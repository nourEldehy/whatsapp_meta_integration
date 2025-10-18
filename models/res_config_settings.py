# whatsapp_meta_integration/models/res_config_settings.py
from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    whatsapp_meta_access_token = fields.Char(
        string='Meta Access Token',
        config_parameter='whatsapp_meta.access_token'
    )
    whatsapp_meta_phone_number_id = fields.Char(
        string='Phone Number ID',
        config_parameter='whatsapp_meta.phone_number_id'
    )
    whatsapp_meta_verify_token = fields.Char(
        string='Webhook Verify Token',
        help="A custom secret string for webhook verification.",
        config_parameter='whatsapp_meta.verify_token'
    )