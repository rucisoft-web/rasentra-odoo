"""JSON dan checksum yang identik dengan `json_encode($x, JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION)`.

Checksum event harus sama persis dengan versi Laravel agar Rasentra Lokal Laravel dan
Rasentra Lokal Odoo bisa mengirim ke Central yang sama selama masa transisi.
"""

import hashlib
import json


def php_json(value):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    # PHP tetap meng-escape "/" dan pemisah baris U+2028/U+2029 walau JSON_UNESCAPED_UNICODE aktif.
    return text.replace("/", "\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def checksum(payload):
    return hashlib.sha256(php_json(payload).encode()).hexdigest()
