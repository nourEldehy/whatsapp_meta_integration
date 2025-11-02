odoo.define('whatsapp_meta_integration.FormViewReload', function (require) {
"use strict";

var FormController = require('web.FormController');

FormController.include({
    /**
     * On start, check if we are on a crm.lead form and start listening.
     */
    start: function () {
        this._super.apply(this, arguments);
        if (this.modelName === 'crm.lead') {
            this.call('bus_service', 'onNotification', this, this._onLeadReloadNotification);
        }
    },

    /**
     * Handles the reload notification from the server.
     * @param {Array} notifications - The list of notifications from the bus.
     */
    _onLeadReloadNotification: function (notifications) {
        var self = this;
        notifications.forEach(function (notification) {
            // Check if the notification is on our custom 'lead_reload' channel
            if (notification[0] && notification[0][1] === 'lead_reload') {
                var leadId = notification[1].lead_id;
                // Check if the notification is for the lead we are currently viewing
                if (self.renderer.state.res_id === leadId) {
                    console.log('WhatsApp Integration: Reloading lead view for ID ' + leadId);
                    self.reload();
                }
            }
        });
    },
});

});