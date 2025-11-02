#Author: Noureldin ElDehy
# whatsapp_meta_integration/wizard/whatsapp_variable_input.py
from odoo import models, fields

class WhatsappVariableInput(models.TransientModel):
    _name = 'whatsapp.variable.input'
    _description = 'WhatsApp Template Variable Input'
    _order = 'sequence'

    wizard_id = fields.Many2one('send.whatsapp.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(required=True)
    name = fields.Char(string="Variable", readonly=True)
    value = fields.Char(string="Value", required=True)