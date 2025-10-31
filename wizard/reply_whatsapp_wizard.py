# -*- coding: utf-8 -*-
import json
import logging
import re
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

def _to_e164(raw):
    if not raw:
        return ''
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return ''
    # if already starts with + leave it, else prefix +
    if raw.strip().startswith('+'):
        return raw.strip()
    return '+' + digits

class WhatsappReplyWizard(models.TransientModel):
    _name = 'whatsapp.reply.wizard'
    _description = 'Reply via WhatsApp (24h free-form)'

    lead_id = fields.Many2one('crm.lead', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', related='lead_id.partner_id', readonly=True)
    to_number = fields.Char(string="To", required=True, help="Destination WhatsApp number in E.164")
    message = fields.Text(string="Message", required=True)

    # Show a small helper
    window_ok = fields.Boolean(string="Within 24h window?", compute="_compute_window_ok")

    @api.depends('lead_id.last_whatsapp_reply_date')
    def _compute_window_ok(self):
        for w in self:
            w.window_ok = bool(w.lead_id and w.lead_id.reply_window_open)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        lead = self.env['crm.lead'].browse(self._context.get('default_lead_id') or 0)
        if lead:
            # prefer mobile then phone then partner mobile/phone
            to = lead.mobile or lead.phone or (lead.partner_id and (lead.partner_id.mobile or lead.partner_id.phone)) or ''
            vals.setdefault('to_number', to)
        return vals

    def action_send(self):
        self.ensure_one()

        # Enforce 24h window
        if not self.lead_id.reply_window_open:
            raise UserError(_("The 24-hour service window is closed. Use a template instead."))

        # Validate destination number
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
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": self.message.strip(),
            },
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        _logger.info("Sending free-form WhatsApp to %s: %s", to, self.message[:120])
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)

        if not resp.ok:
            _logger.error("WhatsApp send error: %s", resp.text)
            raise UserError(_("Send failed: %s") % resp.text)

        # Log to chatter
        self.lead_id.message_post(
            body=_("Sent WhatsApp message to <b>%s</b>:<br/>%s") % (to, self.message.replace('\n', '<br/>')),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return {'type': 'ir.actions.act_window_close'}
