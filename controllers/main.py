# Author: Noureldin ElDehy

import base64
import datetime
import json
import logging
import mimetypes
import re
import requests

from odoo import http
from odoo.http import request
from werkzeug.wrappers import Response

_logger = logging.getLogger(__name__)


# -----------------------
# Helpers
# -----------------------
def _safe_ext(mimetype_str):
    if not mimetype_str:
        return ""
    base = mimetype_str.split(";")[0].strip()
    ext = mimetypes.guess_extension(base) or ""
    if base.startswith("image/jpeg") and ext in ("", ".jpe"):
        return ".jpg"
    if base == "audio/ogg" and ext == ".oga":
        return ".ogg"
    return ext


def _wh_get_media_meta_and_bytes(media_id):
    ICP = request.env['ir.config_parameter'].sudo()
    token = ICP.get_param('whatsapp.access_token') or ''
    api_version = ICP.get_param('whatsapp.api_version') or 'v19.0'
    if not token:
        raise Exception("Missing whatsapp.access_token in Odoo System Parameters")

    meta_url = f"https://graph.facebook.com/{api_version}/{media_id}"
    headers = {"Authorization": f"Bearer {token}"}

    r1 = requests.get(meta_url, headers=headers, timeout=20)
    r1.raise_for_status()
    meta = r1.json() or {}

    file_url = meta.get("url")
    mime = meta.get("mime_type")
    if not file_url:
        raise Exception(f"Media {media_id} has no URL in response: {meta}")

    r2 = requests.get(file_url, headers=headers, timeout=120, allow_redirects=True)
    r2.raise_for_status()
    return mime, r2.content


