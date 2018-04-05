# -*- coding: utf-8 -*-

import logging
import time
from collections import namedtuple
from datetime import datetime

from odoo import api, fields, models, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DATETIME_FORMAT

_logger = logging.getLogger(__name__)

DEFAULT_ERROR = _('Unknown Error')

ERROR_MESSAGE = {
    'title_error': _('Can not find title: {}'),
    'country_error': _('Can not find country_iso_code: {}'),
    'no_parameter': _('Does not have the expected field: {}'),
    'valid_parameter_type': _('Invalid parameter type: {} expected {}'),
    'parameter_singleton': _('Expected singleton: {}'),
}


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_civicrm_id = fields.Integer(string='Civicrm Id', required=False,
                                  help='Civicrm Id')
    _sql_constraints = [
        ('x_civicrm_id', 'unique(x_civicrm_id)',
         'Two partner with the same x_civicrm_id? Impossible!')
    ]

    @staticmethod
    def timestamp_from_string(date_time):
        """ Converts string in datetime format to timestamp
         :param date_time: str, string in datetime format
         :return: float, timestamp
        """
        dt = datetime.strptime(date_time, DATETIME_FORMAT)
        return time.mktime(dt.timetuple())

    def lookup_title_and_country_id(self):
        """ Lookups the ODOO ids for contact title and country_iso_code
         If id is present assign it to parent object
         Else return error message
        """
        title = self.vals.get('title')
        country_iso_code = self.vals.get('country_iso_code')
        if title:
            title_id = self.env['res.partner.title'].search(
                ['|', ('name', '=', str(title)),
                 ('shortcut', '=', str(title))]).id
            if not title_id:
                self.error_log.append(
                    ERROR_MESSAGE.get('title_error', DEFAULT_ERROR).format(
                        title))
            else:
                self.vals.update(title=title_id)

        if country_iso_code:
            country_id = self.env['res.country'].search(
                [('code', '=', str(country_iso_code))]).id
            if not country_id:
                self.error_log.append(
                    ERROR_MESSAGE.get('country_error', DEFAULT_ERROR).format(
                        country_iso_code))
            else:
                self.vals.update(country_id=country_id)

        _logger.debug(
            'country_id = {}, title_id={}'.format(country_id, title_id))

    def save_partner(self, partner):
        """Creates or updates res.partner
         :param partner: res.partner object which want to update
        """
        status = True
        try:
            # Create or update res.partner
            if partner:
                status = partner.write(self.vals)
            else:
                partner = self.create(self.vals)
                self.response_data.update(partner_id=partner.id)

            if not (partner or status):
                self.error_log.append(DEFAULT_ERROR)
                return

            timestamp = self.timestamp_from_string(partner.write_date)
            self.response_data.update(timestamp=int(timestamp))

        except Exception as error:
            _logger.error(error)
            self.error_log.append(str(error))
            self.error_hendler()

    def error_hendler(self):
        """Checks for errors and change response_data if exist
         :return: True if error else False
        """
        is_error = 1
        if self.error_log:
            self.response_data.update(is_error=is_error,
                                      error_log=self.error_log)
            return True
        return False

    def convert_timestamp_param(self, **kwargs):
        """Converts parameter from timestamp in string by parameter key
         :param kwargs: dictionary with value for conversion
         :return: str in DATETIME_FORMAT
        """
        timestamp = kwargs.get('value')
        try:
            return datetime.fromtimestamp(timestamp).strftime(DATETIME_FORMAT)
        except Exception as error:
            _logger.error(error)
            self.error_log.append(str(error))
            self.error_hendler()

    @api.model
    def civicrm_sync(self, input_params):
        """Synchronizes ODOO and CiviCRM.
         Creates or updates res.partner and returns response
         :param input_params: dict of data:{
                                'is_company': bool,
                                'x_civicrm_id': int,
                                'name': str,
                                'display_name': str,
                                'title': str,
                                'street': str,
                                'street2': str,
                                'city': str,
                                'zip': str,
                                'country_iso_code': str,
                                'website': str,
                                'phone': str,
                                'mobile': str,
                                'fax': str,
                                'email': str,
                                'create_date': int,
                                'write_date': int,
                                'active': bool,
                                'customer': bool
                                }
         :return: data in dictionary format: {
                                'is_error': int, 0 when successful and 1 when failed
                                'error_log': str, present when is_error is 1 and should catch the error information
                                'contact_id': int, the id of the synced contact record
                                'partner_id': int, the id of the corresponding partner record in Odoo
                                'timestamp': float, the timestamp when the respond is made
                                }
        """
        self.error_log = []
        self.response_data = {'is_error': 0}
        self.vals = input_params
        if not self.validate_input_params(self.vals):
            return self.get_response()

        x_civicrm_id = self.vals.get('x_civicrm_id')

        # Build response dictionary
        self.response_data.update(contact_id=x_civicrm_id)

        # Check if CiviCRM contact's id exists in ODOO
        partner = self.search([('x_civicrm_id', '=', x_civicrm_id)])

        if len(partner) > 1:
            self.error_log.append(
                ERROR_MESSAGE['parameter_singleton'].format(partner))
            return self.get_response()

        self.response_data.update(partner_id=partner.id)

        _logger.debug('partner = {}'.format(partner))

        # Check if CiviCMR contact's title and country_iso_code exists
        # and have appropriated ids in ODOO
        self.lookup_title_and_country_id()

        # Check for errors and return response with error if exist
        if self.error_log:
            return self.get_response()

        # Create or update res.partner
        self.save_partner(partner)

        return self.get_response()

    def get_response(self):
        """Checks errors and return dictionary response
         :return: response in dictionary format
        """
        self.error_hendler()
        return self.response_data

    def validate_input_params(self):
        """Checks that we get all required parameters in appropriate data type
         :param input_params: dictionary of input parameters
         :return: True if valid else False
        """
        ParamType = namedtuple('Point', ['type', 'required', 'convert_method'])
        param_map = {
            'is_company': ParamType(bool, True, None),
            'x_civicrm_id': ParamType(int, False, None),
            'name': ParamType(str, True, None),
            'display_name': ParamType(str, True, None),
            'title': ParamType(str, False, None),
            'street': ParamType(str, False, None),
            'street2': ParamType(str, False, None),
            'city': ParamType(str, False, None),
            'zip': ParamType(str, False, None),
            'country_iso_code': ParamType(str, False, None),
            'website': ParamType(str, False, None),
            'phone': ParamType(str, False, None),
            'mobile': ParamType(str, False, None),
            'fax': ParamType(str, False, None),
            'email': ParamType(str, True, None),
            'create_date': ParamType(int, False, self.convert_timestamp_param),
            'write_date': ParamType(int, False, self.convert_timestamp_param),
            'active': ParamType(bool, True, None),
            'customer': ParamType(bool, True, None)
        }

        for key, param_type in param_map.items():
            value = self.vals.get(key)
            if value is None and param_type.required:
                self.error_log.append(ERROR_MESSAGE['no_parameter'].format(key))
            elif not isinstance(value, param_type):
                self.error_log.append(ERROR_MESSAGE['valid_parameter_type']
                                      .format(key, param_type))

            if value and param_type.convert_method:
                new_param = param_type.convert_method(key=key, value=value)
                _logger.debug(new_param)
                self.vals[key] = new_param

        return False if self.error_log else True
