# Author: Noureldin ElDehy
# whatsapp_meta_integration/wizard/send_whatsapp_wizard.py
import json
import logging
import requests
import re

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# -----------------------------
# Helpers
# -----------------------------
def _normalize_e164_no_country(raw):
    # ... (This function remains unchanged) ...
    if not raw:
        raise UserError(_("No destination phone set for the recipient."))
    s = (raw or '').strip()
    digits_only = re.sub(r'\D', '', s)
    if s.startswith('+'):
        digits = digits_only
    elif s.startswith('00'):
        digits = digits_only[2:]
    else:
        digits = digits_only
    if not digits or len(digits) < 8 or len(digits) > 15:
        raise UserError(_("Phone number looks invalid. Use country code first, e.g. +2010XXXXXXXX."))
    return '+' + digits


def _display_value_for_field(record, field_name):
    """Return human-readable value from a record for any field type."""
    if not field_name or field_name not in record._fields:
        return ''
    val = record[field_name]
    if not val:
        return ''
    field_type = record._fields[field_name].type
    if field_type == 'many2one':
        return val.display_name or ''
    if field_type == 'selection':
        return dict(record._fields[field_name].selection).get(val, '')
    if field_type in ('many2many', 'one2many'):
        return ", ".join(val.mapped('display_name'))
    return str(val)


