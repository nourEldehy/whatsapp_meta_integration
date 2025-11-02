# -*- coding: utf-8 -*-
import logging
import json
from odoo import http, fields, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsAppWebhook(http.Controller):
    """
    Minimal webhook handler:
    - GET: Meta verification (hub.challenge)
    - POST: Incoming messages -> update crm.lead.last_wa_inbound
    NOTE: Adapt the sender-to-lead resolution to your data model if needed.
    """

    @http.route(['/whatsapp/webhook'], type='http', auth='public', methods=['GET'], csrf=False)
    def webhook_verify(self, **params):
        token_expected = request.env['ir.config_parameter'].sudo().get_param('whatsapp.verify_token') or ''
        mode = params.get('hub.mode')
        token = params.get('hub.verify_token')
        challenge = params.get('hub.challenge')
        if mode == 'subscribe' and token and token == token_expected:
            return challenge or ''
        return http.Response("Forbidden", status=403)

    @http.route(['/whatsapp/webhook'], type='json', auth='public', methods=['POST'], csrf=False)
    def webhook_receive(self, **payload):
        try:
            data = request.jsonrequest or {}
            self._handle_incoming(data)
        except Exception as e:
            _logger.exception("WA webhook error: %s", e)
        return {"status": "ok"}

    # ------------------ helpers ------------------

    def _handle_incoming(self, data):
        """
        Parse the Cloud API webhook and touch last_wa_inbound on the matched lead.
        This covers text & media messages in 'messages' list.
        """
        entries = data.get('entry', [])
        for entry in entries:
            changes = entry.get('changes', [])
            for change in changes:
                value = change.get('value', {})
                contacts = value.get('contacts') or []
                messages = value.get('messages') or []
                if not messages:
                    continue

                # Sender phone in E.164 (e.g., +2010xxxx)
                sender = messages[0].get('from')  # string
                if not sender:
                    continue

                self._touch_lead_from_phone(sender)

    def _touch_lead_from_phone(self, e164):
        """
        Find the active lead for this phone and update last_wa_inbound = now().
        Strategy:
          - Find partner by phone/mobile matching the last 9-12 digits
          - Then find the most recent open lead for that partner
        Adjust as per your data quality.
        """
        env = request.env
        Partner = env['res.partner'].sudo()
        Lead = env['crm.lead'].sudo()

        # Try strict match first (full E.164)
        partner = Partner.search([('mobile', '=', e164)], limit=1)
        if not partner:
            partner = Partner.search([('phone', '=', e164)], limit=1)

        # Fallback: loose tail match (e.g., last 10 digits)
        if not partner and e164 and e164.startswith('+') and len(e164) > 6:
            tail = e164[-10:]
            partner = Partner.search(['|', ('mobile', 'ilike', tail), ('phone', 'ilike', tail)], limit=1)

        lead = None
        if partner:
            lead = Lead.search([('partner_id', '=', partner.id)], order='create_date desc', limit=1)
        else:
            # As a last resort, try lead phone fields
            lead = Lead.search(['|', ('mobile', '=', e164), ('phone', '=', e164)], order='create_date desc', limit=1)
            if not lead and e164 and len(e164) > 6:
                tail = e164[-10:]
                lead = Lead.search(['|', ('mobile', 'ilike', tail), ('phone', 'ilike', tail)], order='create_date desc', limit=1)

        if lead:
            lead.write({'last_wa_inbound': fields.Datetime.now()})
            _logger.info("Updated last_wa_inbound on lead %s for %s", lead.id, e164)
        else:
            _logger.info("No lead matched for inbound WA from %s", e164)

