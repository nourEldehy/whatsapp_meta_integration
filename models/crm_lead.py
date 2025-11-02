# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Updated by webhook on inbound WhatsApp
    last_wa_inbound = fields.Datetime(string="Last WA inbound")

    # Computed window status + deadline + remaining text
    reply_window_open = fields.Boolean(
        string='WA 24h Window Open',
        compute='_compute_reply_window_fields',
        store=False,
    )
    reply_window_deadline = fields.Datetime(
        string='WA reply deadline',
        compute='_compute_reply_window_fields',
        store=False,
    )
    reply_window_remaining_text = fields.Char(
        string='Time left to reply',
        compute='_compute_reply_window_fields',
        store=False,
    )

    @api.depends('last_wa_inbound')
    def _compute_reply_window_fields(self):
        now = fields.Datetime.now()
        for lead in self:
            deadline = None
            open_flag = False
            remaining_text = "Expired"

            if lead.last_wa_inbound:
                deadline = lead.last_wa_inbound + timedelta(hours=24)
                open_flag = now <= deadline
                if open_flag:
                    delta = deadline - now
                    secs = int(delta.total_seconds())
                    hours = secs // 3600
                    mins = (secs % 3600) // 60
                    if hours and mins:
                        remaining_text = f"{hours}h {mins}m left"
                    elif hours:
                        remaining_text = f"{hours}h left"
                    elif mins:
                        remaining_text = f"{mins}m left"
                    else:
                        remaining_text = "Under 1m left"

            lead.reply_window_deadline = deadline
            lead.reply_window_open = open_flag
            lead.reply_window_remaining_text = remaining_text

    def action_open_whatsapp_reply_wizard(self):
        """Open the Reply wizard (free-form only allowed inside 24h)."""
        self.ensure_one()
        view = self.env.ref('whatsapp_meta_integration.view_whatsapp_reply_wizard_form')
        default_phone = self.partner_id.mobile or self.partner_id.phone or ''
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reply via WhatsApp',
            'res_model': 'whatsapp.reply.wizard',
            'view_mode': 'form',
            'views': [(view.id, 'form')],  # important for webclient restore
            'view_id': view.id,
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
                'default_partner_id': self.partner_id.id or False,
                'default_to_number': default_phone,
                'default_window_ok': self.reply_window_open,
            },
        }

