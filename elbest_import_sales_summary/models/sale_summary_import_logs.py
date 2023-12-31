# -*- coding: utf-8 -*-

import datetime

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class SaleSummaryImportLogs(models.Model):
    _name = 'sale.summary.import.logs'
    _description = 'Sale Summary Import Logs'

    name = fields.Char(string="Name", required=True, copy=False, readonly=True, default=lambda self: _('New'))
    file_name = fields.Char(string="Reconciliation Number", required=True, copy=False, readonly=True)
    sale_ids = fields.Many2many('sale.order', string='Sale Orders')
    line_ids = fields.One2many('sale.summary.import.log.line', 'log_id', string='Sale Summary Import Lines')
    date = fields.Datetime('Imported Date', default=fields.Datetime.now)
    reconciliation_date = fields.Char('Reconciliation Date', readonly=True)
    station_number = fields.Char('Station Number', readonly=True)
    sale_count = fields.Integer('Sale Count', compute='_compute_sale_count')
    not_imported_lines = fields.Text('Not Imported Products', readonly=True)
    zip_file_name = fields.Char('Zip File Name', compute='_compute_zip_file_name', store=True)
    picking_type_id = fields.Many2one('stock.picking.type', string="Operation Type", compute='_compute_picking_type', store=False)

    # @api.depends('file_name', 'name', 'station_number')
    def _compute_picking_type(self):
        """
        @private: get operation type for the station number
        """
        for rec in self:
            warehouse_id = rec.env['stock.warehouse'].search([('name', '=', rec.station_number)], limit=1)
            rec.update({
                'picking_type_id': warehouse_id.out_type_id.id
            })

    @api.depends('file_name', 'name', 'station_number')
    def _compute_zip_file_name(self):
        """
        @private - compute file name for Google Drive zip
        """
        for rec in self:
            try:
                name = rec.file_name.strip()
                station_number = rec.station_number
                rec.update({
                    'zip_file_name': str((station_number, f'20{name[0:2]}-{name[2:4]}-{name[4:6].lstrip("0")}.zip'))
                })
            except Exception as e:
                rec.update({
                    'zip_file_name': False
                })
                continue

    def action_open_import_missing_lines_wizard(self):
        """
        @public - action for open import wizard again for not imported lines
        """
        lines_can_import = [eval(x.split('-')[0]) for x in self.not_imported_lines.split('\n') if self.env['product.product'].search([('default_code', '=', eval(x.split('-')[0])[0])])]
        not_imported_lines = [x for x in self.not_imported_lines.split('\n') if not self.env['product.product'].search([('default_code', '=', eval(x.split('-')[0])[0])])]
        if not lines_can_import:
            raise UserError(_('Not able to import the lines, Please check the errors and resolve for import not imported products'))
        view = self.env.ref('elbest_import_sales_summary.sale_summary_import_wizard_view_form')
        return {
            'name': _('Sales Summary Import'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'sale.summary.import.wizard',
            'views': [(view.id, 'form')],
            'view_id': view.id,
            'target': 'new',
            'context': {
                'default_state': 'uploaded',
                'default_line_ids': [(0, 0, {
                    'product_id': self.env['product.product'].sudo().search([('default_code', '=', x[0])], limit=1).id,
                    'quantity': float(x[1]),
                    'price': float(x[3]),
                }) for x in lines_can_import],
                'default_not_imported_lines': '\n'.join(not_imported_lines),
                'default_reconciliation_number': self.file_name,
                'default_reconciliation_date': self.reconciliation_date,
                'default_station_number': self.station_number,
            },
        }

    def _compute_sale_count(self):
        """
        @private - compute assigned sale order count
        """
        self.update({
            'sale_count': len(self.sale_ids)
        })

    @api.model_create_multi
    def create(self, vals_list):
        """
        @override - assign sequence for the sale summary import logs
        """
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.summary.import.log') or '/'
        return super().create(vals_list)

    def action_view_sale_order(self):
        """
        @public - action for view assigned sale order
        """
        action = self.env['ir.actions.actions']._for_xml_id('sale.action_orders')
        if self.sale_count == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = self.sale_ids.id
        else:
            action['domain'] = [('id', 'in', self.sale_ids.ids)]
        return action

    def _cron_fetch_data_from_google_drive(self):
        """
        @private - cron function for fetch data from Google Drive
        """
        drive_config = self.env['google.drive.configuration'].sudo().search([('active', '=', True)], limit=1)
        if not drive_config:
            raise ValidationError(_(f'No google drive configuration found for company {self.env.company.name}!'))
        else:
            drive_config.fetch_sale_summary_data()


class SaleSummaryImportLogLine(models.Model):
    _name = 'sale.summary.import.log.line'
    _description = 'Sale Summary Import Log Line'

    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float('Quantity')
    price = fields.Monetary('Price')
    company_id = fields.Many2one(comodel_name='res.company', required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related="company_id.currency_id", required=True, string='Currency')
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)
    sale_order_status = fields.Selection(related='sale_order_id.state')
    log_id = fields.Many2one('sale.summary.import.logs', string='Log')