# -----------------------
# Controller
# -----------------------
class WhatsAppController(http.Controller):

    @http.route('/whatsapp/webhook', type='http', auth='public', methods=['GET'], csrf=False)
    def whatsapp_verify(self, **kwargs):
        # ... (This function remains unchanged) ...
        try:
            mode = kwargs.get('hub.mode')
            token = kwargs.get('hub.verify_token')
            challenge = kwargs.get('hub.challenge')
            verify_token = request.env['ir.config_parameter'].sudo().get_param('whatsapp.verify_token') or ''
            if mode == 'subscribe' and token == verify_token and challenge:
                return Response(str(challenge), mimetype='text/plain', status=200)
            return Response('Verification failed', mimetype='text/plain', status=403)
        except Exception as e:
            _logger.exception("Verification error: %s", e)
            return Response('OK', mimetype='text/plain', status=200)

    @http.route('/whatsapp/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def whatsapp_webhook(self, **kwargs):
        try:
            raw = request.httprequest.data or b'{}'
            data = json.loads(raw.decode('utf-8'))
        except Exception:
            _logger.exception("Invalid JSON payload")
            return True

        _logger.info("WhatsApp Webhook Received: %s", json.dumps(data, indent=2))

        try:
            entry = (data.get('entry') or [{}])[0]
            change = (entry.get('changes') or [{}])[0]
            value = change.get('value') or {}
            messages = value.get('messages') or []
            if not messages:
                return True

            msg = messages[0]
            from_number = msg.get('from') or ''
            normalized = re.sub(r'\D', '', from_number)
            if not normalized:
                _logger.warning("Cannot normalize phone from %s", from_number)
                return True
            
            phone_e164 = '+' + normalized if not from_number.startswith('+') else from_number

            Lead = request.env['crm.lead'].sudo()
            search_fragment = normalized[-9:]
            lead = Lead.search([
                '|', ('phone', 'like', search_fragment), ('mobile', 'like', search_fragment)
            ], limit=1)

            Bus = request.env['bus.bus'].sudo()
            dbname = request.env.cr.dbname

            if lead:
                lead.last_whatsapp_reply_date = datetime.datetime.now()
                try:
                    channel = (dbname, 'res.partner', lead.user_id.partner_id.id if lead.user_id else request.env.user.partner_id.id)
                    payload = {'lead_id': lead.id}
                    notification = {'type': 'lead_reload', 'payload': payload}
                    Bus._sendone(channel, notification)
                    _logger.info(f"Sent reload signal to channel: {channel}")
                except Exception as e:
                    _logger.exception(f"Failed to send reload signal: {e}")
            
            if not lead:
                _logger.info("No matching Lead; creating a new one for %s", phone_e164)
                lead = Lead.create({
                    'name': f"WhatsApp from {phone_e164}", 'contact_name': phone_e164, 'phone': phone_e164,
                })
                lead.last_whatsapp_reply_date = datetime.datetime.now()
            
            message_type = (msg.get('type') or '').lower()
            body_text = ''
            attachment_ids = []

            # --- ATTACHMENT HANDLING LOGIC ---
            if message_type in ('image', 'audio', 'video', 'document', 'sticker'):
                container = msg.get(message_type) or {}
                media_id = container.get('id')
                caption = container.get('caption') or ''
                suggested_name = container.get('filename')
                mime_hint = container.get('mime_type')

                if not media_id:
                    _logger.info("Media message without id, skipping.")
                    return True
                
                try:
                    mime, content = _wh_get_media_meta_and_bytes(media_id)
                    if not mime and mime_hint:
                        mime = mime_hint
                    ext = _safe_ext(mime)
                    filename = suggested_name or (f"whatsapp_{media_id}{ext or ''}")

                    att = request.env['ir.attachment'].sudo().create({
                        'name': filename,
                        'res_model': 'crm.lead',
                        'res_id': lead.id,
                        'datas': base64.b64encode(content),
                        'mimetype': mime or 'application/octet-stream',
                    })
                    attachment_ids.append(att.id)

                    # --- THIS IS THE FIX ---
                    # Manually create a clickable download link for the chatter body
                    download_url = f"/web/content/{att.id}?download=true"
                    linked_name = f'<a href="{download_url}" target="_blank">{att.name}</a>'
                    body_text = f"Received {message_type} from WhatsApp. {linked_name}"
                    if caption:
                        body_text = f"{caption}<br/>{body_text}"
                    # --- END FIX ---
                
                except Exception as e:
                    _logger.exception("Failed to download media %s: %s", media_id, e)
                    body_text = f"Received {message_type} but failed to download."

            else: # Fallback to text
                body_text = (msg.get('text') or {}).get('body') or (msg.get('button') or {}).get('text') or ''
                if not body_text:
                    _logger.info("Skipping empty message.")
                    return True

            if not lead.partner_id:
                 partner_match = request.env['res.partner'].sudo().search([
                    '|', ('phone', 'like', search_fragment), ('mobile', 'like', search_fragment)
                 ], limit=1)
                 if partner_match:
                     lead.partner_id = partner_match.id

            author_id = lead.partner_id.id if lead.partner_id else (request.env.ref('base.public_partner').id)
            
            follower_partners = set(lead.message_follower_ids.mapped('partner_id').ids)
            if lead.user_id and lead.user_id.partner_id:
                follower_partners.add(lead.user_id.partner_id.id)
            
            message_body = f"WhatsApp Reply from {lead.partner_name or phone_e164}:<br/>{body_text}"

            new_msg = lead.with_context(mail_notify_noemail=True).message_post(
                author_id=author_id,
                body=message_body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                attachment_ids=attachment_ids,
                partner_ids=list(follower_partners)
            )

            try:
                formatted_payload = new_msg.message_format()[0]
                for pid in follower_partners:
                    channel = (dbname, 'res.partner', pid)
                    notification = {'type': 'mail.message/new', 'payload': formatted_payload}
                    Bus._sendone(channel, notification)
                _logger.info("Bus notifications sent to partners: %s", list(follower_partners))
            except Exception as e:
                _logger.exception("Failed explicit bus push (chatter): %s", e)
            
            return True

        except Exception as e:
            _logger.exception("Error processing WhatsApp webhook: %s", e)
            return True
