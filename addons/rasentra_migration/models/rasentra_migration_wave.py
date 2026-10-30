from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

LEGACY = [
    ("raptor_sap", "Raptor + SAP B1"),
    ("rene_accurate", "Rene POS + Accurate"),
]

# (kode, hari relatif ke hari H, judul, petunjuk umum, petunjuk Raptor+SAP, petunjuk Rene+Accurate)
STEPS = [
    ("codes", -45, "Tetapkan kode",
     "Sepakati kode outlet (mis. SLO-MS), kode produk dan daftar peran. Bekukan pembuatan barang baru di sistem "
     "lama kecuali lewat tim merchandising.",
     "Putuskan apakah ItemCode SAP dipakai apa adanya atau dibuat kode baru dengan ItemCode sebagai mapping.",
     "No. barang Accurate menjadi kode tujuan di mapping akuntansi; kode produk Rasentra seragam dengan cabang lain."),
    ("export", -40, "Ekspor master dari sistem lama",
     "Ekspor daftar barang, gudang, akun, pelanggan, harga, barcode dan promo yang masih berjalan.",
     "SAP B1: Item Master Data, Warehouses, Chart of Accounts, Business Partners. Raptor: master item & harga.",
     "Accurate: daftar barang, gudang, akun, pelanggan. Rene POS: master produk & harga."),
    ("clean", -35, "Isi template dan bersihkan data",
     "Unduh template di menu Migrasi > Impor data. Hapus barang mati, gabungkan duplikat, samakan satuan (kg, pcs), "
     "lengkapi barcode.", "", ""),
    ("import_test", -30, "Impor ke database uji",
     "Impor berurutan: wilayah, outlet, pegawai, produk, harga, mapping akuntansi. Perbaiki di file, bukan di "
     "Rasentra, lalu impor ulang sampai semua baris lolos pemeriksaan.", "", ""),
    ("parallel", -21, "Uji coba paralel 1 hari",
     "Kasir mencoba transaksi nyata di database uji. Bandingkan harga, promo dan struk dengan POS lama.",
     "Uji posting ke SAP tes: 1 penjualan, 1 retur, 1 waste, 1 opname, tanpa pengecualian terbuka.",
     "Unggah MSI/MSR Accurate satu bulan terakhir di menu SAP > XML NMEXML untuk pembanding."),
    ("signoff", -14, "Tanda tangan master data",
     "Finance, merchandising dan kepala outlet menandatangani daftar barang, harga, promo dan pegawai.", "", ""),
    ("devices", -7, "Siapkan perangkat dan pelatihan",
     "Pasang server Rasentra Lokal di outlet, cetak label Pack ID untuk stok yang belum berlabel, latih tiap peran "
     "memakai menu Spesifikasi & Panduan.", "", ""),
    ("cutover", -1, "Cut-over setelah tutup toko",
     "Tutup hari di POS lama, cetak laporan penjualan terakhir, opname fisik penuh, lalu impor saldo awal "
     "(stok Pack ID, stok SKU, stok dapur). Pack yang diimpor discan terima di layar handheld.",
     "Matikan integrasi Raptor ke SAP malam ini supaya penjualan hari H tidak terposting dua kali.",
     "Bukukan selisih opname di Accurate sebelum ditutup."),
    ("golive", 0, "Hari H: buka dengan Rasentra",
     "Hitung kas awal laci di Kontrol pembukaan POS. POS lama tetap terpasang hanya untuk dibaca.", "", ""),
    ("reconcile", 7, "Rekonsiliasi harian minggu pertama",
     "Setiap pagi cek menu Status Central dan Rekonsiliasi tutup hari.",
     "Cocokkan dengan dokumen di SAP > Antrean SAP; selesaikan Pengecualian integrasi.",
     "Bukukan penjualan harian Rasentra ke Accurate dari laporan Penjualan outlet."),
    ("close", 30, "Tutup bulan pertama",
     "POS lama boleh dimatikan setelah bulan pertama ditutup dan diaudit.", "", ""),
]


