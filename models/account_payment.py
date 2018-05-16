# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class account_payment(models.Model):
    _inherit = "account.payment"

    x_civicrm_id = fields.Integer(string='Civicrm Id', required=False,
                                  help='Civicrm Id')

    x_sync_status = fields.Selection([
        ('awaiting', 'Awaiting Sync'),
        ('synced', 'Synced'),
        ('failed', 'Sync failed'),
        (None, 'None'),
    ], default=None, string='Sync Status',
        help='When a payment is registered to an invoice whose x_civicrm_id '
             'is not empty, this field should be set to "Awaiting sync".')

    x_last_retry = fields.Date(string='Last Retry', help='Last Retry')
    x_retry_count = fields.Integer(string='Retry Count', default=0,
                                   help='Retry Count')
    x_last_success_sync = fields.Datetime(string='Last Successful Sync Date',
                                         default=0, help='Last Successful Sync Date')
    x_error_log = fields.Text(string='Error Log', help='Error Log')

    @api.model
    def create(self, vals):
        """ Override method to update sync status
         :param vals: dictionary values
         :return: new account_payment object
        """
        payment = super(account_payment, self).create(vals)
        invoices = payment.invoice_ids
        if invoices and len(invoices) > 1:
            return payment
        invoice = invoices.filtered(lambda invoice: invoice.x_civicrm_id)
        if invoice:
            payment.x_sync_status = 'awaiting'
        return payment
