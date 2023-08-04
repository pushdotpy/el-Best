# -*- coding: utf-8 -*-

import json

from odoo import http
from odoo.http import request


class GoogleDriveAuth(http.Controller):

    @http.route('/google_drive/authentication', type='http', auth="public")
    def gdrive_oauth2callback(self, **kw):
        state = json.loads(kw['state'])
        backup_config = request.env['google.drive.configuration'].sudo().browse(state.get('backup_config_id'))
        backup_config.get_gdrive_tokens(kw.get('code'))
        url_return = state.get('url_return')
        return request.redirect(url_return)
