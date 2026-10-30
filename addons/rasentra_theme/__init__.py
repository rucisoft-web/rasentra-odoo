import base64

from odoo.tools import file_open


def post_init_hook(env):
    """Perusahaan tanpa logo memakai logo Rasentra agar login, struk dan laporan langsung bermerek."""
    with file_open("rasentra_theme/static/src/img/rasentra_logo.png", "rb") as logo:
        data = base64.b64encode(logo.read())
    default = env.ref("base.main_company")
    for company in env["res.company"].search([]):
        if not company.logo or company == default and company.name in ("YourCompany", "My Company"):
            company.logo = data
