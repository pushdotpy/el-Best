# -*- coding: utf-8 -*-

import io
import json
import requests
import zipfile
import logging

from werkzeug import urls

from datetime import timedelta

from odoo.http import request
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# GOOGLE_AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/auth'
GOOGLE_AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_ENDPOINT = 'https://accounts.google.com/o/oauth2/token'
GOOGLE_API_BASE_URL = 'https://www.googleapis.com'


class GoogleDriveConfiguration(models.Model):
    _name = 'google.drive.configuration'
    _description = 'Google Drive Configuration'

    name = fields.Char(string='Name', required=True)
    gdrive_client_id = fields.Char(string='Google Drive Client ID', copy=False)
    gdrive_client_secret = fields.Char(string='Google Drive Client Secret', copy=False)
    gdrive_token_validity = fields.Datetime(string='Google Drive Token Validity', copy=False)
    gdrive_redirect_uri = fields.Char(string='Google Drive Redirect URI', compute='_compute_redirect_uri')
    gdrive_refresh_token = fields.Char(string='Google drive Refresh Token', copy=False)
    gdrive_access_token = fields.Char(string='Google Drive Access Token', copy=False)
    is_google_drive_token_generated = fields.Boolean(string='Google drive Token Generated',  compute='_compute_is_google_drive_token_generated', copy=False)
    google_drive_folder_id = fields.Char(string='Drive Folder ID For Check Files')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean('Active')

    @api.constrains('active')
    def _check_active_status(self):
        """
        @private - check another activated config found for Google Drive
        """
        if self.active and bool(self.search([('id', '!=', self.id), ('active', '=', True), ('company_id', '=', self.env.company.id)])):
            raise ValidationError(_(f'Another activated configuration found for company {self.env.company.name}. '
                                    f'Please disable for activate current configuration.'))

    def _compute_redirect_uri(self):
        """
        @private - compute url for redirection of the Google Drive authentication
        """
        for rec in self:
            base_url = request.env['ir.config_parameter'].get_param('web.base.url')
            rec.gdrive_redirect_uri = base_url + '/google_drive/authentication'

    @api.depends('gdrive_access_token', 'gdrive_refresh_token')
    def _compute_is_google_drive_token_generated(self):
        """
        @private - Set True if the Google Drive refresh token is generated
        """
        for rec in self:
            rec.is_google_drive_token_generated = bool(rec.gdrive_access_token) and bool(rec.gdrive_refresh_token)

    def action_get_gdrive_auth_code(self):
        """
        Generate ogoogle drive authorization code
        """
        action = self.env["ir.actions.act_window"].sudo()._for_xml_id("elbest_import_sales_summary.action_view_google_drive_configuration")
        base_url = request.env['ir.config_parameter'].get_param('web.base.url')
        url_return = base_url + '/web#id=%d&action=%d&view_type=form&model=%s' % (self.id, action['id'], 'google.drive.configuration')
        state = {
            'backup_config_id': self.id,
            'url_return': url_return
        }
        encoded_params = urls.url_encode({
            'response_type': 'code',
            'client_id': self.gdrive_client_id,
            'scope': 'https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/drive.file',
            'redirect_uri': base_url + '/google_drive/authentication',
            'access_type': 'offline',
            'state': json.dumps(state),
            'approval_prompt': 'force',
        })
        auth_url = "%s?%s" % (GOOGLE_AUTH_ENDPOINT, encoded_params)
        return {
            'type': 'ir.actions.act_url',
            'target': 'self',
            'url': auth_url,
        }

    def generate_gdrive_refresh_token(self):
        """
        generate google drive access token from refresh token if expired
        """
        headers = {"content-type": "application/x-www-form-urlencoded"}
        data = {
            'refresh_token': self.gdrive_refresh_token,
            'client_id': self.gdrive_client_id,
            'client_secret': self.gdrive_client_secret,
            'grant_type': 'refresh_token',
        }
        try:
            res = requests.post(GOOGLE_TOKEN_ENDPOINT, data=data, headers=headers)
            res.raise_for_status()
            response = res.content and res.json() or {}
            if response:
                expires_in = response.get('expires_in')
                self.write({
                    'gdrive_access_token': response.get('access_token'),
                    'gdrive_token_validity': fields.Datetime.now() + timedelta(seconds=expires_in) if expires_in else False,
                })
        except requests.HTTPError as error:
            error_key = error.response.json().get("error", "nc")
            error_msg = _(
                "An error occurred while generating the token. Your authorization code may be invalid or has already expired [%s]. "
                "You should check your Client ID and secret on the Google APIs plateform or try to stop and restart your calendar synchronisation.",
                error_key)
            raise UserError(error_msg)

    def get_gdrive_tokens(self, authorize_code):
        """
        Generate onedrive tokens from authorization code
        """
        base_url = request.env['ir.config_parameter'].get_param('web.base.url')
        headers = {"content-type": "application/x-www-form-urlencoded"}
        data = {
            'code': authorize_code,
            'client_id': self.gdrive_client_id,
            'client_secret': self.gdrive_client_secret,
            'grant_type': 'authorization_code',
            'redirect_uri': base_url + '/google_drive/authentication'
        }
        try:
            res = requests.post(GOOGLE_TOKEN_ENDPOINT, params=data, headers=headers)
            res.raise_for_status()
            response = res.content and res.json() or {}
            if response:
                expires_in = response.get('expires_in')
                self.write({
                    'gdrive_access_token': response.get('access_token'),
                    'gdrive_refresh_token': response.get('refresh_token'),
                    'gdrive_token_validity': fields.Datetime.now() + timedelta(seconds=expires_in) if expires_in else False,
                })
        except requests.HTTPError:
            error_msg = _("Something went wrong during your token generation. Maybe your Authorization Code is invalid")
            raise UserError(error_msg)

    def fetch_sale_summary_data(self):
        """
        @public - check and get sale summary files from the Google Drive folder
        """
        try:
            # Check token validity and create a new refresh token
            if self.gdrive_token_validity <= fields.Datetime.now():
                self.generate_gdrive_refresh_token()
            headers = {"Authorization": "Bearer %s" % self.gdrive_access_token}
            # Get folders
            query = f"'{self.google_drive_folder_id}' in parents"
            folders = requests.get("https://www.googleapis.com/drive/v3/files?q=%s" % query, headers=headers)
            _logger.info('Received folders from Google Drive API')
            folders = folders.json()['files']
            # Check for imported files
            imported_zip_files = ['_'.join(eval(x['zip_file_name'])) for x in self.env['sale.summary.import.logs'].sudo().search_read([('zip_file_name', '!=', False)], ['zip_file_name']) if (False not in eval(x['zip_file_name']))]
            for folder in folders:
                # get summary text zipfile
                folder_id = folder['id']
                folder_query = f"'{folder_id}' in parents"
                files = requests.get("https://www.googleapis.com/drive/v3/files?q=%s" % folder_query, headers=headers)
                _logger.info(f'Received data from drive folder {folder_id}')
                files = [x for x in files.json()['files'] if x['mimeType'] == 'application/x-zip-compressed' and '{folder_name}_{zip_name}'.format(folder_name=folder['name'], zip_name=x['name']) not in imported_zip_files]
                for file in files:
                    try:
                        # Get read and add file data to the system
                        file_content = requests.get(f"https://www.googleapis.com/drive/v3/files/{file['id']}?alt=media", headers=headers)
                        _logger.info(f'Received text file from drive file {folder_id}')
                        zf = zipfile.ZipFile(io.BytesIO(file_content.content), "r")
                        infolist = [x for x in zf.infolist() if x.filename.endswith('dailysummaryreport.txt')]
                        for fileinfo in infolist:
                            try:
                                _logger.info(f'Begin writing data to the system for file {fileinfo.filename}')
                                summary_file_data = zf.read(fileinfo).decode('iso-8859-1').split('\n')
                                start_line = [x for x in summary_file_data if 'VENTES D\'ARTICLE A 7 CHARACTERS' in x]
                                end_line = [x for x in summary_file_data if 'STATISTIQUES DE QUART' in x]
                                if start_line and end_line:
                                    start_line_index = summary_file_data.index(start_line[0])
                                    end_line_index = summary_file_data.index(end_line[0])
                                    summary_data = summary_file_data[start_line_index + 3:end_line_index - 2]
                                    summary_data = [[x for x in y.strip('\r').split(' ') if x != ''] for y in summary_data]
                                    self.env['sale.summary.import.wizard'].sudo().create({
                                        'file_name': fileinfo.filename
                                    }).with_context(scheduled_action_summary_data=summary_data, reconciliation_date=summary_file_data[11]).action_import()
                                _logger.info(f'End writing data to the system for file {fileinfo.filename}')
                            except Exception as e:
                                _logger.info(f'{fileinfo.filename} cannot be imported due to error: {e}')
                                continue
                    except Exception as e:
                        file_id = file['id']
                        _logger.info(f'Following error with file {file_id} - {e}')
                        continue
        except Exception as e:
            _logger.info(f'Cannot process schedule action - {e}')
