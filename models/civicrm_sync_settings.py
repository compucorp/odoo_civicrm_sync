# -*- coding: utf-8 -*-
from odoo import fields, models


class CivicrmSyncSettings(models.TransientModel):
    _name = 'civicrm.sync.settings'

    custom_invoice_reference_prefix = fields.Char(string='Reference Prefix',
                                                  default='CIVI',
                                                  help='Prefix which is added to civicrm contribution')
