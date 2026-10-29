"""Importir CSV data awal migrasi. Setiap entitas: kolom template, pemeriksaan per baris, lalu penulisan.

Pemeriksaan tidak menulis apa pun; penulisan hanya dijalankan bila semua baris lolos. Referensi antar file
(outlet → wilayah, harga → produk, ...) harus sudah ada di Rasentra, jadi impor mengikuti urutan `ORDER`.
"""

import csv
import io
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from odoo.addons.rasentra_core.models.hr_employee import RASENTRA_ROLES
from odoo.addons.rasentra_core.models.product_template import KITCHEN_STATIONS

YES = {"y", "ya", "yes", "1", "true", "x"}
NO = {"", "n", "t", "tidak", "no", "0", "false"}
UOMS = {
    "kg": "uom.product_uom_kgm", "g": "uom.product_uom_gram", "gram": "uom.product_uom_gram",
    "pcs": "uom.product_uom_unit", "unit": "uom.product_uom_unit", "unit(s)": "uom.product_uom_unit",
    "porsi": "uom.product_uom_unit", "l": "uom.product_uom_litre", "liter": "uom.product_uom_litre",
    "litre": "uom.product_uom_litre", "ml": "uom.product_uom_millilitre",
}
TYPES = ("retail", "meat_pack", "menu", "ingredient", "service")
ROLES = tuple(key for key, _label in RASENTRA_ROLES)
STATIONS = tuple(key for key, _label in KITCHEN_STATIONS)
TIMEZONES = ("Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura")
ENTITY_TYPES = ("product", "outlet", "customer", "payment_method", "account")


class RowError(Exception):
    pass


# ---------------------------------------------------------------------- pembacaan

def read_csv(content):
    """Bytes CSV (UTF-8, boleh BOM; pemisah koma atau titik koma) → list of dict dengan header huruf kecil."""
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252")
    else:
        text = content
    first = text.split("\n", 1)[0]
    delimiter = ";" if first.count(";") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    reader.fieldnames = [(name or "").strip().lower().rstrip("*") for name in reader.fieldnames or []]
    rows = []
    for row in reader:
        clean = {key: (value or "").strip() for key, value in row.items() if key}
        if any(clean.values()):
            rows.append(clean)
    return reader.fieldnames, rows


def number(value, field):
    """'1234.5', '1234,5', '1.234,5' dan '1.500.000' (format Indonesia) → Decimal. Satu titik = desimal."""
    raw = (value or "").replace(" ", "").replace("Rp", "")
    if ("," in raw and "." in raw) or re.fullmatch(r"-?\d{1,3}(\.\d{3}){2,}", raw):
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation as error:
        raise RowError(f"{field}: '{value}' bukan angka") from error


def day(value, field):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise RowError(f"{field}: '{value}' bukan tanggal (pakai YYYY-MM-DD atau DD/MM/YYYY)")


def flag(value, field):
    low = (value or "").lower()
    if low in YES:
        return True
    if low in NO:
        return False
    raise RowError(f"{field}: '{value}' harus Y atau N")


# ---------------------------------------------------------------------- dasar

class Importer:
    key = ""
    label = ""
    columns = ()  # (nama, wajib, contoh)
    note = ""
    stock = False  # saldo stok: file yang sama tidak boleh diimpor dua kali

    def __init__(self, env):
        self.env = env

    def template(self):
        header = ",".join(name + ("*" if required else "") for name, required, _example in self.columns)
        example = ",".join(_quote(example) for _name, _required, example in self.columns)
        return f"{header}\n{example}\n"

    def check(self, header, rows):
        """→ list of (nomor_baris, pesan). Baris 1 = header, data mulai baris 2."""
        errors = []
        missing = [name for name, _req, _ex in self.columns if name not in header]
        if missing:
            return [(1, "Kolom tidak ada: " + ", ".join(missing))]
        if not rows:
            return [(1, "File tidak berisi data")]
        self.prepare(rows)
        for index, row in enumerate(rows, 2):
            for name, required, _example in self.columns:
                if required and not row.get(name):
                    errors.append((index, f"{name} wajib diisi"))
            for check in self.checks(row):
                try:
                    check()
                except RowError as error:
                    errors.append((index, str(error)))
        errors += self.check_file(rows)
        return errors

    def prepare(self, rows):
        pass

    def checks(self, row):
        """Pemeriksaan per baris yang saling lepas, supaya semua masalah satu baris terlihat sekaligus."""
        return [lambda: self.check_row(row)]

    def check_row(self, row):
        pass

    def check_file(self, rows):
        return []

    def apply(self, rows):
        raise NotImplementedError

    # pencarian referensi
    def outlet(self, code):
        outlet = self.env["rasentra.outlet"].search([("code", "=", code)], limit=1)
        if code and not outlet:
            raise RowError(f"kode_outlet '{code}' belum ada; impor outlet.csv dulu")
        return outlet

    def product(self, code, field="kode_produk"):
        product = self.env["product.product"].with_context(active_test=False).search(
            [("default_code", "=", code)], limit=1)
        if code and not product:
            raise RowError(f"{field} '{code}' belum ada; impor produk.csv dulu")
        return product


