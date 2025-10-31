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
    """Return human-readable value from a record for any field, using fields_get to format."""
    if not field_name or field_name not in record._fields:
        return ''
    fdefs = record.fields_get([field_name]) or {}
    fdef = fdefs.get(field_name, {})
    ftype = fdef.get('type')
    val = record[field_name]

    if ftype == 'many2one':
        return val.name or '' if val else ''
    if ftype == 'selection':
        sel = dict(fdef.get('selection') or [])
        return sel.get(val, '') if val else ''
    if ftype in ('many2many', 'one2many'):
        try:
            return ", ".join(val.mapped('name')) if val else ''
        except Exception:
            return ''
    return val if isinstance(val, str) else (val and str(val) or '')


def _find_field_on_record_by_label_contains(record, needles):
    """
    Find a field on `record` whose label (string) contains ALL `needles` (case-insensitive).
    Works for custom fields because it uses in-memory `_fields`.
    """
    needles = [n.lower() for n in (needles or []) if n]
    for name, field in record._fields.items():
        label = (getattr(field, 'string', '') or '').lower()
        if label and all(n in label for n in needles):
            return name
    return None


# -----------------------------
# Wizard
# -----------------------------
class SendWhatsappWizard(models.TransientModel):
    _name = 'send.whatsapp.wizard'
    _description = 'Send WhatsApp Message Wizard'

    # Recipient
    partner_id = fields.Many2one('res.partner', string="Recipient")
    to_number = fields.Char(string="To (E.164 or CC-first)", help="Number like +2010..., 2010..., or 002010...")

    # Template
    template_id = fields.Many2one('whatsapp.template', string="Template", required=True)

    # Header
    has_header_variable = fields.Boolean(related='template_id.has_header_variable')
    header_variable_value = fields.Char(string="Header Variable")
    header_variable_description = fields.Char(related='template_id.header_variable_description', readonly=True)
    header_type = fields.Char(related='template_id.header_type')  # e.g. TEXT / IMAGE

    # Body
    variable_ids = fields.One2many('whatsapp.variable.input', 'wizard_id', string="Body Variables")

    # -----------------------------
    # Defaults & onchange
    # -----------------------------
    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)

        lead_id = self._context.get('default_lead_id') or self._context.get('lead_id')
        if lead_id:
            lead = self.env['crm.lead'].sudo().browse(lead_id)
            if lead.exists():
                if 'partner_id' in fields_list and lead.partner_id:
                    vals['partner_id'] = lead.partner_id.id
                if 'to_number' in fields_list:
                    vals['to_number'] = (
                        (lead.partner_id and (lead.partner_id.mobile or lead.partner_id.phone))
                        or lead.mobile or lead.phone or ''
                    )

        if not vals.get('partner_id'):
            partner_id = self._context.get('default_partner_id')
            if partner_id:
                partner = self.env['res.partner'].sudo().browse(partner_id)
                if partner.exists():
                    vals['partner_id'] = partner.id
                    if 'to_number' in fields_list and not vals.get('to_number'):
                        vals['to_number'] = partner.mobile or partner.phone or ''
        return vals

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and not self.to_number:
            self.to_number = self.partner_id.mobile or self.partner_id.phone or ''

    @api.onchange('template_id')
    def _onchange_template_id(self):
        """
        Auto-fill variables strictly by matching the variable LABEL text (like Customer Name).
        - "Insurance Type" => any lead field label containing ['insurance','type'] (prefers also 'individual').
        - "Agent Phone"    => salesperson's employee.mobile_phone/work_phone, else user partner phone.
        """
        self.variable_ids = [(5, 0, 0)]
        if not self.template_id or not self.template_id.variable_count:
            return

        descriptions = [d.strip() for d in (self.template_id.variable_descriptions or '').split(',')] \
            if self.template_id.variable_descriptions else []

        partner = self.partner_id
        current_user = self.env.user

        # Lead context
        lead = None
        lead_id = self._context.get('default_lead_id') or self._context.get('lead_id')
        if lead_id:
            lead = self.env['crm.lead'].sudo().browse(lead_id)

        # ---- Agent phone (Odoo 13 uses mobile_phone) ----
        agent_user = (lead and lead.user_id) or current_user
        agent_phone = ''
        if agent_user:
            # 1) employee linked to user
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', agent_user.id)], limit=1)
            if emp:
                agent_phone = emp.mobile_phone or emp.work_phone or ''
            # 2) fuzzy by name/email
            if not agent_phone:
                emp2 = self.env['hr.employee'].sudo().search([
                    '|', ('name', 'ilike', agent_user.name),
                         ('work_email', 'ilike', agent_user.email or '')
                ], limit=1)
                if emp2:
                    agent_phone = emp2.mobile_phone or emp2.work_phone or ''
            # 3) fallback to user's partner
            if not agent_phone and agent_user.partner_id:
                agent_phone = agent_user.partner_id.mobile or agent_user.partner_id.phone or ''

        # ---- Insurance type via label on lead ----
        insurance_value = ''
        if lead:
            fld = _find_field_on_record_by_label_contains(lead, ['individual', 'insurance', 'type'])
            if not fld:
                fld = _find_field_on_record_by_label_contains(lead, ['insurance', 'type'])
            if fld:
                insurance_value = _display_value_for_field(lead, fld)

        # ---- Build variable rows ----
        lines = []
        for i in range(1, self.template_id.variable_count + 1):
            label = descriptions[i - 1] if i <= len(descriptions) else f'Body Variable {{{i}}}'
            value = ''
            l = (label or '').lower()

            if partner and ('customer' in l and 'name' in l):
                value = partner.name or ''
            elif 'insurance' in l and 'type' in l:
                value = insurance_value or ''
            elif agent_user and ('agent' in l and 'name' in l):
                value = agent_user.name or ''
            elif 'agent' in l and any(k in l for k in ['phone', 'mobile', 'whatsapp']):
                value = agent_phone or ''

            lines.append((0, 0, {'sequence': i, 'name': label, 'value': value}))

        self.variable_ids = lines

    # -----------------------------
    # Send
    # -----------------------------
    def action_send_message(self):
        self.ensure_one()

        ICP = self.env['ir.config_parameter'].sudo()
        access_token = ICP.get_param('whatsapp_meta.access_token')
        phone_number_id = ICP.get_param('whatsapp_meta.phone_number_id')
        if not access_token or not phone_number_id:
            raise UserError(_("WhatsApp access token / phone number ID are not configured (System Parameters)."))
        api_version = ICP.get_param('whatsapp_meta.api_version') or 'v19.0'
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
                media_type = header_kind.lower()   # image/document/video
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

        payload = {
            "messaging_product": "whatsapp",
            "to": to_e164,
            "type": "template",
            "template": {
                "name": self.template_id.name,
                "language": {"code": self.template_id.language_code},
            },
        }
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
