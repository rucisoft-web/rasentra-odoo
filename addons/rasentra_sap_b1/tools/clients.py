"""Klien SAP Business One. Hanya berjalan di Rasentra Central; kredensial tidak pernah ke outlet."""
import logging
import time

import requests

_logger = logging.getLogger(__name__)

# Kendali klien palsu untuk uji dan demo (padanan properti FakeSapClient Laravel):
# {"fail_next": {"IncomingPayments": 1}, "timeout_after_commit_once": False, "unreachable": False}
FAKE_CONTROL = {"fail_next": {}, "timeout_after_commit_once": False, "unreachable": False}


class SapTimeout(Exception):
    """Hasil posting belum pasti (timeout/putus koneksi): jangan buat ulang, periksa SAP dulu."""


class FakeSapClient:
    """SAP tiruan. Dokumen disimpan di rasentra.sap.fake.document agar demo bisa dilihat di layar."""

    def __init__(self, env, company_db):
        self.env = env
        self.company_db = company_db
        self.Docs = env["rasentra.sap.fake.document"].sudo()

    def find_by_source_ref(self, sap_object, source_ref):
        doc = self.Docs.search([("company_db", "=", self.company_db), ("sap_object", "=", sap_object),
                                ("source_ref", "=", source_ref)], limit=1)
        return {"DocEntry": doc.doc_entry, "DocNum": doc.doc_num, "DocTotal": doc.doc_total} if doc else None

    def create(self, sap_object, payload):
        fail = FAKE_CONTROL["fail_next"]
        if fail.get(sap_object, 0) > 0:
            fail[sap_object] -= 1
            raise RuntimeError(f"SAP menolak {sap_object}")
        doc = self.Docs.create({
            "company_db": self.company_db, "sap_object": sap_object, "source_ref": payload["U_POS_SRC"],
            "doc_total": payload.get("DocTotal"), "payload": payload,
        })
        if FAKE_CONTROL["timeout_after_commit_once"]:
            FAKE_CONTROL["timeout_after_commit_once"] = False
            raise SapTimeout("Timeout setelah SAP menyimpan dokumen")
        return {"DocEntry": doc.doc_entry, "DocNum": doc.doc_num, "DocTotal": doc.doc_total}

    def ping(self):
        if FAKE_CONTROL["unreachable"]:
            raise RuntimeError("Service Layer tidak dapat dihubungi")
        return {"mode": "simulasi"}


class ServiceLayerClient:
    """Klien Service Layer. Cookie B1SESSION disimpan per proses dan diperbarui saat 401."""

    _sessions = {}

    def __init__(self, config):
        self.config = config
        self.base = config["url"].rstrip("/")
        self.verify = config.get("verify", True)

    def _login(self):
        try:
            res = requests.post(f"{self.base}/Login", json={
                "CompanyDB": self.config["company_db"], "UserName": self.config["username"],
                "Password": self.config["password"],
            }, timeout=30, verify=self.verify)
        except requests.RequestException as error:
            raise SapTimeout(str(error)) from error
        res.raise_for_status()
        session = res.cookies.get("B1SESSION")
        self._sessions[self.config["company_db"]] = (session, time.time())
        return session

    def _request(self, method, path, timeout=60, **kwargs):
        cached = self._sessions.get(self.config["company_db"])
        session = cached[0] if cached and time.time() - cached[1] < 25 * 60 else self._login()
        for attempt in (1, 2):
            try:
                res = requests.request(method, f"{self.base}/{path}", cookies={"B1SESSION": session},
                                       timeout=timeout, verify=self.verify, **kwargs)
            except (requests.Timeout, requests.ConnectionError) as error:
                raise SapTimeout(str(error)) from error
            if res.status_code == 401 and attempt == 1:
                session = self._login()
                continue
            res.raise_for_status()
            return res.json() if res.content else {}

    def find_by_source_ref(self, sap_object, source_ref):
        ref = source_ref.replace("'", "''")
        rows = self._request("GET", sap_object, params={
            "$filter": f"U_POS_SRC eq '{ref}'", "$select": "DocEntry,DocNum,DocTotal",
        }).get("value") or []
        return rows[0] if rows else None

    def create(self, sap_object, payload):
        response = self._request("POST", sap_object, json=payload)
        return {"DocEntry": int(response["DocEntry"]), "DocNum": int(response["DocNum"])}

    def ping(self):
        self._request("GET", "Warehouses", timeout=15, params={"$top": 1, "$select": "WarehouseCode"})
        return {"mode": "service_layer"}