# -----------------------------
# Wizard
# -----------------------------
class SendWhatsappWizard(models.TransientModel):
    _name = 'send.whatsapp.wizard'
    _description = 'Send WhatsApp Message Wizard'

    # ... (Fields remain unchanged) ...
    partner_id = fields.Many2one('res.partner', string="Recipient")
    to_number = fields.Char(string="To (E.164 or CC-first)", help="Number like +2010..., 2010..., or 002010...")
    template_id = fields.Many2one('whatsapp.template', string="Template", required=True)
    has_header_variable = fields.Boolean(related='template_id.has_header_variable')
    header_variable_value = fields.Char(string="Header Variable")
    header_variable_description = fields.Char(related='template_id.header_variable_description', readonly=True)
    header_type = fields.Char(related='template_id.header_type')
    variable_ids = fields.One2many('whatsapp.variable.input', 'wizard_id', string="Body Variables")

    @api.model
    def default_get(self, fields_list):
        # ... (This function remains unchanged) ...
        vals = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_id = self.env.context.get('active_id')
        if active_model == 'crm.lead' and active_id:
            lead = self.env['crm.lead'].browse(active_id)
            if lead.partner_id:
                vals['partner_id'] = lead.partner_id.id
                vals['to_number'] = lead.partner_id.mobile or lead.partner_id.phone or ''
            if not vals.get('to_number'):
                vals['to_number'] = lead.mobile or lead.phone or ''
        elif active_model == 'res.partner' and active_id:
            partner = self.env['res.partner'].browse(active_id)
            vals['partner_id'] = partner.id
            vals['to_number'] = partner.mobile or partner.phone or ''
        return vals

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        # ... (This function remains unchanged) ...
        if self.partner_id and not self.to_number:
            self.to_number = self.partner_id.mobile or self.partner_id.phone or ''

    @api.onchange('template_id')
    def _onchange_template_id(self):
        """
        MODIFIED: Auto-fills variables by matching the variable LABEL text.
        """
        self.variable_ids = [(5, 0, 0)]
        if not self.template_id or not self.template_id.variable_count:
            return

        descriptions = [d.strip() for d in (self.template_id.variable_descriptions or '').split(',')] \
            if self.template_id.variable_descriptions else []

        partner = self.partner_id
        
        lead = self.env['crm.lead'].browse(self.env.context.get('active_id')) if self.env.context.get('active_model') == 'crm.lead' else None

        # ---- Agent phone ----
        agent_phone = ''
        if lead and lead.user_id and lead.user_id.employee_ids:
            agent_phone = lead.user_id.employee_ids[0].work_mobile or ''
        
        # ---- Insurance type (finds and joins ALL insurance fields) ----
        insurance_values = []
        if lead:
            for name, field in lead._fields.items():
                label = (getattr(field, 'string', '') or '').lower()
                if 'insurance' in label:
                    # --- THIS IS THE FIX ---
                    # Use the helper function to safely get the value for any field type
                    value = _display_value_for_field(lead, name)
                    if value:
                        insurance_values.append(value)
        insurance_type_str = ", ".join(insurance_values)

        # ---- Build variable rows ----
        lines = []
        for i in range(1, self.template_id.variable_count + 1):
            label = descriptions[i - 1] if i <= len(descriptions) else f'Body Variable {{{i}}}'
            value = ''
            l = (label or '').lower()

            if partner and ('customer' in l and 'name' in l):
                value = partner.name or ''
            elif 'insurance' in l and 'type' in l:
                value = insurance_type_str
            elif lead and lead.user_id and ('agent' in l and 'name' in l):
                value = lead.user_id.name or ''
            elif 'agent' in l and any(k in l for k in ['phone', 'mobile', 'whatsapp']):
                value = agent_phone
            
            lines.append((0, 0, {'sequence': i, 'name': label, 'value': value}))

        self.variable_ids = lines

    def action_send_message(self):
        # ... (This function remains unchanged) ...
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        access_token = ICP.get_param('whatsapp.access_token')
        phone_number_id = ICP.get_param('whatsapp.phone_number_id')
        if not access_token or not phone_number_id:
            raise UserError(_("WhatsApp access token / phone number ID are not configured."))
        api_version = ICP.get_param('whatsapp.api_version') or 'v19.0'
        url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        dest_raw = (self.to_number or (self.partner_id and (self.partner_id.mobile or self.partner_id.phone)) or '').strip()
        if not dest_raw:
            raise UserError(_("Recipient has no phone/mobile set."))
        to_e164 = _normalize_e164_no_country(dest_raw)
        components = []
        if self.has_header_variable:
            if not self.header_variable_value:
                raise UserError(_("Please provide a value for the Header Variable."))
            header_kind = (self.header_type or '').upper()
            if header_kind == 'TEXT':
                parameters = [{"type": "text", "text": self.header_variable_value}]
            else:
                media_type = header_kind.lower()
                parameters = [{"type": media_type, media_type: {"link": self.header_variable_value}}]
            components.append({"type": "header", "parameters": parameters})
        if self.variable_ids:
            if any((not var.value) for var in self.variable_ids):
                raise UserError(_("Please fill in all Body Variable values before sending."))
            placeholder_names = re.findall(r'\{\{([a-zA-Z0-9_]+)\}\}', self.template_id.body_text or '')
            body_params = []
            for i, var in enumerate(self.variable_ids.sorted(key=lambda r: r.sequence or 0)):
                param = {"type": "text", "text": var.value or ""}
                if i < len(placeholder_names):
                    param['parameter_name'] = placeholder_names[i]
                body_params.append(param)
            if body_params:
                components.append({"type": "body", "parameters": body_params})
        payload = {"messaging_product": "whatsapp", "to": to_e164, "type": "template", "template": {"name": self.template_id.name, "language": {"code": self.template_id.language_code},},}
        if components:
            payload["template"]["components"] = components
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        try:
            _logger.info("Sending WhatsApp TEMPLATE to %s: %s", to_e164, json.dumps(payload)[:500])
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            log_body = _("Sent WhatsApp Template: <b>%s</b> to <b>%s</b>") % (self.template_id.name, to_e164)
            active_model = self.env.context.get('active_model')
            active_id = self.env.context.get('active_id')
            if active_model and active_id and hasattr(self.env[active_model], 'message_post'):
                self.env[active_model].browse(active_id).message_post(body=log_body, message_type='comment', subtype_xmlid='mail.mt_comment')
            elif self.partner_id and hasattr(self.partner_id, 'message_post'):
                self.partner_id.message_post(body=log_body, message_type='comment', subtype_xmlid='mail.mt_comment')
        except requests.exceptions.RequestException as e:
            err_text = getattr(e.response, 'text', '') if hasattr(e, 'response') and e.response is not None else str(e)
            try:
                j = e.response.json()
                err = j.get('error', {})
                msg = err.get('message', err_text)
                details = (err.get('error_data') or {}).get('details', '')
                raise UserError(_("Failed to send message: %s\n\nDetails: %s") % (msg, details))
            except Exception:
                _logger.error("Failed to send WhatsApp message: %s", err_text)
                raise UserError(_("Failed to send message: %s") % err_text)
        return {'type': 'ir.actions.act_window_close'}
