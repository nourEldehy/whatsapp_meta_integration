#Author: Noureldin ElDehy
# whatsapp_meta_integration/wizard/send_whatsapp_wizard.py
import json
import logging
import requests
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SendWhatsappWizard(models.TransientModel):
    _name = 'send.whatsapp.wizard'
    _description = 'Send WhatsApp Message Wizard'

    partner_id = fields.Many2one(
        'res.partner', 
        string="Recipient", 
        readonly=True, 
        default=lambda self: self.env.context.get('default_partner_id')
    )
    template_id = fields.Many2one('whatsapp.template', string="Template", required=True)
    
    # Fields for Header
    has_header_variable = fields.Boolean(related='template_id.has_header_variable')
    header_variable_value = fields.Char(string="Header Variable")
    header_variable_description = fields.Char(related='template_id.header_variable_description', readonly=True)
    header_type = fields.Char(related='template_id.header_type')

    # Field for Body
    variable_ids = fields.One2many('whatsapp.variable.input', 'wizard_id', string="Body Variables")
    
    @api.onchange('template_id')
    def _onchange_template_id(self):
        """
        Dynamically creates and auto-fills variable input fields based on the selected template.
        """
        self.variable_ids = [(5, 0, 0)] # Clear existing variables
        if self.template_id and self.template_id.variable_count > 0:
            
            descriptions = [d.strip() for d in self.template_id.variable_descriptions.split(',')] if self.template_id.variable_descriptions else []
            variable_lines = []
            
            # --- START OF NEW AUTO-FILL LOGIC ---
            # Get the records we need for auto-filling
            current_user = self.env.user
            partner = self.partner_id
            # --- END OF NEW AUTO-FILL LOGIC ---

            for i in range(1, self.template_id.variable_count + 1):
                label = descriptions[i-1] if i <= len(descriptions) else f'Body Variable {{{{i}}}}'
                
                # --- AUTO-FILL VALUE LOGIC ---
                value = ''
                label_lower = label.lower()
                if partner and 'customer' in label_lower and 'name' in label_lower:
                    value = partner.name
                elif current_user and 'agent' in label_lower and 'name' in label_lower:
                    value = current_user.name
                elif current_user and 'agent' in label_lower and ('phone' in label_lower or 'mobile' in label_lower):
                    value = current_user.partner_id.mobile or current_user.partner_id.phone
                # --- END OF AUTO-FILL VALUE LOGIC ---

                variable_lines.append((0, 0, {
                    'sequence': i,
                    'name': label,
                    'value': value, # Set the auto-filled value
                }))
            self.variable_ids = variable_lines

    def action_send_message(self):
        # ... The rest of this function (action_send_message) remains exactly the same ...
        ICP = self.env['ir.config_parameter'].sudo()
        access_token = ICP.get_param('whatsapp_meta.access_token')
        phone_number_id = ICP.get_param('whatsapp_meta.phone_number_id')
        url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"

        components = []
        if self.has_header_variable:
            if not self.header_variable_value:
                raise UserError(_("Please provide a value for the Header Variable."))
            parameters = []
            if self.header_type == 'TEXT':
                parameters.append({"type": "text", "text": self.header_variable_value})
            else:
                parameters.append({"type": self.header_type.lower(), self.header_type.lower(): {"link": self.header_variable_value}})
            components.append({"type": "header", "parameters": parameters})
        
        if self.variable_ids:
            if any(not var.value for var in self.variable_ids):
                raise UserError(_("Please fill in all Body Variable values before sending."))
            
            placeholder_names = re.findall(r'\{\{([a-zA-Z0-9_]+)\}\}', self.template_id.body_text)
            
            body_params = []
            for i, var in enumerate(self.variable_ids):
                param = {"type": "text", "text": var.value}
                if i < len(placeholder_names):
                    param['parameter_name'] = placeholder_names[i]
                body_params.append(param)
            components.append({"type": "body", "parameters": body_params})

        payload = {
            "messaging_product": "whatsapp", "to": self.partner_id.mobile, "type": "template",
            "template": {"name": self.template_id.name, "language": {"code": self.template_id.language_code}, "components": components}
        }
        
        try:
            response = requests.post(url, headers={"Authorization": f"Bearer {access_token}"}, json=payload)
            response.raise_for_status()
            
            log_body = f"Sent WhatsApp Template: {self.template_id.name}"
            active_model = self.env.context.get('active_model')
            active_id = self.env.context.get('active_id')
            if active_model and active_id and hasattr(self.env[active_model], 'message_post'):
                record = self.env[active_model].browse(active_id)
                record.message_post(body=log_body, message_type='comment', subtype_xmlid='mail.mt_comment')
            else:
                self.partner_id.message_post(body=log_body, message_type='comment', subtype_xmlid='mail.mt_comment')

        except requests.exceptions.RequestException as e:
            error_details = e.response.json().get('error', {})
            error_message = error_details.get('message', str(e))
            error_debug = error_details.get('error_data', {}).get('details', '')
            _logger.error("Failed to send WhatsApp message: %s - %s", error_message, error_debug)
            raise UserError(_("Failed to send message: %s\n\nDetails: %s") % (error_message, error_debug))
        
        return {'type': 'ir.actions.act_window_close'}