# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    @api.multi
    def process_reconciliations(self, data):
        """ Overrides process_reconciliations method that
         process reconciled statements. The purpose is to set
         the payments created by the reconciliation sync status to "awaiting"
         so they get synced back to CiviCRM instead of being ignored.
         And since the invoice won't be linked directly to the payment but
         instead  the move lines, we determine it by checking the move lines
         that are connected to the payment.
        """
        super(AccountBankStatementLine, self).process_reconciliations(data = data)
        after_reconciliation_data = self._get_after_reconciliation_payment_and_invoice(data)
        if after_reconciliation_data:
            payment = after_reconciliation_data['payment']
            invoice = after_reconciliation_data['invoice']
            if invoice.x_civicrm_id and not payment.x_civicrm_ids and not payment.x_sync_status:
                payment.x_sync_status = 'awaiting'


    def _get_after_reconciliation_payment_and_invoice(self, data):
        try:
            self.env.cr.execute("""
            SELECT aml.pa  yment_id, amamlr.account_invoice_id FROM account_move_line AS aml 
            INNER JOIN  account_invoice_account_move_line_rel as amamlr ON amamlr.account_move_line_id = aml.id 
            WHERE aml.name = %s AND aml.partner_id = %s AND credit > 0 LIMIT 1""",
                                (data[0]['counterpart_aml_dicts'][0]['name'], data[0]['partner_id']))
            record = self.env.cr.fetchone()
            payment = self.env['account.payment'].search([('id', '=', record[0])])
            invoice = self.env['account.invoice'].search([('id', '=', record[1])])
            return {"payment" : payment, "invoice" : invoice}
        except:
            return None
