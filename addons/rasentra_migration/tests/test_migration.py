import base64
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.rasentra_core.tests.common import RasentraCase

from ..models.importers import IMPORTERS, ORDER


@tagged("post_install", "-at_install", "rasentra")
class TestMigration(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.name = "CV Solo Kulina Utama"
        cls.wave = cls.env["rasentra.migration.wave"].create({
            "name": "Gelombang 1 Solo", "legacy": "raptor_sap", "cutover_date": "2027-02-01",
            "outlet_ids": [(6, 0, cls.outlet.ids)],
        })

    def batch(self, entity, text):
        return self.env["rasentra.migration.batch"].create({
            "wave_id": self.wave.id, "entity": entity, "file_name": f"{entity}.csv",
            "file": base64.b64encode(text.encode()),
        })

    def imported(self, entity, text):
        batch = self.batch(entity, text)
        batch.action_import()
        self.assertEqual(batch.state, "imported", batch.error_html)
        return batch

    def test_wave_steps_follow_cutover_and_legacy(self):
        steps = self.wave.step_ids
        self.assertEqual(len(steps), 11)
        first, golive = steps[0], steps.filtered(lambda s: s.code == "golive")
        self.assertEqual((first.when, first.due_date), ("H−45", date(2026, 12, 18)))
        self.assertEqual(golive.due_date, date(2027, 2, 1))
        self.assertIn("SAP", steps.filtered(lambda s: s.code == "export").instructions)
        accurate = self.wave.create({"name": "Gelombang 2", "legacy": "rene_accurate", "cutover_date": "2027-03-01"})
        self.assertIn("Accurate", accurate.step_ids.filtered(lambda s: s.code == "export").instructions)
        steps.filtered(lambda s: s.code in ("codes", "cutover")).action_done()
        self.assertEqual(self.wave.state, "cutover")
        self.assertAlmostEqual(self.wave.progress, 200 / 11)
        with self.assertRaises(UserError):
            first.action_done()

    def test_templates_cover_every_column(self):
        for cls in ORDER:
            header = cls(self.env).template().splitlines()[0]
            self.assertEqual(len(header.split(",")), len(cls.columns), cls.key)
        self.assertEqual(list(IMPORTERS), ["wilayah", "outlet", "pegawai", "produk", "harga", "mapping_akuntansi",
                                           "stok_pack", "stok_sku", "stok_dapur"])

    def test_full_import_chain(self):
        self.imported("wilayah", "kode,nama,nama_cv\nJOG,Jogja,CV Solo Kulina Utama\n")
        self.imported("outlet", "kode;nama;kode_wilayah;zona_waktu;retail;restoran;cooking_fee;nama_retail;"
                                "nama_restoran;kode_gudang_akuntansi;jalur_posting\n"
                                "JOG-MS;Meatshop Jogja;JOG;Asia/Jakarta;Y;N;N;Meatshop Jogja;;GD-JOG;xml\n")
        outlet = self.env["rasentra.outlet"].search([("code", "=", "JOG-MS")])
        self.assertEqual((outlet.sap_posting_channel, outlet.has_restaurant), ("xml", False))
        self.imported("pegawai", "nama,kode_outlet,peran,pin,login,limit_approval\n"
                                 "Sri Kasir,JOG-MS,cashier,2468,,\nAgus Kepala,JOG-MS,outlet_head,1357,,\"1.500.000\"\n")
        head = self.env["hr.employee"].search([("name", "=", "Agus Kepala")])
        self.assertEqual((head.rasentra_outlet_id, head.approval_limit), (outlet, 1500000))
        self.imported("produk", "kode,nama,jenis,satuan,kategori_pos,barcode,station_dapur,harga_dasar\n"
                                "TBONE-AUS,T-Bone Australia,meat_pack,kg,Daging,,,720000\n"
                                "RT-PEPPER,Lada hitam 100 g,retail,pcs,Bumbu,8991234500011,,32500\n")
        tbone = self.env["product.product"].search([("default_code", "=", "TBONE-AUS")])
        self.assertEqual((tbone.tracking, tbone.uom_id, tbone.list_price), ("lot", self.kg, 720000))
        self.imported("harga", "kode_versi,kode_outlet,kanal,berlaku_mulai,kode_produk,harga\n"
                               "JOG-RETAIL-2027,JOG-MS,retail,01/02/2027,TBONE-AUS,735000\n"
                               "JOG-RETAIL-2027,JOG-MS,retail,01/02/2027,RT-PEPPER,33000\n")
        version = self.env["rasentra.price.version"].search([("code", "=", "JOG-RETAIL-2027")])
        self.assertEqual((version.state, len(version.item_ids)), ("draft", 2))
        self.imported("mapping_akuntansi", "company_db,jenis,kunci,kode_tujuan,kode_pajak\n"
                                           "acc_jog,product,TBONE-AUS,BRG-0101,\nacc_jog,outlet,JOG-MS,GD-JOG,\n")
        self.assertEqual(self.env["rasentra.sap.mapping"].search_count([("company_db", "=", "acc_jog")]), 2)
        self.imported("stok_pack", "kode_pack,kode_produk,kode_outlet,berat_kg,harga_label,kedaluwarsa,batch,"
                                   "tanggal_produksi\nPK-JOG-000001,TBONE-AUS,JOG-MS,\"1,235\",907725,2027-02-12,,\n")
        pack = self.env["stock.lot"].search([("name", "=", "PK-JOG-000001")])
        self.assertEqual((pack.pack_status, pack.net_weight), ("shipped", 1.235))
        self.env["rasentra.inventory"].receive(outlet, pack.name, head)
        self.assertEqual(pack.pack_status, "received")
        sku = "kode_outlet,kode_produk,qty,lokasi\nJOG-MS,RT-PEPPER,24,stok\nJOG-MS,RT-PEPPER,2,karantina\n"
        self.imported("stok_sku", sku)
        ledger = self.env["rasentra.stock.ledger"]
        pepper = self.env["product.product"].search([("default_code", "=", "RT-PEPPER")])
        self.assertEqual(ledger.balance(pepper, ledger.location(outlet, "stock")), 24)
        self.assertEqual(ledger.balance(pepper, ledger.location(outlet, "quarantine")), 2)
        again = self.batch("stok_sku", sku)
        with self.assertRaises(UserError):
            again.action_import()
        self.assertEqual(ledger.balance(pepper, ledger.location(outlet, "stock")), 24, "stok tidak dobel")

    def test_errors_block_the_whole_file(self):
        batch = self.batch("pegawai", "nama,kode_outlet,peran,pin,login,limit_approval\n"
                                      "A,SLO-MS,cashier,1111,,\nB,XXX,cashier,12,,\nC,SLO-MS,boss,5555,,abc\n"
                                      "D,SLO-MS,waiter,7777,,\nE,SLO-MS,waiter,7777,,\n")
        batch.action_import()
        self.assertEqual(batch.state, "rejected")
        html = batch.error_html
        for expected in ("pin sudah dipakai Kasir Solo", "kode_outlet 'XXX' belum ada", "pin harus 4–6 angka",
                         "peran 'boss'", "limit_approval: 'abc' bukan angka", "ganda dengan baris 5"):
            self.assertIn(expected, html)
        self.assertFalse(self.env["hr.employee"].search([("name", "in", ["A", "D", "E"])]), "tidak ada yang ditulis")
        missing = self.batch("produk", "kode,nama\nX,Y\n")
        missing.action_check()
        self.assertIn("Kolom tidak ada", missing.error_html)

    def test_imported_batch_is_immutable(self):
        batch = self.imported("wilayah", "kode,nama,nama_cv\nSBY,Surabaya,CV Solo Kulina Utama\n")
        with self.assertRaises(UserError):
            batch.write({"file": base64.b64encode(b"kode,nama,nama_cv\n")})
        with self.assertRaises(UserError):
            batch.unlink()
