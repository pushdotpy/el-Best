# -*- coding: utf-8 -*-

from urllib.request import urlopen

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class SaleSummaryImportWizardViews(models.TransientModel):
    _name = 'sale.summary.import.wizard'
    _description = 'Sale Summary Import Wizard'

    file = fields.Binary('File', help="File to upload")
    file_name = fields.Char('File Name')
    reconciliation_number = fields.Char('Reconciliation Number', readonly=True)
    reconciliation_date = fields.Char('Reconciliation Date', readonly=True)
    station_number = fields.Char('Station Number', readonly=True)
    state = fields.Selection([
        ('uploading', 'Uploading'),
        ('uploaded', 'Uploaded'),
        ('done', 'Done')
    ], string='State', default='uploading')
    line_ids = fields.One2many('sale.summary.import.wizard.line', 'wizard_id', string='Sale Summary Import Wizard Lines')
    not_imported_lines = fields.Text('Not Imported Lines', readonly=True)

    def action_import(self):
        """
        @public - action for import sale summary report file
        """
        if not self.file:
            raise UserError(_('Please attach a file to upload'))
        if self.file_name[-3:] != 'txt':
            raise UserError(_('Invalid file, Please upload .txt format file'))
        if self.env['sale.summary.import.logs'].sudo().search([('file_name', '=', self.file_name.split('_')[1])]):
            raise ValidationError(f'{self.file_name} - File already existing in the system.')
        try:
            # Read file
            file_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') + '/web/content/sale.summary.import.wizard/%s/file/%s' % (self.id, self.file_name)
            i = 0
            indexing = []
            text_data = []
            for line in urlopen(file_url):
                try:
                    line = line.decode('utf-8').replace('\r\n', '')
                    if line != '':
                        text_data.append(line)
                        if 'VENTES D\'ARTICLE A 7 CHARACTERS' in line:
                            indexing.append(i + 1)
                        if 'STATISTIQUES DE QUART' in line:
                            indexing.append(i)
                        i += 1
                except:
                    continue
            # writing data
            product_summary = [[d for d in x.split(' ') if d != ''] for x in text_data[indexing[0]: indexing[1]]]
            import_data = [{
                'product_id': self.env['product.product'].sudo().search([('default_code', '=', x[0])], limit=1).id,
                'quantity': float(x[1]),
                'price': float(x[3]),
                'wizard_id': self.id
            } for x in product_summary if self.env['product.product'].sudo().search([('default_code', '=', x[0])], limit=1).id]
            not_imported_lines = '\n'.join([f'{x} - Reason: Product not found in the system' for x in product_summary if not self.env['product.product'].sudo().search([('default_code', '=', x[0])], limit=1).id])
            self.env['sale.summary.import.wizard.line'].create(import_data)
            self.sudo().write({
                'state': 'uploaded',
                'not_imported_lines': not_imported_lines,
                'reconciliation_number': self.file_name.split('_')[1],
                'reconciliation_date': text_data[8].strip(),
                'station_number': self.file_name.split('_')[0]
            })
        except Exception as e:
            raise UserError(_(f'.txt file format not supported. Please check and try again with the correct txt file. \n\nError\n{e}'))
        # open wizard with imported data
        view = self.env.ref('elbest_import_sales_summary.sale_summary_import_wizard_view_form')
        return {
            'name': _('Sales Summary Import'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'sale.summary.import.wizard',
            'views': [(view.id, 'form')],
            'view_id': view.id,
            'res_id': self.id,
            'target': 'new',
            'context': {},
        }

    def action_done(self):
        """
        @public - confirm and import the lines as sale order
        """
        selected_lines = self.line_ids.filtered(lambda m: m.select)
        not_imported_lines = '\n'.join([str([y.product_id.default_code, f'{y.quantity}', f'{y.currency_id.symbol}', f'{y.price}']) + ' - Reason: User deselected' for y in (self.line_ids - selected_lines)])
        so = self.env['sale.order'].create({
            'partner_id': self.env.ref('elbest_import_sales_summary.partner_summary_import').id,
            'partner_invoice_id': self.env.ref('elbest_import_sales_summary.partner_summary_import').id,
            'state': 'draft',
            'order_line': [
                (0, 0, {
                    'name': x.product_id.name,
                    'product_id': x.product_id.id,
                    'product_uom_qty': x.quantity,
                    'price_unit': (x.price / x.quantity) if x.quantity > 0 else 0
                }) for x in self.line_ids]
        })
        self.confirm_sale_related_records(sale_id=so)
        if self._context.get('active_model', False) != 'sale.summary.import.logs':
            # create import log
            log_id = self.env['sale.summary.import.logs'].create({
                'file_name': self.reconciliation_number,
                'sale_ids': [(4, so.id)],
                'not_imported_lines': self.not_imported_lines + f'\n{not_imported_lines}',
                'reconciliation_date': self.reconciliation_date,
                'station_number': self.station_number,
                'line_ids': [(0, 0, {
                    'product_id': x.product_id.id,
                    'quantity': x.quantity,
                    'price': x.price,
                    'sale_order_id': so.id,
                }) for x in self.line_ids]
            })
        else:
            log_id = self.env['sale.summary.import.logs'].browse(self._context.get('active_id', False))
            self.env['sale.summary.import.log.line'].create([{
                'product_id': x.product_id.id,
                'quantity': x.quantity,
                'price': x.price,
                'sale_order_id': so.id,
                'log_id': log_id.id,
            } for x in self.line_ids])
            log_id.update({
                'sale_ids': [(4, x.id) for x in (log_id.sale_ids + so)],
                'not_imported_lines': self.not_imported_lines
            })
        # open import log
        view = self.env.ref('elbest_import_sales_summary.sale_summary_import_logs_view_form')
        return {
            'name': _('Sales Summary Import Logs'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'sale.summary.import.logs',
            'views': [(view.id, 'form')],
            'view_id': view.id,
            'res_id': log_id.id,
            'target': 'current',
            'context': {},
        }

    def confirm_sale_related_records(self, sale_id):
        """
        @public - confirm and validate sale order related pickings, invoices and create payments
        """
        # Confirm the SO
        try:
            sale_id.action_confirm()
            for picking in sale_id.picking_ids:
                picking.action_assign()
                picking.action_set_quantities_to_reservation()
                picking.action_confirm()
                for line in picking.move_ids_without_package:
                    line.update({
                        'quantity_done': line.product_uom_qty
                    })
                picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
            sale_id._create_invoices()
            for invoice in sale_id.invoice_ids:
                invoice.action_post()
            self.env['account.payment.register'].with_context(active_model='account.move', active_ids=invoice.ids).create({'payment_date': invoice.date})._create_payments()
        except Exception as e:
            pass


class SaleSummaryImportWizardLine(models.TransientModel):
    _name = 'sale.summary.import.wizard.line'
    _description = 'Sale Summary Import Wizard Line'

    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float('Quantity')
    price = fields.Monetary('Price')
    company_id = fields.Many2one(comodel_name='res.company', required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related="company_id.currency_id", required=True, string='Currency')
    wizard_id = fields.Many2one('sale.summary.import.wizard', string='Wizard')
    select = fields.Boolean('Import', default=True)
