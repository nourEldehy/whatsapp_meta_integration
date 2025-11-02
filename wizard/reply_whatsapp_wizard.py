# -*- coding: utf-8 -*-
import base64
import json
import logging
import mimetypes
import re
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Safe HTML escape (v13-friendly import)
try:
    from odoo.tools.misc import html_escape
except Exception:  # fallback if location differs
    from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


def _to_e164(raw):
    """Normalize any phone input to a +E.164-ish string (minimal sanity)."""
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

    # Pre-filled context
    lead_id = fields.Many2one('crm.lead', string="Lead", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    to_number = fields.Char(string="To (E.164)")
    window_ok = fields.Boolean(string="Within 24h window?", readonly=True)

    # Message + attachments
    message = fields.Text(string="Message")
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'wa_reply_ir_attachment_rel',
        'wiz_id', 'att_id',
        string='Attachments',
        help='Add one or more files to send via WhatsApp.'
    )

    # ---------- defaults ----------
    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        lead_id_from_context = self.env.context.get('default_lead_id') or self.env.context.get('active_id')
        if lead_id_from_context:
            lead = self.env['crm.lead'].browse(lead_id_from_context)
            vals['lead_id'] = lead.id
            vals['partner_id'] = lead.partner_id.id
            vals['to_number'] = vals.get('to_number') or lead.mobile or lead.phone or ''
            vals['window_ok'] = getattr(lead, 'reply_window_open', False)
        return vals

    # ---------- config ----------
    def _wa_get_credentials(self):
        ICP = self.env['ir.config_parameter'].sudo()
        access_token = ICP.get_param('whatsapp.access_token') or ''
        phone_number_id = ICP.get_param('whatsapp.phone_number_id') or ''
        api_version = ICP.get_param('whatsapp.api_version') or 'v21.0'
        if not access_token or not phone_number_id:
            raise UserError(_("WhatsApp access token / phone number ID are not configured."))
        return api_version, access_token, phone_number_id

    # ---------- helpers: upload + send ----------
    def _wa_upload_media(self, token, phone_number_id, attachment, api_version='v21.0'):
        """Upload an ir.attachment to WA; return (media_id, mimetype, filename)."""
        filename = attachment.name or 'file'
        mimetype = attachment.mimetype or (mimetypes.guess_type(filename)[0] or 'application/octet-stream')
        raw = base64.b64decode(attachment.datas or b'')

        max_bytes = 100 * 1024 * 1024
        if len(raw) > max_bytes:
            raise UserError(_("File %s is too large to send (>%s MB).") % (filename, 100))

        url = 'https://graph.facebook.com/{ver}/{pnid}/media'.format(ver=api_version, pnid=phone_number_id)
        headers = {'Authorization': 'Bearer %s' % token}
        files = {'file': (filename, raw, mimetype)}
        data = {'messaging_product': 'whatsapp'}

        r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        # Expect JSON always
        try:
            result = r.json()
        except Exception:
            _logger.exception("WhatsApp upload error (non-JSON)")
            raise UserError(_("Failed to upload media to WhatsApp (non-JSON response)."))

        if r.status_code >= 400 or 'id' not in result:
            _logger.error("WhatsApp upload failed: %s", result)
            raise UserError(_("Failed to upload media to WhatsApp:\n%s") % result)
        return result['id'], mimetype, filename

    @staticmethod
    def _wa_type_from_mimetype(mimetype):
        if mimetype.startswith('image/'):
            return 'image'
        if mimetype.startswith('video/'):
            return 'video'
        if mimetype.startswith('audio/'):
            return 'audio'
        return 'document'

    def _wa_send_text(self, token, phone_number_id, api_version, to_e164, body):
        url = 'https://graph.facebook.com/{ver}/{pnid}/messages'.format(ver=api_version, pnid=phone_number_id)
        headers = {'Authorization': 'Bearer %s' % token, 'Content-Type': 'application/json'}
        payload = {
            "messaging_product": "whatsapp",
            "to": to_e164,
            "type": "text",
            "text": {"preview_url": False, "body": body or ""}
        }
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code >= 400:
            _logger.error("WhatsApp text send failed: %s", r.text)
            raise UserError(_("Failed to send text message:\n%s") % r.text)

    def _wa_send_media(self, token, phone_number_id, api_version, to_e164, media_id, wa_type, caption=None, filename=None):
        url = 'https://graph.facebook.com/{ver}/{pnid}/messages'.format(ver=api_version, pnid=phone_number_id)
        headers = {'Authorization': 'Bearer %s' % token, 'Content-Type': 'application/json'}
        block = {"id": media_id}
        if caption:
            block["caption"] = caption
        if wa_type == 'document' and filename:
            block["filename"] = filename
        payload = {
            "messaging_product": "whatsapp",
            "to": to_e164,
            "type": wa_type,
            wa_type: block
        }
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code >= 400:
            _logger.error("WhatsApp media send failed: %s", r.text)
            raise UserError(_("Failed to send media message:\n%s") % r.text)

    # ---------- main action ----------
    def action_send(self):
        self.ensure_one()

        if not self.window_ok:
            raise UserError(_("The 24-hour service window is closed. You cannot send a free-form reply."))

        to = _to_e164(self.to_number)
        if not to or not to.startswith('+'):
            raise UserError(_("Destination number must be E.164 (e.g. +201234567890)."))

        api_version, access_token, phone_number_id = self._wa_get_credentials()

        # 1) Text (if provided)
        msg = (self.message or '').strip()
        if msg:
            self._wa_send_text(access_token, phone_number_id, api_version, to, msg)

        # 2) Media (each attachment)
        sent_any_media = False
        for att in self.attachment_ids:
            media_id, mimetype, filename = self._wa_upload_media(access_token, phone_number_id, att, api_version=api_version)
            wa_type = self._wa_type_from_mimetype(mimetype)
            # (Optional) use caption=msg for the first media:
            # caption_to_use = msg if not sent_any_media and msg else None
            caption_to_use = None
            self._wa_send_media(
                access_token, phone_number_id, api_version,
                to, media_id, wa_type, caption=caption_to_use, filename=filename
            )
            sent_any_media = True

        # ---------- Log full details to chatter (actual text + attachment names) ----------
        parts = [ _("✅ Sent via WhatsApp to <b>%s</b>") % to ]

        if msg:
            safe = html_escape(msg).replace('\n', '<br/>')
            parts.append("<div style='margin-top:6px'><i>Message:</i><br/>%s</div>" % safe)

        if self.attachment_ids:
            names = ", ".join(html_escape(a.name or "file") for a in self.attachment_ids)
            parts.append("<div><i>Attachments:</i> %s</div>" % names)

        self.lead_id.message_post(
            body="<br/>".join(parts),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

        return {'type': 'ir.actions.act_window_close'}

