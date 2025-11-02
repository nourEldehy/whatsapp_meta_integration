# -*- coding: utf-8 -*-
import datetime
from odoo import models, fields, api

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    last_whatsapp_reply_date = fields.Datetime(
        string="Last WhatsApp Reply",
        readonly=True,
        help="The timestamp of the last message received from this lead via WhatsApp."
    )

    # --- NEW COMPUTED FIELD ---
    # This field will be True if the 24-hour reply window is open, and False otherwise.
    reply_window_open = fields.Boolean(
        string="Reply Window Open",
        compute='_compute_reply_window_open',
        readonly=True,
    )

    @api.depends('last_whatsapp_reply_date')
    def _compute_reply_window_open(self):
        """
        Calculates if the 24-hour window is open for each lead.
        """
        for lead in self:
            if lead.last_whatsapp_reply_date:
                time_since_reply = datetime.datetime.now() - lead.last_whatsapp_reply_date
                if time_since_reply < datetime.timedelta(hours=24):
                    lead.reply_window_open = True
                else:
                    lead.reply_window_open = False
            else:
                lead.reply_window_open = False