def _quote(value):
    return f'"{value}"' if "," in value else value


def duplicates(rows, *keys):
    seen, errors = {}, []
    for index, row in enumerate(rows, 2):
        value = tuple(row.get(k, "").lower() for k in keys)
        if all(value) and value in seen:
            errors.append((index, f"{'/'.join(keys)} '{'/'.join(value)}' ganda dengan baris {seen[value]}"))
        seen.setdefault(value, index)
    return errors


# ---------------------------------------------------------------------- entitas

class Region(Importer):
    key, label = "wilayah", "Wilayah"
    columns = (("kode", True, "SLO"), ("nama", True, "Solo"), ("nama_cv", True, "CV Solo Kulina Utama"))
    note = "Satu baris per wilayah. nama_cv = nama perusahaan persis seperti di Odoo."

    def company(self, name):
        company = self.env["res.company"].search([("name", "=ilike", name)], limit=1)
        if name and not company:
            raise RowError(f"nama_cv '{name}' tidak ditemukan di daftar perusahaan")
        return company

    def check_row(self, row):
        self.company(row.get("nama_cv"))

    def check_file(self, rows):
        return duplicates(rows, "kode")

    def apply(self, rows):
        Region = self.env["rasentra.region"]
        for row in rows:
            vals = {"name": row["nama"], "company_id": self.company(row["nama_cv"]).id}
            found = Region.search([("code", "=", row["kode"])], limit=1)
            if found:
                found.write(vals)
            else:
                Region.create({"code": row["kode"], **vals})
        return len(rows)


class Outlet(Importer):
    key, label = "outlet", "Outlet"
    columns = (
        ("kode", True, "SLO-MS"), ("nama", True, "Meatshop & Grill Solo"), ("kode_wilayah", True, "SLO"),
        ("zona_waktu", True, "Asia/Jakarta"), ("retail", False, "Y"), ("restoran", False, "Y"),
        ("cooking_fee", False, "Y"), ("nama_retail", False, "Meatshop Solo"),
        ("nama_restoran", False, "Grill Corner Solo"), ("kode_gudang_akuntansi", False, "WH-SLO-MS"),
        ("jalur_posting", False, "service_layer"),
    )
    note = "jalur_posting: service_layer (SAP B1) atau xml (Accurate / tanpa posting SAP). Lombok: Asia/Makassar."

    def region(self, code):
        region = self.env["rasentra.region"].search([("code", "=", code)], limit=1)
        if code and not region:
            raise RowError(f"kode_wilayah '{code}' belum ada; impor wilayah.csv dulu")
        return region

    def check_row(self, row):
        self.region(row.get("kode_wilayah"))
        if row.get("zona_waktu") and row["zona_waktu"] not in TIMEZONES:
            raise RowError(f"zona_waktu harus salah satu: {', '.join(TIMEZONES)}")
        for name in ("retail", "restoran", "cooking_fee"):
            flag(row.get(name), name)
        if row.get("jalur_posting", "") not in ("", "service_layer", "xml"):
            raise RowError("jalur_posting harus service_layer atau xml")
        if not re.fullmatch(r"[A-Z0-9-]{2,20}", row.get("kode", "")):
            raise RowError("kode outlet hanya huruf besar, angka dan tanda minus (mis. SLO-MS)")

    def check_file(self, rows):
        return duplicates(rows, "kode")

    def apply(self, rows):
        Outlet = self.env["rasentra.outlet"]
        for row in rows:
            region = self.region(row["kode_wilayah"])
            warehouse = self.env["stock.warehouse"].search([("company_id", "=", region.company_id.id)], limit=1)
            vals = {
                "name": row["nama"], "region_id": region.id, "company_id": region.company_id.id,
                "tz": row["zona_waktu"], "has_retail": flag(row.get("retail"), "retail"),
                "has_restaurant": flag(row.get("restoran"), "restoran"),
                "has_cooking_fee": flag(row.get("cooking_fee"), "cooking_fee"),
                "retail_name": row.get("nama_retail") or False, "restaurant_name": row.get("nama_restoran") or False,
                "sap_warehouse_code": row.get("kode_gudang_akuntansi") or False,
                "sap_posting_channel": row.get("jalur_posting") or "service_layer",
            }
            if warehouse:
                vals["warehouse_id"] = warehouse.id
            found = Outlet.search([("code", "=", row["kode"])], limit=1)
            if found:
                found.write(vals)
            else:
                Outlet.create({"code": row["kode"], **vals})
        return len(rows)


