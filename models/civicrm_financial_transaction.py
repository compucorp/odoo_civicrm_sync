# -*- coding: utf-8 -*-
from odoo import fields, models


class CivicrmFinancialTransaction(models.Model):
    _name = 'civicrm.financial.transaction'

    x_financial_transaction_id = fields.Integer(
        string='Financial Transaction Id',
        help='The Financial Transaction Id on Civicrm.')

    payment_id = fields.Many2one('account.payment', 'Payment id')
