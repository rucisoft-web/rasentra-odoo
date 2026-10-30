from odoo import http
from odoo.http import request

from ..models.importers import IMPORTERS


class RasentraMigrationTemplate(http.Controller):
    @http.route("/rasentra/migration/template/<string:entity>.csv", type="http", auth="user")
    def template(self, entity):
        importer = IMPORTERS.get(entity)
        if not importer or not request.env.user.has_group("rasentra_core.group_rasentra_admin"):
            return request.not_found()
        # BOM agar Excel di Windows membaca UTF-8 dengan benar.
        content = "﻿" + importer(request.env).template()
        return request.make_response(content.encode("utf-8"), headers=[
            ("Content-Type", "text/csv; charset=utf-8"),
            ("Content-Disposition", f'attachment; filename="{entity}.csv"'),
        ])
