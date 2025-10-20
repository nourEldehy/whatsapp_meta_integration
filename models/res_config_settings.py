# whatsapp_meta_integration/models/res_config_settings.py
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

    def action_sync_templates(self):
        """Fetches all approved templates from Meta and creates/updates them in Odoo."""
        access_token = self.env['ir.config_parameter'].sudo().get_param('whatsapp_meta.access_token')
        waba_id = self.env['ir.config_parameter'].sudo().get_param('whatsapp_meta.waba_id')

        if not waba_id or not access_token:
            raise UserError(_("Please configure the Access Token and WABA ID before syncing."))

        url = f"https://graph.facebook.com/v18.0/{waba_id}/message_templates"
        params = {
            'fields': 'name,language,status,components',
            'limit': 200, # Increase if you have more than 200 templates
            'access_token': access_token
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json().get('data', [])
            
            approved_templates = [t for t in data if t.get('status') == 'APPROVED']
            Template = self.env['whatsapp.template']
            created_count = 0
            updated_count = 0

            for tpl in approved_templates:
                body_component = next((comp for comp in tpl.get('components', []) if comp['type'] == 'BODY'), None)
                if not body_component:
                    continue

                body_text = body_component.get('text', '')
                variable_count = body_text.count('{{')

                existing_template = Template.search([
                    ('name', '=', tpl['name']),
                    ('language_code', '=', tpl['language'])
                ], limit=1)

                vals = {
                    'name': tpl['name'],
                    'language_code': tpl['language'],
                    'body_text': body_text,
                    'variable_count': variable_count,
                }
                
                if existing_template:
                    existing_template.write(vals)
                    updated_count += 1
                else:
                    Template.create(vals)
                    created_count += 1
            
            _logger.info(f"WhatsApp templates synced: {created_count} created, {updated_count} updated.")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Successful'),
                    'message': _('%s templates created, %s templates updated.', created_count, updated_count),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except requests.exceptions.RequestException as e:
            error_message = e.response.text if e.response else str(e)
            _logger.error("Failed to sync WhatsApp templates: %s", error_message)
            raise UserError(_(f"Failed to sync templates: {error_message}"))