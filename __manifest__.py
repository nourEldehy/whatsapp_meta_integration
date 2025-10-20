# whatsapp_meta_integration/__manifest__.py
{
    'name': 'WhatsApp Meta Integration',
    'version': '13.0.3.0.0', # It's good practice to increment the version
    'summary': 'Custom integration with the official WhatsApp Business (Meta) API',
    'author': 'Your Name',
    'website': 'yourwebsite.com',
    'category': 'Tools',
    'depends': [
        'base',
        'mail',
        'crm',              # <-- ADD THIS
        'sale_management'   # <-- ADD THIS
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/whatsapp_views.xml',
        'views/res_partner_views.xml',
        'views/res_partner_actions.xml',
        'views/crm_lead_views.xml',       # <-- ADD THIS
        'views/sale_order_views.xml',       # <-- ADD THIS
        'wizard/send_whatsapp_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
}