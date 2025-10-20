# whatsapp_meta_integration/wizard/send_whatsapp_wizard.py
import json
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SendWhatsappWizard(models.TransientModel):
    _name = 'send.whatsapp.wizard'
    _description = 'Send WhatsApp Message Wizard'

    partner_id = fields.Many2one(
        'res.partner',
        string="Recipient",
        default=lambda self: self.env.context.get('default_partner_id'),
        readonly=True
    )
    template_id = fields.Many2one('whatsapp.template', string="Template", required=True)
    variable_ids = fields.One2many('whatsapp.variable.input', 'wizard_id', string="Variables")
    
    @api.onchange('template_id')
    def _onchange_template_id(self):
        # Clear existing variables
        self.variable_ids = [(5, 0, 0)]
        if self.template_id and self.template_id.variable_count > 0:
            variable_lines = []
            for i in range(1, self.template_id.variable_count + 1):
                variable_lines.append((0, 0, {
                    'sequence': i,
                    'name': f"Variable {{{{i}}}}",
                }))
            self.variable_ids = variable_lines

    def action_send_message(self):
        self.ensure_one()
        if not self.partner_id.mobile:
            raise UserError(_("Recipient does not have a mobile number."))
        
        # Check if all variable fields are filled
        if len(self.variable_ids) != self.template_id.variable_count:
             raise UserError(_("The number of variables does not match the template. Please re-select the template."))
        if any(not var.value for var in self.variable_ids):
            raise UserError(_("Please fill in all variable values before sending."))

        ICP = self.env['ir.config_parameter'].sudo()
        access_token = ICP.get_param('whatsapp_meta.access_token')
        phone_number_id = ICP.get_param('whatsapp_meta.phone_number_id')
        url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
        headers = { "Authorization": f"Bearer {access_token}", "Content-Type": "application/json" }

        parameters = [{"type": "text", "text": var.value} for var in self.variable_ids]
        components = [{"type": "body", "parameters": parameters}] if parameters else []
        
        payload = {
            "messaging_product": "whatsapp",
            "to": self.partner_id.mobile,
            "type": "template",
            "template": {
                "name": self.template_id.name,
                "language": {"code": self.template_id.language_code},
                "components": components
            }
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            response.raise_for_status()
            
            _logger.info("WhatsApp message sent successfully. Response: %s", response.text)
            self.partner_id.message_post(
                body=f"Sent WhatsApp Template: {self.template_id.name}",
                message_type='comment', subtype_xmlid='mail.mt_comment'
            )
        except requests.exceptions.RequestException as e:
            error_message = e.response.text if e.response else str(e)
            _logger.error("Failed to send WhatsApp message: %s", error_message)
            raise UserError(_(f"Failed to send message: {error_message}"))
        
        return {'type': 'ir.actions.act_window_close'}