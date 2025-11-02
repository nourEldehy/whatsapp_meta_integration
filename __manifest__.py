# whatsapp_meta_integration/__manifest__.py
# Author: Noureldin ElDehy
{
    'name': 'WhatsApp Meta Integration',
    'version': '13.0.3.0.0',
    'summary': 'Custom integration with the official WhatsApp Business (Meta) API',
    'author': 'Your Name',
    'website': 'yourwebsite.com',
    'category': 'Tools',
    'depends': ['base', 'mail', 'crm', 'sale_management'],
    'data': [
        'security/ir.model.access.csv',

        # MUST be before the CRM view that references the action
        'wizard/reply_whatsapp_wizard_views.xml',

        'wizard/send_whatsapp_wizard_views.xml',
        'views/res_partner_actions.xml',
        'views/res_partner_views.xml',
        'views/whatsapp_views.xml',

        # after the action exists
        'views/crm_lead_views.xml',

        'views/sale_order_views.xml',
        'views/res_config_settings_views.xml',
        #'views/assets.xml',
    ],
    'installable': True,
    'application': True,
}

