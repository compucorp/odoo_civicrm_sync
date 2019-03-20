# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    @api.multi
    def process_reconciliations(self, data):
        super(AccountBankStatementLine, self).process_reconciliations(data = data)
        self.env.cr.execute("SELECT aml.pa  yment_id, amamlr.account_invoice_id FROM account_move_line as aml inner join  account_invoice_account_move_line_rel as amamlr on amamlr.account_move_line_id = aml.id where aml.name = %s and aml.partner_id = %s and credit > 0", (data[0]['counterpart_aml_dicts'][0]['name'], data[0]['partner_id']))
        fetchedData = self.env.cr.fetchone()
        if fetchedData:
            payment_id = fetchedData[0]
            payment = self.env['account.payment'].search([('id', '=', payment_id)])
            invoice_id = fetchedData[1]
            invoice = self.env['account.invoice'].search([('id', '=', invoice_id)])
            if invoice.x_civicrm_id and not payment.x_civicrm_ids and not payment.x_sync_status:
                payment.x_sync_status = 'awaiting'
