# whatsapp_meta_integration/controllers/main.py
import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class WhatsAppController(http.Controller):

    @http.route('/whatsapp/webhook', methods=['GET'], type='http', auth='public', csrf=False)
    def webhook_verify(self, **kwargs):
        verify_token = request.env['ir.config_parameter'].sudo().get_param('whatsapp_meta.verify_token')
        if kwargs.get('hub.mode') == 'subscribe' and kwargs.get('hub.verify_token') == verify_token:
            _logger.info("Webhook successfully verified.")
            return kwargs.get('hub.challenge')
        _logger.warning("Webhook verification failed.")
        return 'Forbidden', 403

    @http.route('/whatsapp/webhook', methods=['POST'], type='json', auth='public', csrf=False)
    def webhook_receive(self, **kwargs):
        data = json.loads(request.httprequest.data)
        _logger.info("Received WhatsApp Webhook Data: %s", json.dumps(data, indent=2))
        if data.get('object') == 'whatsapp_business_account' and data.get('entry'):
            for entry in data['entry']:
                for change in entry.get('changes', []):
                    if change.get('field') == 'messages':
                        for message in change.get('value', {}).get('messages', []):
                            if message.get('type') == 'text':
                                self.handle_text_message(message)
        return 'OK'

    def handle_text_message(self, message):
        phone = message.get('from')
        body = message['text'].get('body')
        Partner = request.env['res.partner'].sudo()
        partner = Partner.search(['|', ('phone', '=', phone), ('mobile', '=', phone)], limit=1)
        if not partner:
            _logger.info("No partner found for phone number %s. Creating one.", phone)
            partner = Partner.create({'name': f"WhatsApp Contact {phone}", 'mobile': phone})
        if partner:
            partner.message_post(
                body=f"WhatsApp Message Received: {body}",
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            _logger.info("Posted message from %s to partner %s", phone, partner.name)