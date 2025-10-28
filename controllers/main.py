#Author: Noureldin ElDehy

import json
import logging
import re

from odoo import http
from odoo.http import request
from werkzeug.wrappers import Response

_logger = logging.getLogger(__name__)


class WhatsAppController(http.Controller):
    """
    WhatsApp Cloud API webhook controller (Meta).
    - GET: verification (optional)
    - POST: inbound messages -> post to Lead chatter with customer as author
            + live update via bus + force inbox notifications (bell)
    """

    # ---- Optional: Meta verification (GET) ----
    @http.route('/whatsapp/webhook', type='http', auth='public', methods=['GET'], csrf=False)
    def whatsapp_verify(self, **kwargs):
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

    # ---- Inbound messages (POST) ----
    @http.route('/whatsapp/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def whatsapp_webhook(self, **kwargs):
        """
        Handle inbound WhatsApp messages:
        1) Find/Create Lead by phone
        2) Choose author = customer partner (lead.partner_id or matched by phone; fallback public)
        3) Post COMMENT (no email) and notify followers + salesperson
        4) Explicit bus push (live chatter)
        5) Force inbox notifications (top bell)
        """
        # Parse JSON safely
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

            # Accept text or button text
            body = (msg.get('text') or {}).get('body') or (msg.get('button') or {}).get('text') or ''
            if not body:
                _logger.info("Skipping non-text message.")
                return True

            from_number = msg.get('from') or ''
            normalized = re.sub(r'\D', '', from_number)
            if not normalized:
                _logger.warning("Cannot normalize phone from %s", from_number)
                return True

            phone_e164 = '+' + normalized if not from_number.startswith('+') else from_number

            Lead = request.env['crm.lead'].sudo()
            Partner = request.env['res.partner'].sudo()

            # --- MODIFIED SEARCH LOGIC ---
            # Find lead by the LAST 9 DIGITS of the phone number.
            # This is more robust against international vs. local formatting (e.g. +20 vs 0).
            search_fragment = normalized[-9:]

            lead = Lead.search([
                '|', ('phone', 'like', search_fragment), ('mobile', 'like', search_fragment)
            ], limit=1)
            # --- END MODIFIED SEARCH LOGIC ---


            # Optionally create a lead if none found
            if not lead:
                _logger.info("No matching Lead; creating a new one for %s", phone_e164)
                lead = Lead.create({
                    'name': "WhatsApp from %s" % phone_e164,
                    'contact_name': phone_e164,
                    'phone': phone_e164,
                })

            # If lead has no partner, try link a partner by phone
            if not lead.partner_id:
                partner_match = Partner.search([
                    '|', ('phone', 'like', search_fragment), ('mobile', 'like', search_fragment)
                ], limit=1)
                if partner_match:
                    lead.partner_id = partner_match.id

            # Decide author: customer's partner if available, else public partner
            try:
                public_partner = request.env.ref('base.public_partner')
                public_pid = public_partner.id if public_partner else False
            except Exception:
                public_pid = False

            author_id = lead.partner_id.id if lead.partner_id else public_pid

            # -------- followers to notify --------
            follower_partners = set(lead.message_follower_ids.mapped('partner_id').ids)
            if lead.user_id and lead.user_id.partner_id:
                follower_partners.add(lead.user_id.partner_id.id)

            # Subscribe missing followers
            existing = set(lead.message_follower_ids.mapped('partner_id').ids)
            to_sub = list(follower_partners - existing)
            if to_sub:
                lead.message_subscribe(partner_ids=to_sub)

            # -------- post COMMENT (no email), with customer as author --------
            ctx = {
                'mail_post_autofollow': True,
                'mail_notify_noemail': True,  # suppress emails; still push in-app/bus
            }
            message_body = "WhatsApp Reply from %s:<br/>%s" % ((lead.partner_name or phone_e164), body)

            new_msg = lead.with_context(**ctx).message_post(
                author_id=author_id,               # show customer's name as author
                body=message_body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                notify=True,
                partner_ids=list(follower_partners)   # recipients (followers + salesperson)
            )

            # -------- explicit bus push to each follower's partner channel (live chatter) --------
            try:
                formatted = new_msg.message_format()[0]  # payload expected by web client
                dbname = request.env.cr.dbname
                Bus = request.env['bus.bus'].sudo()
                for pid in follower_partners:
                    Bus._sendone((dbname, 'res.partner', pid),
                                 {'type': 'mail.message/new', 'payload': formatted})
                _logger.info("Bus notifications sent to partners: %s", list(follower_partners))
            except Exception as e:
                _logger.exception("Failed explicit bus push (chatter): %s", e)

            # ---------- FORCE INBOX NOTIFICATIONS (top bell) ----------
            try:
                Notif = request.env['mail.notification'].sudo()
                existing_notifs = Notif.search([
                    ('mail_message_id', '=', new_msg.id),
                    ('res_partner_id', 'in', list(follower_partners))
                ])
                existing_map = {n.res_partner_id.id for n in existing_notifs}

                to_create = []
                for pid in follower_partners:
                    if pid in existing_map:
                        continue
                    to_create.append({
                        'mail_message_id': new_msg.id,
                        'res_partner_id': pid,
                        'notification_type': 'inbox',  # show in Odoo inbox/bell
                        'is_read': False,
                    })
                if to_create:
                    Notif.create(to_create)

                # send a bell/inbox bus event per partner (updates top bar in real time)
                dbname = request.env.cr.dbname
                Bus = request.env['bus.bus'].sudo()
                payload = {'message_id': new_msg.id, 'partner_ids': list(follower_partners)}
                for pid in follower_partners:
                    Bus._sendone((dbname, 'res.partner', pid),
                                 {'type': 'mail.message/notification', 'payload': payload})
            except Exception as e:
                _logger.exception("Failed to force inbox notifications: %s", e)
            # ---------- END FORCE INBOX ----------

        except Exception as e:
            _logger.exception("Error processing WhatsApp webhook: %s", e)

        return True