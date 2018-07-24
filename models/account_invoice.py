# -*- coding: utf-8 -*-

import json
import inspect
import logging
import time
import sys
from collections import namedtuple
from datetime import datetime

from odoo import api, fields, models, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DATETIME_FORMAT

_logger = logging.getLogger(__name__)

UNKNOWN_ERROR = _("Unknown error when synchronize invoice data")
EXCEPTION_ERROR_MESSAGE = _("Exception in file: '{}' line: {} type error: {} messege: {}")

ERROR_MESSAGE = {
    'duplicated_partner_with_contact_id': _(
        "You cannot have two partners with the same civicrm Id"),
    'invalid_parameter_type': _(
        "Wrong CiviCRM request - invalid \"{}\" parameter "
        "data type: {} expected {}"),
    'missed_required_parameter': _(
        "Wrong CiviCRM request - missed required field: {}"),
    'lookup_id_error': _(
        "This {} doesn't exist in ODOO: {}"),
}

LOOK_UP_MAP = {
    'contact_civicrm_id': ('res.partner', 'x_civicrm_id', 'partner_id'),
    'account_code': ('account.account', 'code', 'account_id'),
    'currency_code': ('res.currency', 'name', 'currency_id'),
    'product_code': ('product.product', 'default_code', 'product_id'),
    'tax_name': ('account.tax', 'name', 'invoice_line_tax_ids'),
    'invoice_journal_name': ('account.journal', 'name', 'journal_id'),
    'journal_name': ('account.journal', 'name', 'journal_id'),
    'invoice_civicrm_id': ('account.invoice', 'x_civicrm_id', 'x_civicrm_id'),
    'invoice_line_civicrm_id': ('account.invoice.line', 'x_civicrm_id',
                                'x_civicrm_id'),
}

DUPLICATE_MAP = {
    'refund_date_invoice': 'date'
}


class AccountInvoiceLine(models.Model):
    _inherit = "account.invoice.line"

    x_civicrm_id = fields.Integer(string='Civicrm Id', required=False,
                                  help='Civicrm Id')


