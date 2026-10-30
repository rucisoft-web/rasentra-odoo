import mimetypes
import os

from odoo import http
from odoo.http import request
from odoo.tools import file_path

DOCS_ROOT = "rasentra_docs/docs"


class RasentraDocs(http.Controller):
    """Spesifikasi & panduan hanya untuk pengguna yang login (bukan /static yang publik)."""

    @http.route(["/rasentra/docs", "/rasentra/docs/<path:name>"], type="http", auth="user", methods=["GET"])
    def docs(self, name="index.html", **_kw):
        name = os.path.normpath(name).lstrip("/")
        if name.startswith("..") or os.path.isabs(name):
            raise request.not_found()
        try:
            path = file_path(f"{DOCS_ROOT}/{name}")
        except FileNotFoundError:
            raise request.not_found() from None
        if not os.path.isfile(path):
            raise request.not_found()
        with open(path, "rb") as handle:
            content = handle.read()
        mimetype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return request.make_response(content, headers=[
            ("Content-Type", f"{mimetype}; charset=utf-8" if mimetype.startswith("text/") else mimetype),
            ("Cache-Control", "private, max-age=600"),
            ("X-Content-Type-Options", "nosniff"),
        ])
