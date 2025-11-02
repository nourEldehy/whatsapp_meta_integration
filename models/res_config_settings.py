#Author: Noureldin ElDehy
# whatsapp_meta_integration/models/res_config_settings.py
import re
import requests
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    whatsapp_meta_access_token = fields.Char(
        string='Meta Access Token',
        config_parameter='whatsapp_meta.access_token'
    )
    whatsapp_meta_phone_number_id = fields.Char(
        string='Phone Number ID',
        config_parameter='whatsapp_meta.phone_number_id'
    )
    whatsapp_meta_waba_id = fields.Char(
        string='WhatsApp Business Account ID (WABA ID)',
        config_parameter='whatsapp_meta.waba_id',
        help="The ID of your WhatsApp Business Account, required for syncing templates."
    )
    whatsapp_meta_verify_token = fields.Char(
        string='Webhook Verify Token',
        help="A custom secret string for webhook verification.",
        config_parameter='whatsapp_meta.verify_token'
    )

    # --- THIS FUNCTION IS NOW CORRECTLY INDENTED ---
    def action_sync_templates(self):
        """Fetches all approved templates from Meta and creates/updates them in Odoo."""
        import re

        access_token = self.env['ir.config_parameter'].sudo().get_param('whatsapp_meta.access_token')
        waba_id = self.env['ir.config_parameter'].sudo().get_param('whatsapp_meta.waba_id')
        if not waba_id or not access_token:
            raise UserError(_("Please configure the Access Token and WABA ID before syncing."))

        url = f"https://graph.facebook.com/v19.0/{waba_id}/message_templates"
        params = {
            'fields': 'name,language,status,components',
            'limit': 200,
            'access_token': access_token
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json().get('data', [])

            approved_templates = [t for t in data if t.get('status') == 'APPROVED']
            Template = self.env['whatsapp.template']
            created_count, updated_count = 0, 0

            for tpl in approved_templates:
                body_component = next((c for c in tpl.get('components', []) if c['type'] == 'BODY'), None)
                header_component = next((c for c in tpl.get('components', []) if c['type'] == 'HEADER'), None)

                body_text = body_component.get('text', '') if body_component else ''
                
                matches = re.findall(r'\{\{([a-zA-Z0-9_]+)\}\}', body_text)
                variable_count = len(matches)

                has_header_variable = 'example' in header_component if header_component else False
                header_type = header_component.get('format', 'TEXT') if header_component else ''

                existing = Template.search([('name', '=', tpl['name']), ('language_code', '=', tpl['language'])], limit=1)
                vals = {
                    'name': tpl['name'], 'language_code': tpl['language'], 'body_text': body_text,
                    'variable_count': variable_count, 'has_header_variable': has_header_variable, 'header_type': header_type,
                }

                if existing:
                    existing.write(vals)
                    updated_count += 1
                else:
                    Template.create(vals)
                    created_count += 1

            message = _('%s templates created, %s templates updated.') % (created_count, updated_count)
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Sync Successful'), 'message': message, 'type': 'success', 'sticky': False}
            }
        except requests.exceptions.RequestException as e:
            error_message = e.response.json().get('error', {}).get('message', str(e))
            _logger.error("Failed to sync WhatsApp templates: %s", error_message)
            raise UserError(_(f"Failed to sync templates: {error_message}"))