class Employee(Importer):
    key, label = "pegawai", "Pegawai"
    columns = (
        ("nama", True, "Budi Santoso"), ("kode_outlet", True, "SLO-MS"), ("peran", True, "cashier"),
        ("pin", True, "1234"), ("login", False, ""), ("limit_approval", False, "0"),
    )
    note = "peran: " + ", ".join(ROLES) + ". PIN 4–6 angka, unik per outlet. login = user Odoo yang sudah ada (opsional)."

    def user(self, login):
        user = self.env["res.users"].search([("login", "=", login)], limit=1)
        if login and not user:
            raise RowError(f"login '{login}' belum ada di Odoo; buat user dulu atau kosongkan")
        return user

    def checks(self, row):
        return [
            lambda: self.check_role(row), lambda: self.check_pin(row), lambda: self.user(row.get("login")),
            lambda: row.get("limit_approval") and number(row["limit_approval"], "limit_approval"),
            lambda: self.check_clash(row),
        ]

    def check_role(self, row):
        if row.get("peran") and row["peran"] not in ROLES:
            raise RowError(f"peran '{row['peran']}' tidak dikenal; pilih: {', '.join(ROLES)}")

    def check_pin(self, row):
        if row.get("pin") and not re.fullmatch(r"\d{4,6}", row["pin"]):
            raise RowError("pin harus 4–6 angka")

    def check_clash(self, row):
        outlet = self.outlet(row.get("kode_outlet"))
        if outlet and row.get("pin"):
            clash = self.env["hr.employee"].search([
                ("rasentra_outlet_id", "=", outlet.id), ("pin", "=", row["pin"]), ("name", "!=", row.get("nama")),
            ], limit=1)
            if clash:
                raise RowError(f"pin sudah dipakai {clash.name} di outlet ini")

    def check_file(self, rows):
        return duplicates(rows, "kode_outlet", "pin") + duplicates(rows, "kode_outlet", "nama")

    def apply(self, rows):
        Employee = self.env["hr.employee"]
        for row in rows:
            outlet = self.outlet(row["kode_outlet"])
            vals = {
                "company_id": outlet.company_id.id, "rasentra_outlet_id": outlet.id, "rasentra_role": row["peran"],
                "pin": row["pin"], "approval_limit": float(number(row.get("limit_approval") or "0", "limit_approval")),
            }
            user = self.user(row.get("login"))
            if user:
                vals["user_id"] = user.id
            found = Employee.search([("name", "=", row["nama"]), ("rasentra_outlet_id", "=", outlet.id)], limit=1)
            if found:
                found.write(vals)
            else:
                Employee.with_company(outlet.company_id).create({"name": row["nama"], **vals})
        return len(rows)


