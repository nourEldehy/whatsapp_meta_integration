# whatsapp_meta_integration/models/whatsapp_template.py
from odoo import models, fields

class WhatsappTemplate(models.Model):
    _name = 'whatsapp.template'
    _description = 'WhatsApp Message Template'
    _order = 'name'

    name = fields.Char(
        string='Template Name',
        required=True,
        help="The exact name of the template from your Meta dashboard."
    )
    body_text = fields.Text(
        string='Body Text',
        help="The full body of the template, use {{1}}, {{2}} for variables. For user reference only."
    )
    language_code = fields.Char(
        string='Language',
        default='en_US',
        required=True,
        help="Language code, e.g., 'en_US', 'ar', 'es'."
    )
    variable_count = fields.Integer(
        string="Variable Count",
        readonly=True,
        help="The number of variables detected in the body text."
    )