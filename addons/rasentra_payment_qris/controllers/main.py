import hashlib
import hmac
import json
import time

from odoo import http
from odoo.http import request

MAX_SKEW = 300


class RasentraPaymentWebhook(http.Controller):
    """Hasil provider (diteruskan Central). HMAC-SHA256 atas "timestamp.nonce.body" dengan
    rahasia rasentra.payment.webhook_secret; timestamp maks. 5 menit; nonce tidak boleh dipakai ulang."""

    @http.route("/rasentra/payment/webhook", type="http", auth="none", methods=["POST"], csrf=False)
    def webhook(self, **_kw):
        env = request.env(su=True)
        secret = env["ir.config_parameter"].get_param("rasentra.payment.webhook_secret")
        body = request.httprequest.get_data()
        headers = request.httprequest.headers
        timestamp, nonce, signature = headers.get("X-Timestamp", ""), headers.get("X-Nonce", ""), headers.get("X-Signature", "")
        if not secret or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_SKEW or not nonce:
            return request.make_json_response({"error": "unauthorized"}, status=401)
        expected = hmac.new(secret.encode(), f"{timestamp}.{nonce}.".encode() + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return request.make_json_response({"error": "unauthorized"}, status=401)
        params = env["ir.config_parameter"]
        key = f"rasentra.payment.nonce.{nonce}"
        if params.get_param(key):
            return request.make_json_response({"error": "replay"}, status=409)
        params.set_param(key, timestamp)
        data = json.loads(body or b"{}")
        intent = env["rasentra.payment.intent"].search([("provider_ref", "=", data.get("provider_ref"))], limit=1)
        if not intent:
            return request.make_json_response({"error": "unknown"}, status=404)
        if not intent.apply_provider_result(data.get("status"), data.get("amount")):
            return request.make_json_response({"error": "payment_amount_mismatch"}, status=409)
        return request.make_json_response({"status": intent.status})
