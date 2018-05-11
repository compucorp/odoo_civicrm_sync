# -*- coding: utf-8 -*-
import logging
import requests
import xml.etree.ElementTree as ElementTree
from datetime import datetime
from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PaymentSync(models.Model):
    _name = "payment.sync"

    @api.model
    def sync_payments(self):
        """ Syncs Odoo payments to CiviCRM
         :return:
        """
        _logger.debug("Payment Sync Started")
        payments = self._get_payments()
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
            if self._sync(payment):
                self._send_report(payment)

    def _sync(self, payment):
        """ Syncs single record of Payment to CiviCRM
         :param payment: account_payment model
         :return: bool True on success, False on failure
        """
        data = self._fill_sync_data(payment)
        # get url to sync
        url = self.env.user.company_id.civicrm_instance_url
        api_key = self.env.user.company_id.civicrm_api_key
        site_key = self.env.user.company_id.civicrm_site_key
        if not url or not api_key or not site_key:
            raise UserError("CiviCRM setting not filled")
        xml_doc = self._create_xml_with_data(data)
        response = self._do_request(url, api_key, site_key, xml_doc)
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
            if payment.x_retry_count >= self.env.user.company_id.retry_threshold:
                payment.write({'x_sync_status': status})
            else:
                payment.write({'x_retry_count': payment.x_retry_count + 1})
        elif status == 'synced':
            payment.write({'x_sync_status': status})
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
        update = {'x_last_retry': datetime.now().date()}
        if response.status_code >= 400:
            update.update({
                'x_error_log': response.text,
            })
            return False
        response_xml = ElementTree.XML(response.text)
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

    @staticmethod
    def _fill_sync_data(payment):
        """ Fills request body with payment's data
         :param payment: account_payment model
         :return: dict with data
        """
        return [
            {"to_financial_account_id": payment.journal_id.name},
            {"total_amount": payment.amount},
            {"trxn_date": payment.payment_date},
            {"currency": payment.currency_id.name}
        ]

    def _get_payments(self):
        """ Gets payments from db
         :return: account_payment models list
        """
        return self.env['account.payment'].search(
            [
                ('x_sync_status', '=', 'awaiting'),
                ('payment_date', '<=', datetime.now().date())
            ]
        )

    def _send_report(self, payment):
        """ Sends email with information regarding payment sync error
         :param payment: account.payment model
         :return: void
        """
        template = self.env.ref('odoo_civicrm_sync.odoo_sivicrm_sync_error')
        self.env['mail.template'].browse(template.id).send_mail(payment.id)