class Product(Importer):
    key, label = "produk", "Produk"
    columns = (
        ("kode", True, "SIRLOIN-AUS"), ("nama", True, "Sirloin Australia"), ("jenis", True, "meat_pack"),
        ("satuan", True, "kg"), ("kategori_pos", False, "Daging ber-Pack ID"), ("barcode", False, ""),
        ("station_dapur", False, ""), ("harga_dasar", False, "650000"),
    )
    note = ("jenis: " + ", ".join(TYPES) + ". satuan: kg, g, pcs, porsi, liter, ml. meat_pack = daging timbang "
            "ber-Pack ID (satuan kg). station_dapur untuk menu: " + ", ".join(STATIONS) + ".")

    def check_row(self, row):
        if row.get("jenis") and row["jenis"] not in TYPES:
            raise RowError(f"jenis '{row['jenis']}' tidak dikenal; pilih: {', '.join(TYPES)}")
        unit = row.get("satuan", "").lower()
        if unit and unit not in UOMS:
            raise RowError(f"satuan '{row['satuan']}' tidak dikenal; pakai: {', '.join(sorted(UOMS))}")
        if row.get("jenis") == "meat_pack" and unit and unit != "kg":
            raise RowError("produk meat_pack harus bersatuan kg")
        if row.get("station_dapur") and row["station_dapur"] not in STATIONS:
            raise RowError(f"station_dapur pilih: {', '.join(STATIONS)}")
        if row.get("harga_dasar"):
            number(row["harga_dasar"], "harga_dasar")
        if row.get("barcode"):
            other = self.env["product.product"].with_context(active_test=False).search(
                [("barcode", "=", row["barcode"]), ("default_code", "!=", row.get("kode"))], limit=1)
            if other:
                raise RowError(f"barcode {row['barcode']} sudah dipakai {other.display_name}")

    def check_file(self, rows):
        return duplicates(rows, "kode") + duplicates(rows, "barcode")

    def category(self, name):
        if not name:
            return self.env["pos.category"]
        Category = self.env["pos.category"]
        return Category.search([("name", "=", name)], limit=1) or Category.create({"name": name})

    def apply(self, rows):
        Product = self.env["product.product"].with_context(active_test=False, tracking_disable=True)
        for row in rows:
            kind, uom = row["jenis"], self.env.ref(UOMS[row["satuan"].lower()])
            vals = {
                "name": row["nama"], "rasentra_type": kind, "uom_id": uom.id, "uom_po_id": uom.id,
                "type": "service" if kind == "service" else "consu",
                "is_storable": kind in ("retail", "meat_pack", "ingredient"),
                "tracking": "lot" if kind == "meat_pack" else "none",
                "to_weight": kind == "meat_pack",
                "available_in_pos": kind in ("retail", "meat_pack", "menu", "service"),
                "barcode": row.get("barcode") or False,
                "kitchen_station": row.get("station_dapur") or False,
            }
            if row.get("harga_dasar"):
                vals["list_price"] = float(number(row["harga_dasar"], "harga_dasar"))
            category = self.category(row.get("kategori_pos"))
            if category:
                vals["pos_categ_ids"] = [(6, 0, category.ids)]
            found = Product.search([("default_code", "=", row["kode"])], limit=1)
            if found:
                found.write(vals)
            else:
                Product.create({"default_code": row["kode"], "taxes_id": [(5, 0, 0)],
                                "supplier_taxes_id": [(5, 0, 0)], **vals})
        return len(rows)


class Price(Importer):
    key, label = "harga", "Harga (versi draft)"
    columns = (
        ("kode_versi", True, "SLO-RETAIL-2027"), ("kode_outlet", False, "SLO-MS"), ("kanal", False, "retail"),
        ("berlaku_mulai", True, "2027-01-01"), ("kode_produk", True, "SIRLOIN-AUS"), ("harga", True, "650000"),
    )
    note = ("Satu baris per produk; baris dengan kode_versi sama menjadi satu versi harga. Kosongkan kode_outlet "
            "untuk semua outlet. Versi masuk sebagai draft dan diterbitkan tim merchandising.")

    def check_row(self, row):
        self.outlet(row.get("kode_outlet"))
        self.product(row.get("kode_produk"))
        if row.get("kanal") and row["kanal"] not in ("retail", "restaurant", "takeaway"):
            raise RowError("kanal harus retail, restaurant atau takeaway")
        if row.get("berlaku_mulai"):
            day(row["berlaku_mulai"], "berlaku_mulai")
        if row.get("harga") and number(row["harga"], "harga") < 0:
            raise RowError("harga tidak boleh negatif")
        if row.get("kode_versi") and self.env["rasentra.price.version"].search_count(
                [("code", "=", row["kode_versi"])]):
            raise RowError(f"kode_versi '{row['kode_versi']}' sudah ada (versi harga tidak bisa diubah); pakai kode baru")

    def check_file(self, rows):
        errors = duplicates(rows, "kode_versi", "kode_produk")
        heads = {}
        for index, row in enumerate(rows, 2):
            head = (row.get("kode_outlet"), row.get("kanal"), row.get("berlaku_mulai"))
            first = heads.setdefault(row.get("kode_versi"), (head, index))
            if first[0] != head:
                errors.append((index, f"kode_outlet/kanal/berlaku_mulai berbeda dengan baris {first[1]} "
                                      "untuk kode_versi yang sama"))
        return errors

    def apply(self, rows):
        groups = defaultdict(list)
        for row in rows:
            groups[row["kode_versi"]].append(row)
        for code, items in groups.items():
            head = items[0]
            self.env["rasentra.price.version"].create({
                "code": code, "outlet_id": self.outlet(head.get("kode_outlet")).id or False,
                "channel": head.get("kanal") or False,
                "effective_from": datetime.combine(day(head["berlaku_mulai"], "berlaku_mulai"), datetime.min.time()),
                "note": "Impor migrasi",
                "item_ids": [(0, 0, {"product_id": self.product(r["kode_produk"]).id,
                                     "unit_price": float(number(r["harga"], "harga"))}) for r in items],
            })
        return len(groups)


