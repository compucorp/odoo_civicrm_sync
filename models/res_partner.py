# -*- coding: utf-8 -*-

import logging
import time
from collections import namedtuple
from datetime import datetime

from odoo import api, fields, models, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DATETIME_FORMAT

_logger = logging.getLogger(__name__)

UNKNOWN_ERROR = _("Unknown error when updating res.partner data")

ERROR_MESSAGE = {
    'title_error': _("This title doesn't exist in ODOO: {}"),
    'country_error': _("This country_iso_code doesn't exist in ODOO: {}"),
    'missed_required_parameter': _(
        "Wrong CiviCRM request - missed required field: {}"),
    'invalid_parameter_type': _(
        "Wrong CiviCRM request - invalid \"{}\" parameter "
        "data type: {} expected {}"),
    'duplicated_partner_with_contact_id': _(
        "You cannot have two partners with the same civicrm Id"),
}


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_civicrm_id = fields.Integer(string='Civicrm Id', required=False,
                                  help='Civicrm Id')
    _sql_constraints = [
        ('x_civicrm_id', 'unique(x_civicrm_id)',
         ERROR_MESSAGE['duplicated_partner_with_contact_id'])
    ]

    @api.model
    def civicrm_sync(self, input_params):
        """Synchronizes CiviCRM contact to Odoo partner.
         Creates new partners if not exists and updates is it is
         present in Odoo. Returns back to CiviCRM assigned partner_id and
         update_date and data processing status.

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
                                'is_error': int, value from list [0, 1]
                                'error_log': str, not empty when is_error = 1
                                'contact_id': int, CiviCRM contact_id
                                'partner_id': int, Odoo partner_id
                                'timestamp': float, respond timestamp
                                }
        """
        self.error_log = []

        # Build response dictionary
        self.response_data = {'is_error': 0}

        # Validate CiviCRM input request structure and data
        if not self._validate_civicrm_sync_input_params(input_params):
            return self._get_civicrm_sync_response()

        # Check if CiviCRM contact id exists in ODOO
        partner = self.with_context(active_test=False).search(
            [('x_civicrm_id', '=', self.vals.get('x_civicrm_id'))])

        # Assign ODOO partner_id if exists
        self.response_data.update(partner_id=partner.id)

        _logger.debug('partner = {}'.format(partner))

        # Create or update res.partner data
        self.save_partner(partner)

        return self._get_civicrm_sync_response()

    def _validate_civicrm_sync_input_params(self, input_params):
        """Validates input parameters structure and data type
         :param input_params: dictionary of input parameters
         :return: validation status True or False
        """
        self.vals = input_params
        ParamType = namedtuple('Point', ['type', 'required',
                                         'convert_method', 'default'])
        param_map = {
            'is_company': ParamType(bool, True, None, None),
            'x_civicrm_id': ParamType(int, False, None, None),
            'name': ParamType(str, True, None, None),
            'display_name': ParamType(str, True, None, None),
            'title': ParamType(str, False, None, None),
            'street': ParamType(str, False, None, None),
            'street2': ParamType(str, False, None, None),
            'city': ParamType(str, False, None, None),
            'zip': ParamType(str, False, None, None),
            'country_iso_code': ParamType(str, False, None, None),
            'website': ParamType(str, False, None, None),
            'phone': ParamType(str, False, None, None),
            'mobile': ParamType(str, False, None, None),
            'fax': ParamType(str, False, None, None),
            'email': ParamType(str, True, None, None),
            'create_date': ParamType((int, str), False,
                                     self.convert_timestamp_param, None),
            'write_date': ParamType((int, str), False,
                                    self.convert_timestamp_param, None),
            'active': ParamType(bool, True, None, None),
            'customer': ParamType(bool, True, None, True)
        }

        for key, param_type in param_map.items():
            value = self.vals.get(key, param_type.default)
            if param_type.required and value is None:
                self.error_log.append(ERROR_MESSAGE[
                    'missed_required_parameter'].format(
                    key))
            elif not isinstance(value, param_type.type):
                self.error_log.append(ERROR_MESSAGE['invalid_parameter_type']
                                      .format(key, type(value),
                                              param_type.type))

            x_civicrm_id = self.vals.get('x_civicrm_id')

            # Assign CiviCRM contact_id
            self.response_data.update(contact_id=x_civicrm_id)

            if value and param_type.convert_method:
                new_param = param_type.convert_method(key=key, value=value)
                _logger.debug(new_param)
                self.vals[key] = new_param

        # Check if CiviCMR contact's title and country_iso_code exists
        # and have appropriated ids in ODOO
        self.lookup_country_id()
        self.lookup_title_id()

        return False if self.error_log else True

    def convert_timestamp_param(self, **kwargs):
        """Converts timestamp parameter into datetime string according
         :param kwargs: dictionary with value for conversion
         :return: str in DATETIME_FORMAT
        """
        timestamp = kwargs.get('value')
        try:
            return datetime.fromtimestamp(timestamp).strftime(DATETIME_FORMAT)
        except Exception as error:
            _logger.error(error)
            self.error_log.append(str(error))
            self.error_handler()

    def _get_civicrm_sync_response(self):
        """Checks errors and return dictionary response
         :return: response in dictionary format
        """
        self.error_handler()
        return self.response_data

    def error_handler(self):
        """Checks for errors and change response_data if exist
         :return: True if error else False
        """
        is_error = 1
        if self.error_log:
            self.response_data.update(is_error=is_error,
                                      error_log=self.error_log)
            return True
        return False

    def lookup_country_id(self):
        """ Lookups the ODOO ids for contact country_iso_code
         If id is present assign it to parent object
         Else return error message
        """
        country_iso_code = self.vals.get('country_iso_code')
        if country_iso_code:
            country_id = self.env['res.country'].search(
                [('code', '=', str(country_iso_code))]).id
            if not country_id:
                self.error_log.append(
                    ERROR_MESSAGE.get('country_error', UNKNOWN_ERROR).format(
                        country_iso_code))
            else:
                self.vals.update(country_id=country_id)

    def lookup_title_id(self):
        """ Lookups the ODOO ids for contact title
         If id is present assign it to parent object
         Else return error message
        """
        title = self.vals.get('title')
        if title:
            title_id = self.env['res.partner.title'].search(
                ['|', ('name', '=', str(title)),
                 ('shortcut', '=', str(title))]).id
            if not title_id:
                self.error_log.append(
                    ERROR_MESSAGE.get('title_error', UNKNOWN_ERROR).format(
                        title))
            else:
                self.vals.update(title=title_id)

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

                # Assign CiviCRM partner_id
                self.response_data.update(partner_id=partner.id)

            if not (partner or status):
                self.error_log.append(UNKNOWN_ERROR)
                return

            # Assign CiviCRM timestamp
            timestamp = self.timestamp_from_string(partner.write_date)
            self.response_data.update(timestamp=int(timestamp))

        except Exception as error:
            _logger.error(error)
            self.error_log.append(str(error))
            self.error_handler()

    @staticmethod
    def timestamp_from_string(date_time):
        """ Converts string in datetime format to timestamp
         :param date_time: str, string in datetime format
         :return: float, timestamp
        """
        dt = datetime.strptime(date_time, DATETIME_FORMAT)
        return time.mktime(dt.timetuple())
