odoo.define('whatsapp_meta_integration.chatter', function (require) {
"use strict";

var ChatThread = require('mail.ChatThread');
var session = require('web.session');

/**
 * This JS code listens for notifications on the bus and refreshes the chatter
 * when a new WhatsApp message is received.
 */
ChatThread.include({
    init: function () {
        this._super.apply(this, arguments);
        // Start listening to bus notifications
        this.call('bus_service', 'onNotification', this, this._onBusNotification);
    },

    _onBusNotification: function (notifications) {
        var self = this;
        notifications.forEach(function (notification) {
            // Check if the notification is for a new WhatsApp message
            if (notification[0][1] === 'whatsapp_new_message') {
                var message = notification[1];
                
                // Check if the chatter we're looking at is for the correct document
                if (self.getThreadID() === message.res_id && self.getThreadModel() === message.model) {
                    // Refresh the chatter to show the new message
                    self.trigger_up('reload_mail_fields', {
                        thread: true,
                        followers: true,
                        activities: true,
                    });
                }
            }
        });
    },
});

});