class Mapping(Importer):
    key, label = "mapping_akuntansi", "Mapping akuntansi"
    columns = (
        ("company_db", True, "sap_solo"), ("jenis", True, "product"), ("kunci", True, "SIRLOIN-AUS"),
        ("kode_tujuan", True, "FG-SIRLOIN-AUS"), ("kode_pajak", False, ""),
    )
    note = ("jenis: product (kode produk → ItemCode / No. barang), outlet (kode outlet → gudang), customer "
            "(walk_in → CardCode), payment_method (cash, qris, edc_manual → akun), account (waste, count, "
            "production → akun penyesuaian). company_db = database SAP CV (mis. sap_solo) atau kode Accurate.")

    def check_row(self, row):
        kind, key = row.get("jenis"), row.get("kunci")
        if kind and kind not in ENTITY_TYPES:
            raise RowError(f"jenis harus salah satu: {', '.join(ENTITY_TYPES)}")
        if kind == "product":
            self.product(key, "kunci")
        if kind == "outlet":
            self.outlet(key)
        if kind == "account" and key not in ("waste", "count", "production"):
            raise RowError("kunci akun harus waste, count atau production")

    def check_file(self, rows):
        return duplicates(rows, "company_db", "jenis", "kunci")

    def apply(self, rows):
        Mapping = self.env["rasentra.sap.mapping"].with_context(active_test=False)
        for row in rows:
            domain = [("company_db", "=", row["company_db"]), ("entity_type", "=", row["jenis"]),
                      ("entity_key", "=", row["kunci"])]
            vals = {"sap_code": row["kode_tujuan"], "tax_code": row.get("kode_pajak") or False, "active": True}
            found = Mapping.search(domain, limit=1)
            if found:
                found.write(vals)
            else:
                Mapping.create({"company_db": row["company_db"], "entity_type": row["jenis"],
                                "entity_key": row["kunci"], **vals})
        return len(rows)


