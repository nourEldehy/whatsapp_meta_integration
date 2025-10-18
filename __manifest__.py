# whatsapp_meta_integration/__manifest__.py
{
    'name': 'WhatsApp Meta Integration',
    'version': '13.0.1.0.0',
    'summary': 'Custom integration with the official WhatsApp Business (Meta) API',
    'author': 'Noureldin ElDehi',
    'website': 'covermatch.com',
    'category': 'Tools',
    'depends': ['base', 'mail'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': True,
}