# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    civicrm_instance_url = fields.Char(
        string='CiviCRM URL',
        help='Specify the address of the CiviCRM Instance that Odoo should '
             'sync to.')

    civicrm_site_key = fields.Char(
        string='CiviCRM Site Key',
        help='Specify the CiviCRM Site key Odoo should use in the API calls '
             'sent to CiviCRM.')

    civicrm_api_key = fields.Char(
        string='CiviCRM API Key',
        help='Specify the CiviCRM API key Odoo should use in the API calls '
             'sent to CiviCRM.')

    batch_size = fields.Integer(
        string='Batch Size',
        default=500,
        help='The number of the records should be synced every job run.')

    retry_threshold = fields.Integer(
        string='Retry Threshold',
        help='The number of sync retry should occur before the "Sync Status" '
             'of the relevant entity should be marked as "Sync failed".')

    error_notice_address = fields.Char(
        string='Error Notice Address',
        help='The email addresses that the sync error report email should be '
             'sent to. Multiple email addresses can be entered and separated '
             'by comma.')


class CivicrmSyncSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    civicrm_instance_url = fields.Char(
        related='company_id.civicrm_instance_url',
        string='CiviCRM URL',
        help='Specify the address of the CiviCRM Instance that Odoo should '
             'sync to.')

    civicrm_site_key = fields.Char(
        related='company_id.civicrm_site_key',
        string='CiviCRM Site Key',
        help='Specify the CiviCRM Site key Odoo should use in the API calls '
             'sent to CiviCRM.')

    civicrm_api_key = fields.Char(
        related='company_id.civicrm_api_key',
        string='CiviCRM API Key',
        help='Specify the CiviCRM API key Odoo should use in the API calls '
             'sent to CiviCRM.')

    batch_size = fields.Integer(
        related='company_id.batch_size',
        string='Batch Size',
        default=500,
        help='The number of the records should be synced every job run.')

    retry_threshold = fields.Integer(
        related='company_id.retry_threshold',
        string='Retry Threshold',
        help='The number of sync retry should occur before the "Sync Status" '
             'of the relevant entity should be marked as "Sync failed".')

    error_notice_address = fields.Char(
        related='company_id.error_notice_address',
        string='Error Notice Address',
        help='The email addresses that the sync error report email should be '
             'sent to. Multiple email addresses can be entered and separated '
             'by comma.')
