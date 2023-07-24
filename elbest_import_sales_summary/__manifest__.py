# -*- coding: utf-8 -*-

{
    "name": "Elbest - Import sales summary",
    "author": "Bassam Infotech LLP",
    "website": "https://bassaminfotech.com",
    "support": "sales@bassaminfotech.com",
    "category": "Sales",
    "summary": "Import sale summary data to odoo",
    "description": """
Import sale summary data to odoo
""",
    "version": "16.0.1.0.0",
    "depends": [
        'base',
        'sale',
        'sale_management',
    ],
    "data": [
        'data/data.xml',
        'security/ir.model.access.csv',
        'views/sale_summary_import_logs_views.xml',
        'wizards/sale_summary_import_wizard_views.xml',
    ],
    "application": False,
    "auto_install": False,
    "installable": True,
    "license": 'LGPL-3'
}
