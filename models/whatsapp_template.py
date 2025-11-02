#Author: Noureldin ElDehy
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
        string="Body Variable Count", 
        readonly=True, 
        help="The number of variables detected in the body text."
    )
    variable_descriptions = fields.Char(
        string="Body Variable Descriptions", 
        help="Comma-separated descriptions for each body variable. Example: Customer Name, Order Number"
    )
    
    # --- Fields for Header ---
    has_header_variable = fields.Boolean(
        string="Has Header Variable", 
        readonly=True
    )
    header_variable_description = fields.Char(
        string="Header Variable Description", 
        help="Description for the header variable (e.g., Customer Name, Document URL)."
    )
    header_type = fields.Char(
        string="Header Type", 
        readonly=True, 
        help="DOCUMENT, IMAGE, VIDEO, or TEXT"
    )