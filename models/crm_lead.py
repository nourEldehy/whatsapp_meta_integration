# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import timedelta

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Set this when an inbound WhatsApp is received
    last_whatsapp_reply_date = fields.Datetime(readonly=True)

    # Computed flag used by the view to show/hide the reply button
    reply_window_open = fields.Boolean(
        compute='_compute_reply_window_open',
        help="True only within 24h since the last inbound WhatsApp message."
    )

    @api.depends('last_whatsapp_reply_date')
    def _compute_reply_window_open(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.reply_window_open = bool(
                rec.last_whatsapp_reply_date and
                (now - rec.last_whatsapp_reply_date) <= timedelta(hours=24)
            )