class PackStock(Importer):
    key, label = "stok_pack", "Saldo awal Pack ID"
    stock = True
    columns = (
        ("kode_pack", True, "PK-SLO-100001"), ("kode_produk", True, "SIRLOIN-AUS"), ("kode_outlet", True, "SLO-MS"),
        ("berat_kg", True, "1,235"), ("harga_label", False, "802750"), ("kedaluwarsa", True, "2027-01-12"),
        ("batch", False, "B270101-SIR"), ("tanggal_produksi", False, "2027-01-01"),
    )
    note = ("Satu baris per kemasan dari opname malam cut-over. Pack masuk berstatus Dikirim; petugas gudang "
            "men-scan terima di Rasentra Inventory (handheld) sehingga stok jual bertambah per pack.")

    def check_row(self, row):
        product = self.product(row.get("kode_produk"))
        if product and product.rasentra_type != "meat_pack":
            raise RowError(f"{product.default_code} bukan produk meat_pack")
        self.outlet(row.get("kode_outlet"))
        if row.get("berat_kg") and number(row["berat_kg"], "berat_kg") <= 0:
            raise RowError("berat_kg harus lebih dari 0")
        if row.get("harga_label"):
            number(row["harga_label"], "harga_label")
        for name in ("kedaluwarsa", "tanggal_produksi"):
            if row.get(name):
                day(row[name], name)
        if row.get("kode_pack") and self.env["stock.lot"].search_count([("name", "=", row["kode_pack"])]):
            raise RowError(f"kode_pack {row['kode_pack']} sudah ada")

    def check_file(self, rows):
        return duplicates(rows, "kode_pack")

    def apply(self, rows):
        Lot = self.env["stock.lot"]
        for row in rows:
            outlet = self.outlet(row["kode_outlet"])
            Lot.create({
                "name": row["kode_pack"], "product_id": self.product(row["kode_produk"]).id,
                "company_id": outlet.company_id.id, "is_rasentra_pack": True,
                "net_weight": float(number(row["berat_kg"], "berat_kg")),
                "label_price": float(number(row.get("harga_label") or "0", "harga_label")),
                "pack_expiry_date": day(row["kedaluwarsa"], "kedaluwarsa"),
                "production_date": day(row["tanggal_produksi"], "tanggal_produksi") if row.get("tanggal_produksi") else False,
                "rasentra_batch_no": row.get("batch") or False, "weigh_source": "saldo awal migrasi",
                "rasentra_outlet_id": outlet.id, "rasentra_location_type": "transit", "pack_status": "shipped",
            })
        return len(rows)


class SkuStock(Importer):
    key, label = "stok_sku", "Saldo awal barang retail"
    stock = True
    location_kind = {"stok": "stock", "karantina": "quarantine", "": "stock"}
    columns = (
        ("kode_outlet", True, "SLO-MS"), ("kode_produk", True, "RT-SALT"), ("qty", True, "24"),
        ("lokasi", False, "stok"),
    )
    note = "Barang berbarcode tanpa Pack ID, hasil opname malam cut-over. lokasi: stok atau karantina."

    def check_row(self, row):
        self.outlet(row.get("kode_outlet"))
        product = self.product(row.get("kode_produk"))
        if product and product.rasentra_type == "meat_pack":
            raise RowError("daging ber-Pack ID diimpor lewat stok_pack.csv")
        if product and not product.is_storable:
            raise RowError(f"{product.default_code} bukan barang berstok")
        if row.get("qty") and number(row["qty"], "qty") <= 0:
            raise RowError("qty harus lebih dari 0")
        if row.get("lokasi", "").lower() not in self.location_kind:
            raise RowError("lokasi harus stok atau karantina")

    def check_file(self, rows):
        return duplicates(rows, "kode_outlet", "kode_produk", "lokasi")

    def target(self, outlet, row):
        return self.env["rasentra.stock.ledger"].location(outlet, self.location_kind[row.get("lokasi", "").lower()])

    def apply(self, rows):
        ledger = self.env["rasentra.stock.ledger"]
        for row in rows:
            outlet = self.outlet(row["kode_outlet"])
            ledger.move(self.product(row["kode_produk"]), number(row["qty"], "qty"),
                        ledger.virtual(outlet.company_id, "inventory"), self.target(outlet, row),
                        f"Saldo awal migrasi {outlet.code}")
        return len(rows)


class KitchenStock(SkuStock):
    key, label = "stok_dapur", "Saldo awal bahan dapur"
    columns = (("kode_outlet", True, "SLO-MS"), ("kode_produk", True, "BH-BUTTER"), ("qty", True, "5"))
    note = "Bahan dan saus di dapur restoran (jenis ingredient), dalam satuan produknya."

    def check_row(self, row):
        super().check_row(row)
        product = self.product(row.get("kode_produk"))
        if product and product.rasentra_type != "ingredient":
            raise RowError(f"{product.default_code} bukan bahan (ingredient)")

    def check_file(self, rows):
        return duplicates(rows, "kode_outlet", "kode_produk")

    def target(self, outlet, row):
        return self.env["rasentra.stock.ledger"].location(outlet, "kitchen")


ORDER = [Region, Outlet, Employee, Product, Price, Mapping, PackStock, SkuStock, KitchenStock]
IMPORTERS = {cls.key: cls for cls in ORDER}
SELECTION = [(cls.key, f"{i}. {cls.label}") for i, cls in enumerate(ORDER, 1)]

