# -*- coding: utf-8 -*-
import json
import logging
import re
import requests
import datetime # <-- Make sure this import is present

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

def _to_e164(raw):
    # ... (This function remains unchanged) ...
    if not raw:
        return ''
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return ''
    if raw.strip().startswith('+'):
        return raw.strip()
    return '+' + digits

class WhatsappReplyWizard(models.TransientModel):
    _name = 'whatsapp.reply.wizard'
    _description = 'Reply via WhatsApp (24h free-form)'

    # --- Fields for the wizard ---
    lead_id = fields.Many2one('crm.lead', string="Lead", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    to_number = fields.Char(string="To", readonly=True)
    window_ok = fields.Boolean(string="Within 24h window?", readonly=True)
    message = fields.Text(string="Message")

    @api.model
    def default_get(self, fields_list):
        """
        This function runs when the wizard opens. It gets the lead's data
        from the context and pre-fills the fields.
        """
        vals = super().default_get(fields_list)
        lead_id_from_context = self.env.context.get('default_lead_id') or self.env.context.get('active_id')
        
        if lead_id_from_context:
            lead = self.env['crm.lead'].browse(lead_id_from_context)
            vals['lead_id'] = lead.id
            vals['partner_id'] = lead.partner_id.id
            vals['to_number'] = lead.mobile or lead.phone or ''
            
            # Re-calculate window status based on the lead
            vals['window_ok'] = lead.reply_window_open

        return vals

    def action_send(self):
        # ... (Your action_send logic remains mostly the same, just minor improvements) ...
        self.ensure_one()
        if not self.window_ok:
            raise UserError(_("The 24-hour service window is closed. You cannot send a free-form reply."))

        to = _to_e164(self.to_number)
        if not to.startswith('+'):
            raise UserError(_("Destination number must be E.164 (e.g. +201234567890)."))

        ICP = self.env['ir.config_parameter'].sudo()
        access_token = ICP.get_param('whatsapp.access_token') or ''
        phone_number_id = ICP.get_param('whatsapp.phone_number_id') or ''
        api_version = ICP.get_param('whatsapp.api_version') or 'v21.0'

        if not access_token or not phone_number_id:
            raise UserError(_("WhatsApp access token / phone number ID are not configured."))

        url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp", "to": to, "type": "text",
            "text": {"preview_url": False, "body": self.message.strip(),},
        }
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json",}
        _logger.info("Sending free-form WhatsApp to %s: %s", to, self.message[:120])
        
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
            resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            
            # Log success to chatter
            self.lead_id.message_post(
                body=_("✅ Sent via WhatsApp to <b>%s</b>:<br/>%s") % (to, self.message.replace('\n', '<br/>')),
                message_type='comment', subtype_xmlid='mail.mt_note',
            )
        except requests.exceptions.RequestException as e:
            _logger.error("WhatsApp send error: %s", e.response.text if e.response else e)
            raise UserError(_("Send failed: %s") % (e.response.text if e.response else e))

        return {'type': 'ir.actions.act_window_close'}
