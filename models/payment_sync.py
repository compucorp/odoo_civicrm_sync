# -*- coding: utf-8 -*-
import logging
import requests
import time
import xml.etree.ElementTree as ElementTree
from datetime import datetime
from odoo import api, models, fields
from odoo.exceptions import UserError
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DATE_FORMAT

_logger = logging.getLogger(__name__)


class PaymentSync(models.TransientModel):
    _name = "payment.sync"

    payments = fields.Many2many('account.payment', string='Payments')

    @api.model
    def sync(self):
        """ Syncs Odoo payments to CiviCRM
         :return:
        """
        _logger.debug("Payment Sync Started")
        payments = self._get_awaiting_payments()
        if payments:
            self._process_payments(payments)
        else:
            _logger.debug("No payments were found")

    def _process_payments(self, payments):
        """ Processing payments sync
         :param payments: list of payments
         :return: list of failed payments
        """
        for payment in payments:
            if not payment.invoice_ids:
                continue
            self._sync_single_payment(payment)
        self._send_error_email(payments)

    def _sync_single_payment(self, payment):
        """ Syncs single record of Payment to CiviCRM
         :param payment: account_payment model
         :return: bool True on success, False on failure
        """
        # get url to sync
        url = self.env.user.company_id.civicrm_instance_url
        api_key = self.env.user.company_id.civicrm_api_key
        site_key = self.env.user.company_id.civicrm_site_key
        if not url or not api_key or not site_key:
            raise UserError("CiviCRM setting not filled")

        data = self._fill_sync_data(payment)
        xml_doc = self._create_xml_with_data(data)
        response = self._do_request(url, api_key, site_key, xml_doc)
        _logger.debug('CiviCRM sync responce = {}'.format(response.text))
        result = self._validate_sync_response(response, payment)
        self._change_payment_status(payment, 'synced' if not result else
        'failed')
        return result

    @staticmethod
    def _do_request(url, api_key, site_key, xml_doc):
        """ Does request to civiCRM
         :param url: Url to perform request
         :param xml_doc: xml doc request body
         :return: xml response
        """
        headers = {'Content-Type': 'application/xml'}
        api = "entity=OdooSync&action=transaction"
        return requests.post(
            "{}?{}&key={}&api_key={}".
                format(url, api, site_key, api_key),
            data=xml_doc,
            headers=headers
        )

    @staticmethod
    def _create_xml_with_data(data):
        """ Creates xml document using data and returns it
         :param data: list of parameters
         :return: string xml document
        """
        # Going through xml structure to <struct> element
        # which has to contain payment data
        request_xml = ElementTree.Element('AATAvailReq')
        params = ElementTree.SubElement(request_xml, 'params')
        param = ElementTree.SubElement(params, 'param')
        value = ElementTree.SubElement(param, 'value')
        struct = ElementTree.SubElement(value, 'struct')

        for data in data:
            for key, val in data.items():
                financial_trxn = ElementTree.SubElement(struct,
                                                        'financial_trxn')
                name = ElementTree.SubElement(financial_trxn, 'name')
                name.text = str(key)
                data_value = ElementTree.SubElement(financial_trxn, 'value')
                if val:
                    data_value.text = str(val)

        return ElementTree.tostring(request_xml, 'utf8', 'xml')

    def _change_payment_status(self, payment, status):
        """ Changes status of payment according to
         :param payment: account_payment model
         :param status: str status to change
         :return: void
        """
        prev_status = payment.x_sync_status
        if status == 'failed':
            payment.write({'x_retry_count': payment.x_retry_count + 1})
            if payment.x_retry_count >= self.env.user.company_id.retry_threshold:
                payment.write({'x_sync_status': status})
        elif status == 'synced':
            payment.write({
                'x_sync_status': status,
                'x_last_success_sync': fields.Datetime.now(),
                'x_retry_count': 0,
                'x_error_log': None,
                'x_last_retry': None,
            })
        if prev_status == payment.x_sync_status:
            _logger.debug(
                "Status of payment with civi_crm_id: {} was changed from {} to {}".
                    format(payment.x_civicrm_id, prev_status, status))

    @staticmethod
    def _validate_sync_response(response, payment):
        """ Validates response on failure
         :param response:
         :return:
        """
        update = {'x_last_retry': fields.Datetime.now()}
        if response.status_code >= 400:
            update.update({
                'x_error_log': response.text,
            })
            return False
        response_xml = ElementTree.XML(response.text)
        if not response_xml:
            return False
        result_set = response_xml.find('Result')
        is_error = int(result_set.find('is_error').text)
        if is_error:
            error_message = str(result_set.find('error_message').text)
            update.update({
                'x_error_log': error_message,
            })
        else:
            transaction_id = int(result_set.find('transaction_id').text)
            update.update({
                'x_civicrm_id': transaction_id
            })
        payment.write(update)
        return bool(is_error)

    def _fill_sync_data(self, payment):
        """ Fills request body with payment's data
         :param payment: account_payment model
         :return: dict with data
        """
        payment_to_invoice = max(payment.invoice_ids)

        if not payment_to_invoice:
            raise UserError('No invoice connected to payment was found')

        dt = datetime.strptime(payment.payment_date, DATE_FORMAT)
        payment_date = time.mktime(dt.timetuple())

        return [
            {"to_financial_account_name": payment.journal_id.name},
            {"total_amount": payment.amount},
            {"trxn_date": int(payment_date)},
            {"currency": payment.currency_id.name},
            {"invoice_id": payment_to_invoice.x_civicrm_id}
        ]

    def _get_awaiting_payments(self):
        """ Gets payments from db
         :return: account_payment models list
        """
        return self.env['account.payment'].search(
            [
                ('x_sync_status', '=', 'awaiting'),
                ('payment_date', '<=', fields.Date.today())
            ],
        )

    def _send_error_email(self, payments):
        """ Sends email with information regarding payment sync error
         :param payment: account.payment model
         :return: void
        """
        template = self.env.ref('odoo_civicrm_sync.odoo_sivicrm_sync_error')
        payments = payments.filtered(lambda payment: payment.x_sync_status == 'failed')
        if payments:
            sync = self.create({'payments':[(6, 0, payments.ids)]})
            self.env['mail.template'].browse(template.id).send_mail(sync.id)