class RasentraMigrationWave(models.Model):
    _name = "rasentra.migration.wave"
    _description = "Gelombang migrasi (cut-over per cabang)"
    _inherit = ["mail.thread"]
    _order = "cutover_date, id"

    name = fields.Char(string="Nama gelombang", required=True, tracking=True)
    legacy = fields.Selection(LEGACY, string="Sistem lama", required=True, tracking=True)
    company_id = fields.Many2one("res.company", string="Perusahaan (CV)", required=True,
                                 default=lambda self: self.env.company)
    outlet_ids = fields.Many2many("rasentra.outlet", string="Outlet")
    cutover_date = fields.Date(string="Hari H (go-live)", required=True, tracking=True)
    step_ids = fields.One2many("rasentra.migration.step", "wave_id", string="Langkah")
    batch_ids = fields.One2many("rasentra.migration.batch", "wave_id", string="Impor data")
    progress = fields.Float(string="Progres (%)", compute="_compute_progress", store=True)
    state = fields.Selection(
        [("plan", "Persiapan"), ("cutover", "Cut-over"), ("live", "Berjalan"), ("closed", "Selesai")],
        string="Status", compute="_compute_progress", store=True,
    )
    note = fields.Text(string="Catatan")

    @api.depends("step_ids.done", "step_ids.code")
    def _compute_progress(self):
        for wave in self:
            steps = wave.step_ids
            wave.progress = 100.0 * len(steps.filtered("done")) / len(steps) if steps else 0.0
            done = set(steps.filtered("done").mapped("code"))
            if steps and len(done) == len(steps):
                wave.state = "closed"
            elif "golive" in done:
                wave.state = "live"
            elif "cutover" in done:
                wave.state = "cutover"
            else:
                wave.state = "plan"

    @api.model_create_multi
    def create(self, vals_list):
        waves = super().create(vals_list)
        for wave in waves:
            wave._generate_steps()
        return waves

    def _generate_steps(self):
        self.ensure_one()
        hint = 4 if self.legacy == "raptor_sap" else 5
        self.env["rasentra.migration.step"].create([
            {"wave_id": self.id, "sequence": i, "code": step[0], "offset_days": step[1], "name": step[2],
             "instructions": "\n".join(filter(None, (step[3], step[hint])))}
            for i, step in enumerate(STEPS, 1)
        ])


class RasentraMigrationStep(models.Model):
    _name = "rasentra.migration.step"
    _description = "Langkah migrasi"
    _order = "wave_id, sequence"

    wave_id = fields.Many2one("rasentra.migration.wave", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer()
    code = fields.Char(required=True, readonly=True)
    name = fields.Char(string="Langkah", required=True)
    offset_days = fields.Integer(string="Hari relatif H", readonly=True)
    when = fields.Char(string="Kapan", compute="_compute_due", store=True)
    due_date = fields.Date(string="Tenggat", compute="_compute_due", store=True)
    instructions = fields.Text(string="Petunjuk")
    done = fields.Boolean(string="Selesai", readonly=True)
    done_by_id = fields.Many2one("res.users", string="Diselesaikan oleh", readonly=True)
    done_at = fields.Datetime(string="Waktu selesai", readonly=True)
    note = fields.Char(string="Catatan")
    overdue = fields.Boolean(compute="_compute_overdue")

    @api.depends("wave_id.cutover_date", "offset_days")
    def _compute_due(self):
        for step in self:
            date = step.wave_id.cutover_date
            step.due_date = date + timedelta(days=step.offset_days) if date else False
            sign = "+" if step.offset_days > 0 else ("−" if step.offset_days < 0 else "")
            step.when = f"H{sign}{abs(step.offset_days)}" if step.offset_days else "H"

    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for step in self:
            step.overdue = bool(not step.done and step.due_date and step.due_date < today)

    def action_done(self):
        if self.filtered("done"):
            raise UserError(_("Langkah ini sudah selesai."))
        self.write({"done": True, "done_by_id": self.env.uid, "done_at": fields.Datetime.now()})
        for step in self:
            step.wave_id.message_post(body=_("Langkah selesai: %s", step.name))

    def action_reopen(self):
        self.write({"done": False, "done_by_id": False, "done_at": False})
        for step in self:
            step.wave_id.message_post(body=_("Langkah dibuka lagi: %s", step.name))
