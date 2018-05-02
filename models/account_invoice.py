# -*- coding: utf-8 -*-

import logging
import time
from collections import namedtuple
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DATETIME_FORMAT

_logger = logging.getLogger(__name__)

UNKNOWN_ERROR = _("Unknown error when synchronize invoice data")

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
    'journal_code': ('account.journal', 'code', 'journal_id'),
    'invoice_civicrm_id': ('account.invoice', 'x_civicrm_id', 'x_civicrm_id'),
    'invoice_line_civicrm_id': ('account.invoice.line', 'x_civicrm_id',
                                'x_civicrm_id'),
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
        _logger.debug('Start CiviCRM contribution to invoice syncing')

        self.error_log = []

        # Build response dictionary
        self.response_data = {'is_error': 0}
        if not self._validate_civicrm_sync_input_params(input_params):
            return self._get_civicrm_sync_response()
        _logger.debug('valid data = {}'.format(self.vals))

        x_civicrm_invice_id = self.vals.get('x_civicrm_id')

        # Assign ODOO contribution_id if exists
        self.response_data.update(contribution_id=x_civicrm_invice_id)

        # Check if CiviCRM contribution_id exists in ODOO
        invoice = self.with_context(active_test=False).search(
            [('x_civicrm_id', '=', x_civicrm_invice_id)], order='id desc',
            limit=1)
        _logger.debug('invoice = {}'.format(invoice))
        invoice_state = invoice.state
        _logger.debug('invoice_state = {}'.format(invoice_state))

        try:

            # Create and post new invoice if not exist
            if not invoice:
                invoice = self.save_new_invoice()
                self.line_items_handling()
                invoice.compute_taxes()
                invoice.action_invoice_open()
                return self._get_civicrm_sync_response()

            if invoice_state in ('draft',):
                self.line_items_handling()
                invoice.compute_taxes()
                invoice.action_invoice_open()
                return self._get_civicrm_sync_response()

            # Start line items match
            if not self.match_lines(invoice):
                # If no, unreconcile and cancel the invoice.
                # Create a new one and do Line Items Handling.
                # Posted invoice
                # Re-reconcile the payments with the new invoice

                self.move_id.reverse_moves(invoice)
                invoice.action_invoice_cancel()
                invoice = self.save_new_invoice()
                self.line_items_handling()
                invoice.compute_taxes()
                invoice.action_invoice_open()

            self.status_and_payment_handling()

        except UserError as error:
            _logger.error(error)
            self.error_log.append(str(error))
            self.error_handler()

        return self._get_civicrm_sync_response()

    def _validate_civicrm_sync_input_params(self, input_params):
        """ Validates input parameters structure and data type
         :param input_params: dictionary of input parameters
         :return: validation status True or False
        """
        self.vals = input_params
        ParamType = namedtuple('ParamType', ['type', 'required',
                                             'convert_method', 'default'])

        param_map = {
            'contact_civicrm_id': ParamType(int, True, self.lookup_id, None),
            'x_civicrm_id': ParamType(int, False, None, None),
            'name': ParamType(str, True, self._add_prefix, None),
            'account_code': ParamType(int, True, self.lookup_id, None),
            'journal_code': ParamType(str, False, self.lookup_id, 'INV'),
            'currency_code': ParamType(str, False, self.lookup_id, None),
            'line_items': {
                'x_civicrm_id': ParamType(int, False, None, None),
                'product_code': ParamType(str, False, self.lookup_id, None),
                'name': ParamType(str, True, None, None),
                'quantity': ParamType(float, False, None, None),
                'price_unit': ParamType(float, False, None, None),
                'price_subtotal': ParamType(float, False, None, None),
                'account_code': ParamType(int, False, self.lookup_id, None),
                'tax_name': ParamType(list, False, self.lookup_tax_id, None),
            },
        }

        self._validate_model(param_map, self.vals)

        return False if self.error_log else True

    def _validate_model(self, param_map, vals):
        """ Recursively validate parameters data
         :param param_map: dictionary with rules to validation
         :param vals: dictionary of input parameters
        """
        for key, param_type in param_map.items():
            value = vals.get(key)
            new_param_map = param_map.get(key)
            if isinstance(value, list) and isinstance(new_param_map, dict):
                for val in value:
                    self._validate_model(param_map[key], val)
                continue
            if isinstance(value, dict):
                vals = self.vals.get(key)
                self._validate_model(param_map[key], vals)
                continue

            self._validate_value(param_type, value, vals, key)

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

    def _add_prefix(self, **kwargs):
        key = kwargs.get('key')
        value = kwargs.get('value')
        vals = kwargs.get('vals')
        civicrm_sync_settings = self.env['civicrm.sync.settings']
        prefix = civicrm_sync_settings.custom_invoice_reference_prefix
        if not prefix:
            prefix = 'CIVI'
        vals[key] = '{} {}'.format(prefix, value)

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
        ids = self._lookup_id(key, value, model, field)
        del vals[key]
        if not ids:
            return
        vals[res] = [(6, 0, ids)]

    def _lookup_id(self, key, value, model, field, error_ignore=False):
        """ Lookups the ODOO ids
         If id exists assign it to parent object
         Else returns error message
         :param key: key for value in input params
         :param value: value to search
         :param model: ODOO model in which to search
         :param field: field name from ODOO model to search
         :param error_ignore: ignore error flag
         :return: row ids
        """
        _logger.debug('lookup {} {} {}'.format(model, field, value))
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

    def save_new_invoice(self):
        """ Creates new invoice
         :return: invoice object
        """
        _logger.debug('start save new incvoice')
        invoice = self.create(self.vals)
        _logger.debug('create invoice = {}'.format(invoice))
        lines = self.vals.get('line_items')
        for line in lines:
            self.create_line(line, invoice.id)
        return invoice

    def create_line(self, line, invoice_id):
        """ Creates invoice line
         :param line: ivoice line values
         :param invoice_id: relation invoice id
        """
        invoice_line = self.env['account.invoice.line']
        line.update(invoice_id=invoice_id)
        line_invoice = invoice_line.create(line)
        _logger.debug('create line = {}'.format(line_invoice))

    # TODO in COS-24
    def line_items_handling(self):
        pass

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
        _logger.debug(
            'update line = {} ,invoice_line ={}'.format(line, invoice_line))
        line.update(invoice_id=invoice_id)
        if not invoice_line.write(line):
            self.error_log.append(UNKNOWN_ERROR)

    def match_lines(self, invoice):
        """ Checks the if exact same invoices lines exist in the last matched
         invoice in Odoo as per CiviCRM contribution
         :param invoice:
         :return: True if line is the same, otherwise False
        """
        _logger.debug('start match_line')
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
         :param second: second first value
         :return: True if match, False if not
        """
        _logger.debug('MATCHING {} == {}'.format(first, second))
        return True if first == second else False

    @staticmethod
    def _get_value(value, field):
        """ Extracts value before matching
         :param value: field value
         :param field: field type or name
         :return: extract value
        """
        _logger.debug('value = {} field = {}'.format(value, field))
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

    # TODO in COS-25
    def status_and_payment_handling(self):
        pass

    def _get_civicrm_sync_response(self):
        """ Checks errors and return dictionary response
         :return: response in dictionary format
        """
        self.error_handler()
        _logger.debug('response = {}'.format(self.response_data))
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

    @staticmethod
    def timestamp_from_string(date_time):
        """ Converts string in datetime format to timestamp
         :param date_time: str, string in datetime format
         :return: float, timestamp
        """
        _logger.debug('convert to timestamp {}'.format(date_time))
        dt = datetime.strptime(date_time, DATETIME_FORMAT)
        return time.mktime(dt.timetuple())
