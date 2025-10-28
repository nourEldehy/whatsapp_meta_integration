#Author: Noureldin ElDehy
# whatsapp_meta_integration/models/res_partner.py
from odoo import models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    # The button now opens a wizard, so the Python function is no longer needed here.
    # You can add other partner-related WhatsApp logic here in the future.