class AccountInvoice(models.Model):
    _inherit = "account.invoice"

    x_civicrm_id = fields.Integer(string='Civicrm Id', required=False,
                                  help='Civicrm Id')

    @api.model
    def civicrm_sync(self, input_params):
        """Synchronizes CiviCRM Contributions to Odoo invoice.
         Creates new invoice if not exists and updates it if it is not
         present in Odoo. Returns back to CiviCRM assigned invoice_id and
         update_date and data processing status.
        """
        try:
            _logger.debug('Start CiviCRM contribution to invoice syncing')

            self.error_log = []

            # Build response dictionary
            self.response_data = {'is_error': 0}
            if not self._validate_civicrm_sync_input_params(input_params):
                return self._get_civicrm_sync_response()
            x_civicrm_invice_id = self.vals.get('x_civicrm_id')

            # Assign ODOO contribution_id if exists
            self.response_data.update(contribution_id=x_civicrm_invice_id)

            # Check if CiviCRM contribution_id exists in ODOO
            invoice = self.with_context(active_test=False).search(
                [('x_civicrm_id', '=', x_civicrm_invice_id)], order='id desc',
                limit=1)
            _logger.debug('last invoice({}) with civicrm_id({})'.format(invoice, x_civicrm_invice_id))

            if invoice:
                self.response_data.update(invoice_number=invoice.number)

            invoice_state = invoice.state

            # Create and post new invoice if not exist
            if not invoice:
                invoice = self.save_new_invoice()
                self._invoice_open(invoice)

            # Start line items handling if invoice not posted
            elif invoice_state in ('draft',):
                self._invoice_open(invoice)

            # Start line items match
            elif not self.match_lines(invoice):
                # If no, unreconcile and cancel the invoice.
                # Create a new one and do Line Items Handling.
                # Posted invoice
                # Re-reconcile the payments with the new invoice
                credit_aml_ids = invoice.payment_move_line_ids.ids
                invoice.move_id.line_ids.remove_move_reconcile()
                refund_invoice = self._refund_invoice(invoice)
                refund_invoice.re_reconcile_payment(invoice_number=invoice.number)
                invoice = self.save_new_invoice()
                self._invoice_open(invoice)
                invoice.re_reconcile_payment(credit_aml_ids=credit_aml_ids)

            self.status_and_payment_handling(invoice)

        except Exception as error:
            self.exception_handler(error)


        return self._get_civicrm_sync_response()

    def _validate_civicrm_sync_input_params(self, input_params):
        """ Validates input parameters structure and data type
         :param input_params: dictionary of input parameters
         :return: validation status True or False
        """
        _logger.debug('validate input params')
        self.vals = input_params
        ParamType = namedtuple('ParamType', ['type', 'required',
                                             'convert_method', 'default', 'weight'])

        param_map = {
            'contact_civicrm_id': ParamType(int, True, self.lookup_id, None, 100),
            'x_civicrm_id': ParamType(int, False, None, None, 100),
            'name': ParamType(str, True, None, None, 100),
            'account_code': ParamType(int, True, self.lookup_id, None, 100),
            'invoice_journal_name': ParamType(str, False, self.lookup_id, 'Customer Invoices', 100),
            'currency_code': ParamType(str, False, self.lookup_id, None, 100),
            'date_invoice': ParamType(int, False, self.convert_timestamp_param,
                                      None, 100),
            'line_items': {
                'x_civicrm_id': ParamType(int, False, None, None, 100),
                'product_code': ParamType(str, False, self.lookup_id, None, 100),
                'name': ParamType(str, True, None, None, 100),
                'quantity': ParamType(float, False, None, None, 100),
                'price_unit': ParamType(float, False, None, None, 100),
                'price_subtotal': ParamType(float, False, None, None, 100),
                'account_code': ParamType(int, False, self.lookup_id, None, 100),
                'tax_name': ParamType(list, False, self.lookup_tax_id, None, 100),
            },
            'payments': {
                'x_civicrm_id': ParamType(int, False, None, None, 100),
                'communication': ParamType(str, False, None, None, 100),
                'journal_name': ParamType(str, True, self.lookup_id, None, 100),

                'is_payment': ParamType(int, False, None, None, 100),
                'status': ParamType(str, True, None, '', 100),
                'amount': ParamType(float, False, None, None, 100),
                'payment_date': ParamType((int, str), False,
                                          self.convert_timestamp_param, None, 100),
                'currency_code': ParamType(str, False, self.lookup_id, None, 100),
                'payment_type': ParamType(str, False, None, 'inbound', 100),
                'payment_method_id': ParamType(int, False, None, 1, 100),
                'partner_type': ParamType(str, False, None, 'customer', 100),
            },
            'refund': {
                'filter_refund': ParamType(str, False, None, 'refund', 100),
                'description': ParamType(str, False, None, '', 100),
                'date': ParamType(int, False, self.convert_timestamp_param,
                                  None, 100),
                'date_invoice': ParamType(int, False, self._duplicate_field, 0, 101),
            },
        }
        self._model_name = ''
        self._validate_model(param_map, self.vals)

        return False if self.error_log else True

    def _validate_model(self, param_map, vals):
        """ Recursively validate parameters data
         :param param_map: dictionary with rules to validation
         :param vals: dictionary of input parameters
        """
        for key in sorted(param_map.keys(), key=lambda key: 100 if isinstance(param_map[key],
                                                                              dict) else param_map[key].weight):
            value = vals.get(key)
            new_param_map = param_map.get(key)
            if isinstance(value, list) and isinstance(new_param_map, dict):
                self._model_name = key
                for val in value:
                    self._validate_model(param_map[key], val)
                continue
            if isinstance(value, dict):
                self._model_name = key
                vals = self.vals.get(key)
                self._validate_model(param_map[key], vals)
                continue

            self._validate_value(new_param_map, value, vals, key)

    def _validate_value(self, param_type, value, vals, key):
        """ Validates value and runs convert_method from param_map
         :param param_type: object ParamType with rules for value
         :param value: value to validates
         :param vals: dictionary of input parameters
         :param key: name of validates value
        """
        value = value if value else vals.get(key, param_type.default)
        vals[key] = value
        if param_type.required and value is None:
            self.error_log.append(ERROR_MESSAGE[
                'missed_required_parameter'].format(
                key))
        elif not isinstance(value, param_type.type):
            self.error_log.append(ERROR_MESSAGE['invalid_parameter_type']
                                  .format(key, type(value),
                                          param_type.type))

        if value is not None and param_type.convert_method:
            param_type.convert_method(key=key, value=value, vals=vals)

    def _duplicate_field(self, **kwargs):
        """ Copy value from another field according to the DUPLICATE_MAP
         :param kwargs: dictionary with value for duplicate
        """
        key = kwargs.get('key')
        vals = kwargs.get('vals')
        duplicate_fild_name = DUPLICATE_MAP.get('{}_{}'.format(self._model_name, key))
        vals[key] = vals.get(duplicate_fild_name)

    def lookup_id(self, **kwargs):
        """ Lookups the ODOO ids
         If id exists assign id to parent object
         :param kwargs: dictionary with key value and vals to search
        """
        key = kwargs.get('key')
        value = kwargs.get('value')
        vals = kwargs.get('vals')

        model, field, res = LOOK_UP_MAP.get(key)
        ids = self._lookup_id(key, value, model, field)
        if not ids:
            return
        if isinstance(value, list):
            vals[res] = ids
        else:
            vals[res] = ids[0]
        del vals[key]

    def lookup_tax_id(self, **kwargs):
        """ Lookups the ODOO ids
         If id exists assign id to account.tax object
         :param kwargs: dictionary with key value and vals to search
        """
        key = kwargs.get('key')
        value = kwargs.get('value')
        vals = kwargs.get('vals')

        model, field, res = LOOK_UP_MAP.get(key)
        if not value:
            del vals[key]
            return
        ids = self._lookup_id(key, value, model, field)
        del vals[key]
        if not ids:
            return
        vals[res] = [(6, 0, ids)]

    def _lookup_id(self, key, value, model, field):
        """ Lookups the ODOO ids
         If id exists assign it to parent object
         Else returns error message
         :param key: key for value in input params
         :param value: value to search
         :param model: target ODOO model to search
         :param field: field name from ODOO model to search
         :return: row ids
        """
        if not isinstance(value, list):
            value = [value]
        ids = self.env[model].search(
            [(field, 'in', value)]).ids
        if not ids:
            self.error_log.append(
                ERROR_MESSAGE.get('lookup_id_error', UNKNOWN_ERROR).format(
                    key, value))
            return
        return ids

    def convert_timestamp_param(self, **kwargs):
        """ Converts timestamp parameter into datetime string according
         :param kwargs: dictionary with value for conversion
         :return: str in DATETIME_FORMAT
        """
        timestamp = kwargs.get('value')
        key = kwargs.get('key')
        vals = kwargs.get('vals')
        try:
            date_time = datetime.fromtimestamp(timestamp)
            _logger.debug('date_time value is {} type is {}'.format(date_time, type(date_time)))
            vals[key] = date_time.strftime(DATETIME_FORMAT)
        except Exception as error:
            self.exception_handler(error)

    def save_new_invoice(self):
        """ Creates new invoice
         :return: invoice object
        """
        invoice = self.create(self.vals)
        _logger.debug('create new invoice({})'.format(invoice))
        return invoice

    def create_line(self, line, invoice_id):
        """ Creates invoice line
         :param line: ivoice line values
         :param invoice_id: relation invoice id
        """
        invoice_line = self.env['account.invoice.line']
        line.update(invoice_id=invoice_id)
        return invoice_line.create(line)

    def _invoice_open(self, invoice):
        """ Handles line items, computes taxes and open invoice
         :param invoice: invoice object
        """
        _logger.debug('start open new invoice({})'.format(invoice))
        self.line_items_handling(invoice)
        invoice.compute_taxes()
        invoice.action_invoice_open()
        self.response_data.update(invoice_number=invoice.number)

    def line_items_handling(self, invoice):
        """ Creates/updates or deletes invoice line
         :param invoice: invoice object
        """
        _logger.debug('start line items handling')
        lines = self.vals.get('line_items')
        line_civicrm_id = set(line.get('x_civicrm_id') for line in lines)
        for line in lines:
            x_civicrm_id = line.get('x_civicrm_id')
            invoice_line = invoice.invoice_line_ids.filtered(
                lambda invoice_line: invoice_line.x_civicrm_id == x_civicrm_id)

            if not invoice_line:
                self.create_line(line, invoice.id)
                continue

            if not self.match_line(line, invoice_line):
                self.update_line(line, invoice_line, invoice.id)

        line_to_delete = invoice.invoice_line_ids.filtered(
            lambda invoice_line: invoice_line.x_civicrm_id not in
                                 line_civicrm_id)

        for line in line_to_delete:
            line.unlink()

    def match_line(self, match_line, line):
        """ Compares invoice line items
         :param match_line: dictionary invoice line from input params
         :param line: account.invoice.line to match
         :return: True if items the same, False if not
        """
        for name, field in match_line.items():
            first = self._get_value(line[name], line._fields[name])
            second = self._get_value(field, name)
            if first != second:
                return False
        return True

    def update_line(self, line, invoice_line, invoice_id):
        """ Updates invoice lines
         :param line: dictionary invoice line from input params
         :param invoice_line: account.invoice.line to update
         :param invoice_id: relation invoice id
        """
        line.update(invoice_id=invoice_id)
        if not invoice_line.write(line):
            self.error_log.append(UNKNOWN_ERROR)

    def match_lines(self, invoice):
        """ Checks the if exact same invoices lines exist in the last matched
         invoice in Odoo as per CiviCRM contribution
         :param invoice:  invoice object
         :return: True if line is the same, otherwise False
        """
        _logger.debug('start match lines')
        new_lines = self.vals.get('line_items')
        if len(invoice.invoice_line_ids) != len(new_lines):
            return False

        for line in invoice.invoice_line_ids:
            match_line = self._get_match_invoice_line(new_lines,
                                                      line.x_civicrm_id)
            if match_line is None:
                return False
            if not self.match_line(match_line, line):
                return False
        return True

    def _get_match_invoice_line(self, lines, x_civicrm_id):
        """ Returns line with same x_civicrm_id
         :param lines: invoice line object
         :param x_civicrm_id: civicrm_id
         :return: invoice line object
        """
        for line in lines:
            if line.get('x_civicrm_id') == x_civicrm_id:
                return line

    @staticmethod
    def _match_values(first, second):
        """ Matchs two values
         :param first: first value
         :param second: second value
         :return: True if match, otherwise False
        """
        return True if first == second else False

    @staticmethod
    def _get_value(value, field):
        """ Extracts value before matching
         :param value: field value
         :param field: field type or name
         :return: extract value
        """
        if isinstance(value, models.Model):
            if field.type == 'many2one':
                return value.id
            elif field.type in ['many2many', 'one2many']:
                return value.ids
            elif field.type in ['many2many', 'one2many']:
                return value.ids
        if field == 'invoice_line_tax_ids':
            return value[-1][-1]
        return value

    @api.multi
    def re_reconcile_payment(self, credit_aml_ids=None, invoice_number=None):
        """ Re-reconciles with the invoice """
        self.ensure_one()
        if not credit_aml_ids:
            credit_aml_ids = []
            self._get_outstanding_info_JSON()
            outstanding_JSON = self.outstanding_credits_debits_widget
            if self.has_outstanding:
                outstanding = json.loads(outstanding_JSON)
                for content in outstanding['content']:
                    if content.get('journal_name') == invoice_number:
                        credit_aml_ids.append(content['id'])
        _logger.debug('assign credits({})'.format(credit_aml_ids))
        for credit_aml_id in credit_aml_ids:
            self.assign_outstanding_credit(credit_aml_id)

    def status_and_payment_handling(self, invoice):
        """ Checks payment exists in odoo, refunds invoice
         :param invoice: invoice object
        """
        account_payment = self.env['account.payment']

        x_civicrm_payment_ids = [payment_data.get('x_civicrm_id') for
                                 payment_data in
                                 self.vals.get('payments')]
        payments = account_payment.with_context(active_test=False).search(
            [('x_civicrm_id', 'in', x_civicrm_payment_ids)])

        for payment_data in self.vals.get('payments'):
            _logger.debug('handling payment({})'.format(payment_data))
            x_civicrm_payment_id = payment_data.get('x_civicrm_id')
            payment = payments.filtered(
                lambda payment: payment.x_civicrm_id == x_civicrm_payment_id)
            amount = payment_data.get('amount')
            if payment:
                continue

            elif not payment_data.get('status') or amount < 0:
                payment_data.update(payment_type='outbound')
                amount = -1 * amount if amount < 0 else amount
                payment_data.update(amount=amount)
                if invoice.state == 'paid' and (amount != invoice.amount_total or not self.vals.get('refund')):
                    payment_data.update(partner_id=invoice.partner_id.id)
                    payment = self._create_payment(payment_data)
                    payment.post()
                    self._payment_reconciliations(payment)
                    continue
                refund_invoice = self._refund_invoice(invoice)
                if invoice.state != 'paid':
                    refund_invoice.re_reconcile_payment(invoice_number=invoice.number)
                    continue
                invoice = refund_invoice

            elif 'refund' in invoice.type:
                invoice = self.save_new_invoice()
                self._invoice_open(invoice)

            payment = self._create_payment(payment_data, invoice)
            self._validate_invoice_payment(payment, invoice)

    def _refund_invoice(self, invoice):
        """ Creates account.invoice.refund object and
         refundes invoice
         :param invoice: invoice object
        """
        refund = self.save_refund()
        _logger.debug('create refund_invoice({})'.format(refund))
        view = refund.with_context(active_ids=invoice.ids).compute_refund(mode='refund')
        domains = view.get('domain')
        for domain in domains:
            if domain[0] == 'id':
                refund_invoice = invoice.browse(domain[2])

        refund_invoice.write({'x_civicrm_id': invoice.x_civicrm_id})
        refund_invoice.action_invoice_open()
        _logger.debug('open refund_invoice({})'.format(refund))
        self.response_data.update(creditnote_number=refund_invoice.number)
        return refund_invoice

    def _payment_reconciliations(self, payment):
        """ Gets data for reconciliation and reconciled
         :param payment: payment object
        """
        move = self.env['account.move.line']
        reconciliation_data = move.get_data_for_manual_reconciliation('partner', [payment.partner_id.id])
        for reconciliation in reconciliation_data:
            move_ids = [data.get('id') for data in reconciliation.get('reconciliation_proposition')]
            _logger.debug("reconciliations move_ids = {}".format(move_ids))
            if move_ids:
                move.process_reconciliations(
                    [{'type': None, 'id': None, 'mv_line_ids': move_ids, 'new_mv_line_dicts': []}])


    def _create_payment(self, payment_data, invoice=None):
        """ Updates payment_data, creates payment
         :param payment_data: dictionary payment from input params
         :param invoice: invoice object
        """
        if invoice is not None:
            payment_data.update(invoice_ids=[(6, 0, invoice.ids)])
            payment_data.update(partner_id=invoice.partner_id.id)
            payment_data.update(account_id=invoice.account_id.id)
        account_payment = self.env['account.payment']
        payment = account_payment.create(payment_data)
        _logger.debug('create payment({})'.format(payment))
        return payment

    def _validate_invoice_payment(self, payment, invoice):
        """ Creates the journal items for the payment and updates the
         payment's state to 'posted'.
         :param payment: payment object
        """
        _logger.debug('start validate payment')
        payment.invoice_ids = invoice.ids
        payment.action_validate_invoice_payment()

    def save_refund(self):
        """ Creates refund objects """
        default_data = [{'description': 'Tecnical refund',
                         'date_invoice': fields.Datetime.now(),
                         'date': fields.Date.today()}]
        refunds_data = self.vals.get('refund') if self.vals.get('refund') else default_data

        account_invoice_refund = self.env['account.invoice.refund']
        for refund_data in refunds_data:
            refund_data.update(filter_refund='refund')
            refund = account_invoice_refund.create(refund_data)
        return refund

    def _get_civicrm_sync_response(self):
        """ Checks errors and return dictionary response
         :return: response in dictionary format
        """
        self.error_handler()
        self.response_data.update(timestamp=int(time.time()))
        return self.response_data

    def error_handler(self):
        """ Checks for errors and change response_data if exist
         :return: True if error else False
        """
        is_error = 1
        if self.error_log:
            self.response_data.update(is_error=is_error,
                                      error_log=self.error_log)
            return True
        return False

    def exception_handler(self, error):
        """ Adds error log message if raise exception """
        ex_type, ex, exc_tb = sys.exc_info()
        filename = exc_tb.tb_frame.f_code.co_filename
        line = exc_tb.tb_lineno
        self.error_log.append(EXCEPTION_ERROR_MESSAGE.format(filename,
                                                             line,
                                                             ex_type,
                                                             error))
        self.error_handler()

    @staticmethod
    def timestamp_from_string(date_time):
        """ Converts string in datetime format to timestamp
         :param date_time: str, string in datetime format
         :return: float, timestamp
        """
        dt = datetime.strptime(date_time, DATETIME_FORMAT)
        return time.mktime(dt.timetuple())

    @api.multi
    def assign_outstanding_credit(self, credit_aml_id):
        """ Override method to update sync status
         :param credit_aml_id: int Account move line ids
         :return: bool
        """
        res = super(AccountInvoice, self).assign_outstanding_credit(
            credit_aml_id)
        curframe = inspect.currentframe()
        calframe = inspect.getouterframes(curframe, 2)
        if self.x_civicrm_id and calframe[1][3] != 're_reconcile_payment':
            for payment in self.payment_ids:
                payment.x_sync_status = 'awaiting'
        return res
