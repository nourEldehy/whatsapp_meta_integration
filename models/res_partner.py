# whatsapp_meta_integration/models/res_partner.py
import json
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def send_whatsapp_test_template(self):
        """Sends a hardcoded test template to the partner."""
        self.ensure_one()
        
        if not self.mobile:
            raise UserError(_("Partner does not have a mobile number."))

        ICP = self.env['ir.config_parameter'].sudo()
        access_token = ICP.get_param('whatsapp_meta.access_token')
        phone_number_id = ICP.get_param('whatsapp_meta.phone_number_id')

        if not access_token or not phone_number_id:
            raise UserError(_("WhatsApp API credentials are not configured in settings."))

        url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        
        # IMPORTANT: Replace 'hello_world' with the actual name of your approved template.
        payload = {
            "messaging_product": "whatsapp",
            "to": self.mobile,
            "type": "template",
            "template": {
                "name": "hello_world", # <-- YOUR TEMPLATE NAME HERE
                "language": {
                    "code": "en_US" # <-- YOUR TEMPLATE LANGUAGE HERE
                }
            }
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)
            
            _logger.info("WhatsApp message sent successfully to %s. Response: %s", self.mobile, response.text)

            # Log the outbound message in the chatter
            self.message_post(
                body=f"Sent WhatsApp Template: hello_world",
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

        except requests.exceptions.RequestException as e:
            _logger.error("Failed to send WhatsApp message: %s", e)
            raise UserError(_("Failed to send message. Check the logs for details."))