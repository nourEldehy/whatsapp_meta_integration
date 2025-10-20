# whatsapp_meta_integration/__manifest__.py
{
    'name': 'WhatsApp Meta Integration',
    'version': '13.0.2.0.0',
    'summary': 'Custom integration with the official WhatsApp Business (Meta) API',
    'author': 'Noureldin ElDehi',
    'website': 'covermatch.com',
    'category': 'Tools',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/whatsapp_views.xml',
        'views/res_partner_views.xml',
        'views/res_partner_actions.xml',
        'wizard/send_whatsapp_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
}