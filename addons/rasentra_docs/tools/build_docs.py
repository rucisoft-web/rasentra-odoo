"""Bangun docs/index.html: Spesifikasi perangkat lunak + Panduan penggunaan per peran Rasentra Odoo.

Jalankan: python3 addons/rasentra_docs/tools/build_docs.py
Screenshot diambil oleh tools/screenshots.js dari database demo (rasentra_demo_solo + rasentra_demo_lombok)
dan disimpan di docs/img/. Diagram dibuat sebagai SVG inline oleh svg.py.
"""

import os
import sys
from html import escape

sys.path.insert(0, os.path.dirname(__file__))
from svg import Svg, flow  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")


# ---- diagram konsep ------------------------------------------------------------------------

def architecture():
    s = Svg(1040, 640, "Arsitektur Rasentra Odoo 18 Community")
    # SAP dan sistem lama
    s.group(20, 20, 1000, 100, "Sistem ERP & sumber lama", color="#2e2420", fill="#f6f1ea")
    s.box(40, 50, 220, 56, "SAP Business One", "sap_solo · Service Layer", "ext")
    s.box(280, 50, 220, 56, "SAP Business One", "sap_lombok · Service Layer", "ext")
    s.box(560, 50, 200, 56, "File NMEXML", "MSI / MSR sistem lama", "ext")
    s.box(790, 50, 210, 56, "QRIS / EDC", "penyedia pembayaran", "ext")
    # Central
    s.group(20, 150, 1000, 190, "Rasentra Central · Odoo 18 CE (kantor pusat Indoguna)", color="#8b2e1f", fill="#fff8f5")
    s.box(40, 185, 180, 60, "Master & katalog", ["outlet, wilayah, produk,", "harga berversi"], "central")
    s.box(235, 185, 180, 60, "Promo · Resep", ["cooking fee, maker-", "checker, simulasi"], "central")
    s.box(430, 185, 180, 60, "Sinkron Central", ["API /api/v1/sync", "inbox · publikasi"], "central")
    s.box(625, 185, 180, 60, "Proyeksi HQ", ["struk, retur, stok,", "rekonsiliasi harian"], "central")
    s.box(820, 185, 180, 60, "Integrasi SAP", ["posting, mapping,", "pengecualian, XML"], "central")
    s.box(40, 262, 370, 56, "Dashboard · Status Central · Laporan", "pivot/grafik Odoo, audit, monitoring", "plain")
    s.box(430, 262, 570, 56, "Keamanan: grup peran, aturan per perusahaan & outlet, log audit",
          "Spesifikasi & Panduan tersedia sebagai menu untuk semua peran", "plain")
    s.arrow([(910, 185), (910, 140), (150, 140), (150, 106)], "Invoice, pembayaran, stok", label_at=0.5)
    s.arrow([(910, 140), (390, 140), (390, 106)])
    s.arrow([(660, 106), (660, 130), (950, 130), (950, 185)], "impor staging", dashed=True, label_at=0.75)
    # Lokal
    s.group(20, 380, 490, 240, "Rasentra Lokal Solo · Odoo 18 CE di outlet", color="#d9822b", fill="#fffaf3")
    s.group(530, 380, 490, 240, "Rasentra Lokal Lombok (WITA) · Odoo 18 CE", color="#d9822b", fill="#fffaf3")
    for gx, outlet in ((20, "SLO-MS · SLO-RB"), (530, "LOP-MS · LOP-EP")):
        s.box(gx + 20, 415, 215, 56, "POS Meatshop", ["scan Pack ID, promo,", "QRIS/EDC, kas"], "lokal")
        s.box(gx + 255, 415, 215, 56, "POS Restoran", ["meja, modifier, split,", "cooking fee"], "lokal")
        s.box(gx + 20, 484, 140, 56, "Kitchen (KDS)", ["station, bump,", "resep → stok"], "lokal")
        s.box(gx + 172, 484, 140, 56, "Inventory", ["terima, opname,", "waste, karantina"], "lokal")
        s.box(gx + 324, 484, 146, 56, "Outbox · Agen sinkron", ["kirim event,", "tarik publikasi"], "lokal")
        s.box(gx + 20, 553, 450, 50, f"Perangkat outlet {outlet}",
              "PC kasir · tablet pelayan · layar dapur · handheld · timbangan · printer struk/label", "device")
        s.arrow([(gx + 397, 484), (gx + 397, 360), (520, 360), (520, 318)] if gx == 20 else
                [(gx + 397, 484), (gx + 397, 360), (520, 360)], None)
    s.text(300, 356, "HTTPS: event (struk, retur, stok, tutup hari) naik · publikasi master turun · heartbeat",
           size=12, color="#8b2e1f", weight="700")
    s.arrow([(1000, 78), (1010, 78), (1010, 415), (1000, 443)], dashed=True)
    s.arrow([(1010, 300), (1020, 300)], None, dashed=True)
    return s.render()


def module_map():
    s = Svg(1040, 420, "Peta modul Rasentra")
    s.group(20, 20, 1000, 70, "Fondasi", color="#2e2420")
    s.box(40, 40, 230, 40, "rasentra_core", None, "ext")
    s.box(290, 40, 230, 40, "rasentra_pack_id", None, "ext")
    s.box(540, 40, 230, 40, "rasentra_theme", None, "ext")
    s.box(790, 40, 210, 40, "rasentra_docs", None, "ext")
    s.group(20, 110, 1000, 70, "Aturan bisnis (Central menerbitkan, Lokal menerapkan)", color="#8b2e1f")
    for i, name in enumerate(["rasentra_promo", "rasentra_recipe", "rasentra_cooking_fee", "rasentra_stock_count"]):
        s.box(40 + i * 245, 130, 225, 40, name, None, "central")
    s.group(20, 200, 1000, 70, "Kanal outlet (Rasentra Lokal)", color="#d9822b")
    for i, name in enumerate(["rasentra_pos_meatshop", "rasentra_payment_qris", "rasentra_cash_control",
                              "rasentra_kitchen", "rasentra_mobile_terminal"]):
        s.box(40 + i * 196, 220, 184, 40, name, None, "lokal")
    s.group(20, 290, 1000, 110, "Sinkron & integrasi", color="#5b7f3a")
    for i, name in enumerate(["rasentra_sync_outlet", "rasentra_sync_central", "rasentra_reconcile", "rasentra_sap_b1"]):
        s.box(40 + i * 245, 310, 225, 36, name, None, "device")
    for i, name in enumerate(["rasentra_sap_xml", "rasentra_monitor", "rasentra_dashboard", "rasentra_demo_*"]):
        s.box(40 + i * 245, 354, 225, 36, name, None, "device")
    return s.render()


def pack_states():
    s = Svg(1040, 330, "Siklus hidup Pack ID")
    nodes = {
        "available": (30, 40, "available", "tersedia di pusat"), "allocated": (230, 40, "allocated", "dialokasikan"),
        "shipped": (430, 40, "shipped", "dikirim ke outlet"), "received": (630, 40, "received", "diterima outlet"),
        "reserved": (830, 40, "reserved", "di keranjang kasir"), "sold": (830, 170, "sold", "terjual (struk)"),
        "hold": (630, 170, "hold", "ditahan kepala outlet"), "damaged": (430, 170, "damaged", "rusak / tolak terima"),
        "quarantine": (230, 170, "quarantine", "retur pelanggan"), "wasted": (30, 170, "wasted", "dibuang (waste)"),
    }
    kinds = {"sold": "done", "damaged": "warn", "wasted": "warn", "quarantine": "warn", "hold": "decision",
             "received": "lokal", "reserved": "lokal"}
    for key, (x, y, title, sub) in nodes.items():
        s.box(x, y, 170, 58, title, sub, kinds.get(key, "plain"))

    def right(a, b, label=None):
        ax, ay, *_ = nodes[a]
        bx, by, *_ = nodes[b]
        s.arrow([(ax + 170, ay + 29), (bx, by + 29)], label)

    right("available", "allocated", "alokasi")
    right("allocated", "shipped", "kirim")
    right("shipped", "received", "scan terima")
    right("received", "reserved", "scan kasir")
    s.arrow([(915, 98), (915, 170)], "bayar", label_dy=4)
    s.arrow([(870, 98), (870, 120), (760, 120), (760, 98)], "batal/hapus baris", label_dy=-4)
    s.arrow([(715, 98), (715, 170)], "tahan", label_dy=4)
    s.arrow([(500, 98), (500, 170)], "tolak", label_dy=4)
    s.arrow([(830, 199), (800, 199)], None)
    s.arrow([(915, 228), (915, 280), (315, 280), (315, 228)], "retur dengan alasan", label_at=0.5)
    s.arrow([(230, 199), (200, 199)], None)
    s.arrow([(470, 228), (470, 254), (115, 254), (115, 228)], "waste + approval kepala outlet", label_dy=4)
    s.text(30, 316, "Satu Pack ID hanya bisa berada di satu keranjang (dikunci di server). Setiap perubahan status "
                    "tercatat di Riwayat pack dan log audit.", size=12)
    return s.render()


def sync_sequence():
    s = Svg(1040, 380, "Sinkronisasi Central dan Lokal")
    cols = [(110, "POS / KDS / Inventory"), (370, "Rasentra Lokal"), (640, "Rasentra Central"), (900, "SAP B1")]
    for x, label in cols:
        s.box(x - 95, 16, 190, 40, label, None, "lokal" if "Lokal" in label or "POS" in label else
              ("central" if "Central" in label else "ext"))
        s.arrow([(x, 56), (x, 360)], None, dashed=True, color="#cbbba8")
    steps = [
        (110, 370, 86, "transaksi selesai → outbox (idempoten)"),
        (370, 640, 126, "POST /sync/events: struk, retur, stok, tutup hari"),
        (640, 370, 166, "ack per event (diterima / duplikat / menunggu induk)"),
        (640, 900, 206, "posting Invoice + IncomingPayment (cron 5 menit)"),
        (900, 640, 246, "DocEntry / gagal → pengecualian & retry"),
        (370, 640, 286, "GET /sync/changes?cursor: harga, promo, resep, tarif"),
        (640, 370, 316, "publikasi berversi → diterapkan + ack"),
        (370, 640, 346, "heartbeat 1 menit: antrean outbox, jam, hari buka"),
    ]
    for x1, x2, y, label in steps:
        s.arrow([(x1, y), (x2, y)], label, label_dy=-5)
    return s.render()


def maker_checker():
    s = Svg(1040, 220, "Maker-checker harga, promo, resep dan tarif")
    s.box(20, 60, 170, 64, "Draft", "dibuat Merchandising", "plain")
    s.box(230, 60, 170, 64, "Simulasi", "keranjang contoh, hasil diskon", "decision")
    s.box(440, 60, 170, 64, "Disetujui", "oleh orang lain (checker)", "central")
    s.box(650, 60, 170, 64, "Terbit", "dipublikasi ke outlet target", "done")
    s.box(860, 60, 160, 64, "Ack outlet", "diterima / diterapkan", "lokal")
    s.arrow([(190, 92), (230, 92)])
    s.arrow([(400, 92), (440, 92)], "tidak boleh pembuat")
    s.arrow([(610, 92), (650, 92)])
    s.arrow([(820, 92), (860, 92)])
    s.box(650, 150, 170, 54, "Diganti versi baru", "versi lama tetap terbaca", "plain")
    s.arrow([(735, 124), (735, 150)])
    s.text(20, 30, "Versi yang sudah terbit tidak bisa diubah. Perubahan = versi baru, sehingga histori struk selalu "
                   "merujuk aturan yang berlaku saat itu.", size=12)
    return s.render()


def cooking_paths():
    s = Svg(1040, 260, "Dua jalur cooking fee")
    s.box(20, 30, 220, 64, "Pack di keranjang restoran", "belum dibayar", "lokal")
    s.box(290, 30, 220, 64, "Masak pack ini", "metode, kematangan, saus, alergi", "plain")
    s.box(560, 30, 220, 64, "Tarif aturan berlaku", "per kg / per porsi / tier, min.", "central")
    s.box(830, 30, 190, 64, "Struk: daging + jasa", "dua baris terpisah", "done")
    s.box(20, 150, 220, 64, "Struk retail lunas", "daging dibeli di meatshop", "lokal")
    s.box(290, 150, 220, 64, "Masak dari struk", "nomor struk + Pack ID", "plain")
    s.box(560, 150, 220, 64, "Hak layanan sekali pakai", "pakai ulang ditolak + audit", "warn")
    s.box(830, 150, 190, 64, "Struk restoran", "hanya jasa & tambahan", "done")
    for y in (62, 182):
        s.arrow([(240, y), (290, y)])
        s.arrow([(510, y), (560, y)])
        s.arrow([(780, y), (830, y)])
    s.text(20, 245, "Batal sebelum dimasak: jasa batal, pack tetap milik pelanggan. Batal setelah dimasak: PIN kepala "
                    "outlet, daging dicatat waste dan tidak kembali dijual.", size=12)
    return s.render()


def kitchen_flow():
    return flow("Alur dapur", [
        ("Pelayan kirim ke dapur", "POS: tombol Order (hanya item baru / tambahan)", "lokal"),
        ("Tiket per station", "grill, hot, cold, bar · nomor antrean", "plain"),
        ("Chef mulai masak", "KDS: bump pertama → resep memotong stok dapur", "central"),
        ("Siap", "KDS: bump kedua → status meja 'Siap'", "done"),
        ("Expeditor sajikan", "KDS expeditor · tablet pelayan", "plain"),
        ("Analisis waktu saji", "rata-rata, p50, p90 per station", "plain"),
    ], per_row=3)


def sap_flow():
    s = Svg(1040, 250, "Posting SAP dan jalur XML")
    s.box(20, 40, 200, 64, "Struk HQ (proyeksi)", "rasentra.hq.order", "central")
    s.box(270, 40, 200, 64, "Cek mapping", "produk, gudang, metode bayar", "decision")
    s.box(520, 20, 230, 50, "Invoice + IncomingPayment", "U_POS_SRC mencegah ganda", "done")
    s.box(520, 90, 230, 50, "Pengecualian integrasi", "mapping kosong → Finance", "warn")
    s.box(800, 40, 220, 64, "Status SAP struk", "posted / failed / parsial", "plain")
    s.arrow([(220, 72), (270, 72)])
    s.arrow([(470, 60), (520, 45)], "lengkap")
    s.arrow([(470, 84), (520, 115)], "kurang", label_dy=14)
    s.arrow([(750, 45), (800, 62)])
    s.arrow([(750, 115), (800, 86)])
    s.box(20, 170, 200, 56, "Outlet jalur XML", "posting_channel = xml", "ext")
    s.box(270, 170, 200, 56, "Impor NMEXML", "MSI → MSR, tanpa DTD", "plain")
    s.box(520, 170, 230, 56, "Staging dokumen sumber", "dedup nomor, selisih pembulatan", "lokal")
    s.arrow([(220, 198), (270, 198)])
    s.arrow([(470, 198), (520, 198)])
    s.text(780, 195, "Satu kejadian hanya diposting", size=12)
    s.text(780, 212, "lewat satu jalur.", size=12)
    return s.render()


# ---- alur per peran -----------------------------------------------------------------------

ROLES = [
    {
        "id": "admin", "title": "Admin pusat", "login": "admin.pusat",
        "goal": "Menyiapkan struktur grup (CV, wilayah, outlet, perangkat, pengguna) dan memantau kesehatan seluruh "
                "sistem.",
        "flow": [
            ("Siapkan CV & mapping SAP", "Pengaturan → Perusahaan, SAP → Mapping", "central"),
            ("Buat wilayah & outlet", "Rasentra → Master → Outlet (zona waktu WIB/WITA)", "central"),
            ("Daftarkan perangkat Lokal", "Master → Perangkat → buat token", "plain"),
            ("Karyawan & pengguna per peran", "Karyawan (peran, outlet, PIN, limit approval)", "plain"),
            ("Konfigurasi POS outlet", "Point of Sale → Konfigurasi (outlet, kanal)", "lokal"),
            ("Pantau dashboard & status", "Rasentra → Dashboard, Monitoring → Status Central", "done"),
        ],
        "explain": [
            "Rasentra memisahkan dua CV (Solo dan Lombok) sebagai perusahaan Odoo dengan database SAP masing-masing. "
            "Semua data outlet dibatasi per perusahaan; admin pusat melihat keduanya.",
            "Setiap outlet punya satu server Rasentra Lokal yang terdaftar sebagai perangkat. Token perangkat hanya "
            "ditampilkan sekali saat dibuat dan dipakai agen sinkron di outlet.",
            "Peran ditentukan oleh grup pengguna (backend) dan peran karyawan (POS dan approval). PIN karyawan dipakai "
            "untuk masuk POS dan menyetujui void, diskon manual, hold pack dan batal setelah masak.",
        ],
        "shots": [("a1_dashboard", "Dashboard grup: penjualan hari ini, tren 7 hari, per CV dan per outlet."),
                  ("a2_outlets", "Daftar outlet dengan wilayah, zona waktu dan perusahaan."),
                  ("a3_outlet", "Formulir outlet: kanal retail/restoran, cooking fee, gudang dan jalur posting SAP."),
                  ("a4_devices", "Perangkat Rasentra Lokal per outlet.")],
    },
    {
        "id": "merch", "title": "Merchandising", "login": "merch",
        "goal": "Mengelola harga, promo, resep dan tarif cooking fee dengan prinsip maker-checker.",
        "flow": [
            ("Buat versi harga", "Katalog & harga → Versi harga (outlet/kanal)", "plain"),
            ("Terbitkan harga", "tombol Terbitkan → publikasi ke outlet", "central"),
            ("Rancang promo", "Katalog & harga → Promo (jenis, aturan, target)", "plain"),
            ("Simulasikan keranjang", "Simulasi: diskon dan alokasi per baris", "decision"),
            ("Disetujui orang lain", "Admin/merch lain menerbitkan (bukan pembuat)", "central"),
            ("Pantau penerimaan outlet", "status ack per outlet target", "done"),
            ("Kelola resep berversi", "Dapur → Resep: menu, saus, modifier", "plain"),
            ("Tarif cooking fee", "Katalog & harga → Aturan cooking fee", "plain"),
        ],
        "explain": [
            "Harga, promo, resep dan tarif disimpan sebagai versi. Versi yang terbit tidak diubah; perubahan dibuat "
            "sebagai versi baru agar struk lama tetap merujuk aturan yang berlaku saat itu.",
            "Promo dihitung oleh mesin promo Rasentra (port dari Laravel) yang sama di Central dan POS, termasuk mode "
            "exclusive/stackable/best benefit, batas diskon dan penanggung (internal, pemasok, bank, platform).",
            "Resep menu memakai baris modifier (mis. extra butter, saus lada hitam, tanpa bawang putih) sehingga stok "
            "dapur terpotong sesuai pilihan tamu.",
        ],
        "shots": [("m1_price", "Versi harga terbit untuk kanal retail."),
                  ("m2_promo", "Promo draft menunggu simulasi dan persetujuan orang lain."),
                  ("m3_recipe", "Resep Sirloin steak dengan baris modifier."),
                  ("m4_cooking_rule", "Aturan cooking fee per kg dengan tier dan resep jasa.")],
    },
    {
        "id": "finance", "title": "Finance", "login": "finance",
        "goal": "Memastikan setiap struk sampai ke SAP tepat satu kali, menangani pengecualian, dan mencocokkan "
                "penjualan harian.",
        "flow": [
            ("Buka Status Central", "Monitoring → Status Central", "central"),
            ("Periksa antrean SAP", "SAP → Dokumen SAP (gagal, parsial, perlu dicek)", "plain"),
            ("Selesaikan pengecualian", "SAP → Pengecualian (mis. mapping kosong)", "warn"),
            ("Lengkapi mapping & retry", "SAP → Mapping, lalu Posting SAP sekarang", "decision"),
            ("Rekonsiliasi harian", "Monitoring → Rekonsiliasi (cocok/selisih)", "plain"),
            ("Impor XML sistem lama", "SAP → XML NMEXML → Unggah XML", "plain"),
            ("Laporan penjualan & stok", "Laporan → Struk HQ, baris, diskon, stok", "done"),
        ],
        "explain": [
            "Struk dari Lokal masuk lewat inbox sinkron dan diproyeksikan menjadi Struk HQ. Cron memposting ke SAP B1 "
            "sebagai Invoice + IncomingPayment; retur sebagai CreditNote + pembayaran keluar.",
            "Bila mapping produk, gudang atau metode bayar belum ada, struk tidak diposting dan muncul sebagai "
            "pengecualian. Setelah mapping dilengkapi, posting ulang memeriksa SAP lebih dulu sehingga tidak ganda.",
            "Rekonsiliasi membandingkan tutup hari Lokal dengan struk yang diterima Central: cocok, menunggu, atau "
            "selisih dengan daftar nomor struk yang hilang/lebih.",
        ],
        "shots": [("f1_status", "Status Central: heartbeat outlet, antrean, koneksi SAP per CV."),
                  ("f2_sap", "Dokumen SAP per status."),
                  ("f3_exceptions", "Pengecualian integrasi: mapping SAP Short rib Lombok sengaja dikosongkan di demo."),
                  ("f4_report", "Laporan struk HQ (pivot) per outlet dan tanggal."),
                  ("f5_xml", "Hasil impor NMEXML: jumlah dokumen, duplikat dan selisih pembulatan.")],
    },
    {
        "id": "head", "title": "Kepala outlet", "login": "solo.kepala",
        "goal": "Menjalankan hari operasional outlet dan memberi persetujuan sesuai limit.",
        "flow": [
            ("Buka kasir & hari", "POS: Kontrol pembukaan (kas awal)", "lokal"),
            ("Setujui dengan PIN", "void, diskon manual, hold pack, batal masak", "decision"),
            ("Pantau stok & kedaluwarsa", "Inventory → Handheld: cek", "plain"),
            ("Setujui opname", "Inventory → Sesi opname → Setujui", "central"),
            ("Tutup sesi kasir", "POS: tutup kas, selisih dicatat", "plain"),
            ("Tutup hari", "Sinkron Lokal: tutup hari → Central", "done"),
        ],
        "explain": [
            "Persetujuan selalu memakai PIN kepala outlet (atau admin) dan dibatasi limit approval. Setiap approval "
            "tercatat di log audit beserta alasan.",
            "Opname dilakukan dua putaran: produk yang selisih dihitung ulang oleh orang berbeda; penghitung tidak "
            "boleh menyetujui hitungannya sendiri.",
        ],
        "shots": [("h1_count", "Sesi opname dengan progres dan putaran kedua."),
                  ("h2_adjustments", "Penyesuaian stok (waste, opname, produksi) dengan nomor dokumen.")],
    },
    {
        "id": "cashier", "title": "Kasir meatshop", "login": "solo.kasir",
        "goal": "Menjual daging ber-Pack ID dengan harga dan promo yang benar, lalu menerima pembayaran.",
        "flow": [
            ("Masuk POS dengan PIN", "POS: Buka Kasir → PIN karyawan", "lokal"),
            ("Scan Pack ID", "pack dikunci di server untuk keranjang ini", "central"),
            ("Promo otomatis", "mesin promo menghitung diskon per baris", "plain"),
            ("Pembayaran", "Tunai, QRIS, EDC; QRIS menunggu konfirmasi", "plain"),
            ("Struk & sinkron", "outbox → Central → SAP", "done"),
            ("Retur", "alasan wajib, pack ke karantina", "warn"),
        ],
        "explain": [
            "Daging tidak dijual dengan memilih produk lalu mengetik berat: kasir men-scan label Pack ID sehingga berat, "
            "harga dan kedaluwarsa diambil dari pack. Pack yang sama tidak bisa masuk dua keranjang.",
            "Barang retail biasa (garam, saus botol) tetap bisa dipilih dari layar produk atau di-scan barcode-nya.",
        ],
        "shots": [("k1_login", "Layar masuk POS dengan PIN karyawan."),
                  ("k2_cart", "Keranjang dengan dua Pack ID hasil scan dan satu barang retail."),
                  ("k3_payment", "Layar pembayaran: Tunai, QRIS, EDC.")],
    },
    {
        "id": "waiter", "title": "Pelayan restoran", "login": "solo.pelayan",
        "goal": "Melayani meja dari tablet: pesanan dengan modifier, kirim ke dapur, pantau status dan minta tagihan.",
        "flow": [
            ("Pilih meja di denah", "POS restoran: peta meja + status dapur", "lokal"),
            ("Catat pesanan & modifier", "kematangan, saus, tambahan", "plain"),
            ("Kirim ke dapur", "tombol Order: hanya item baru/tambahan", "central"),
            ("Pantau status", "badge meja: Masak, Siap, Belum kirim", "plain"),
            ("Pindah / gabung meja", "transfer meja = gabung kunjungan", "plain"),
            ("Minta tagihan & bayar", "Tagihan → status meja 'Tagihan'", "done"),
        ],
        "explain": [
            "Setiap kedatangan tamu membuka kunjungan meja dengan token baru, sehingga pesanan tidak pernah masuk ke "
            "tamu sebelumnya setelah meja dibayar dan dibuka lagi.",
            "Badge pada denah meja diperbarui tiap 10 detik dari server: jumlah item sedang dimasak, siap diantar, "
            "item belum dikirim dan meja yang sudah minta tagihan.",
        ],
        "shots": [("w1_floor", "Denah meja Grill Corner Solo dengan badge status dapur."),
                  ("w2_order", "Pesanan meja dengan modifier steak sebelum dikirim ke dapur.")],
    },
    {
        "id": "chef", "title": "Chef / dapur", "login": "solo.dapur",
        "goal": "Memasak sesuai tiket per station, memotong stok sesuai resep, dan mencatat produksi serta susut.",
        "flow": [
            ("Buka layar dapur", "Rasentra → Dapur → Layar dapur (KDS)", "lokal"),
            ("Mulai masak", "bump pertama: resep memotong stok dapur", "central"),
            ("Siap", "bump kedua: pelayan melihat 'Siap'", "done"),
            ("Batal diminta", "konfirmasi batal; setelah masak = waste", "warn"),
            ("Produksi saus/kaldu", "Produksi batch: hasil aktual & susut", "plain"),
            ("Analisis waktu saji", "KDS → Analisis", "plain"),
        ],
        "explain": [
            "Konsumsi stok terjadi saat item mulai dimasak (bukan saat dipesan), memakai versi resep yang aktif dan "
            "modifier pilihan tamu. Histori konsumsi menyimpan versi resep yang dipakai.",
            "Produksi batch mencatat bahan masuk dan hasil timbang aktual. Susut di atas toleransi (2%) wajib diberi "
            "alasan dari daftar.",
        ],
        "shots": [("d1_kds", "Layar dapur station grill dengan tiket dari meja."),
                  ("d2_production", "Form produksi potong & porsi dengan pratinjau susut.")],
    },
    {
        "id": "warehouse", "title": "Petugas gudang & opname", "login": "solo.gudang",
        "goal": "Menerima Pack ID kiriman pusat, menjaga stok layak jual, dan melakukan opname.",
        "flow": [
            ("Scan terima pack", "Inventory → Handheld: Terima", "lokal"),
            ("Tolak bila rusak", "masuk karantina, tidak menambah stok jual", "warn"),
            ("Cek kedaluwarsa", "Handheld: Cek / daftar hampir kedaluwarsa", "plain"),
            ("Waste dengan approval", "Handheld: Waste + PIN kepala outlet", "decision"),
            ("Opname per lokasi", "Buka sesi opname → scan lokasi & pack", "plain"),
            ("Kirim untuk disetujui", "kepala outlet menyetujui, stok disesuaikan", "done"),
        ],
        "explain": [
            "Pack dikirim pusat berstatus 'shipped'. Scan terima memindahkan stok dari transit ke lokasi stok outlet; "
            "penolakan memindahkannya ke karantina sehingga tidak bisa dijual.",
            "Semua penyesuaian (waste, opname, produksi, release) menjadi dokumen bernomor yang dikirim ke Central dan "
            "diposting ke SAP sebagai InventoryGenExits/Entries.",
        ],
        "shots": [("g1_handheld", "Layar handheld: mode terima, cek, opname, waste, release, hold."),
                  ("g2_packs", "Daftar Pack ID outlet dengan status dan kedaluwarsa.")],
    },
]

LOGINS = [
    ("admin.pusat", "Admin pusat (kedua CV)", "-"),
    ("merch", "Merchandising", "-"),
    ("finance", "Finance", "-"),
    ("solo.kepala / lombok.kepala", "Kepala outlet Meatshop", "1111"),
    ("solo.kasir / lombok.kasir", "Kasir meatshop", "1222"),
    ("solo.pelayan / lombok.pelayan", "Pelayan grill/restoran", "1333"),
    ("solo.dapur / lombok.dapur", "Chef / dapur", "1444"),
    ("solo.gudang / lombok.gudang", "Petugas gudang & opname", "1555"),
]

MODULES = [
    ("rasentra_core", "Perusahaan (CV), wilayah, outlet, perangkat, peran karyawan, harga berversi, ledger stok, audit, approval PIN."),
    ("rasentra_pack_id", "Pack ID di atas stock.lot: status, berat, label, kedaluwarsa, riwayat, penguncian per keranjang."),
    ("rasentra_promo", "Mesin promo (port Laravel), versi promo, simulasi, target wilayah/outlet, ack outlet."),
    ("rasentra_pos_meatshop", "POS retail: scan Pack ID, promo, validasi harga di server, outbox struk & retur."),
    ("rasentra_payment_qris / rasentra_cash_control", "QRIS dan EDC terintegrasi (simulasi), kontrol kas, tutup sesi."),
    ("rasentra_recipe", "Resep berversi (menu, prep virtual, prep berstok), modifier, uji siklus, maker-checker."),
    ("rasentra_cooking_fee", "Tarif jasa masak berversi, cooking job per Pack ID, hak layanan dari struk retail."),
    ("rasentra_stock_count", "Terima, cek, waste, karantina, release, opname dua putaran, dokumen penyesuaian stok."),
    ("rasentra_kitchen", "KDS station & expeditor, tiket delta, konsumsi resep, split bill, produksi batch."),
    ("rasentra_mobile_terminal", "Kunjungan meja bertoken, peta meja dengan status dapur, minta tagihan, pindah/gabung."),
    ("rasentra_sync_outlet / rasentra_sync_central", "Outbox, agen sinkron, API /api/v1/sync (OCA fastapi), inbox, publikasi, heartbeat."),
    ("rasentra_reconcile", "Proyeksi HQ (struk, retur, stok) dan rekonsiliasi tutup hari."),
    ("rasentra_sap_b1", "Posting Service Layer per CV, mapping, pengecualian, mode simulasi, cek kesehatan."),
    ("rasentra_sap_xml", "Impor NMEXML MSI/MSR aman ke staging, dedup, selisih pembulatan, jalur posting."),
    ("rasentra_monitor / rasentra_dashboard", "Status Central dan dashboard grup."),
    ("rasentra_theme / rasentra_docs", "Tema ringan food specialist; menu Spesifikasi & Panduan."),
    ("rasentra_demo, rasentra_demo_solo, rasentra_demo_lombok", "Data demo grup, CV Solo dan CV Lombok (terpisah)."),
]

TESTS = [
    ("U01", "Dua Pack ID → struk Rp650.000, 3,250 kg ke outbox"), ("U02", "Pack sama di dua kasir: satu ditolak"),
    ("U05", "Promo hanya di outlet target"), ("U07", "Kirim ke dapur hanya delta"),
    ("U08", "Split bill memindahkan item KDS"), ("U09", "Konsumsi resep 10 porsi"),
    ("U10", "Produksi saus berstok"), ("U12", "Neraca produksi dan susut"),
    ("U14", "Event berulang tanpa duplikasi"), ("U16", "Posting sebagian, retry pembayaran saja"),
    ("U25–U30", "Cooking fee: dua jalur, tarif, hak layanan, batal sebelum/sesudah masak"),
    ("U32–U38", "XML: 49 invoice/182 baris/49 pembayaran, Rp18.811.355, selisih Rp0,40, XXE ditolak, jalur posting"),
]


# ---- HTML -----------------------------------------------------------------------------------

def shot(name, caption):
    path = os.path.join(DOCS, "img", f"{name}.png")
    if not os.path.exists(path):
        return f'<figure class="shot missing"><div>Screenshot {escape(name)} belum dibuat</div>' \
               f'<figcaption>{escape(caption)}</figcaption></figure>'
    return f'<figure class="shot"><a href="img/{name}.png" target="_blank"><img src="img/{name}.png" ' \
           f'alt="{escape(caption)}" loading="lazy"/></a><figcaption>{escape(caption)}</figcaption></figure>'


def section(anchor, title, body, level=2):
    return f'<section id="{anchor}"><h{level}>{escape(title)}</h{level}>{body}</section>'


def table(headers, rows):
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def figure(svg, caption):
    return f'<figure class="diagram-wrap">{svg}<figcaption>{escape(caption)}</figcaption></figure>'


def role_section(role):
    steps = "".join(f"<li><b>{escape(name)}</b> — {escape(screen)}</li>" for name, screen, *_k in role["flow"])
    explain = "".join(f"<p>{escape(p)}</p>" for p in role["explain"])
    shots = "".join(shot(n, c) for n, c in role["shots"])
    body = (
        f'<p class="lead">{escape(role["goal"])} <span class="login">Login demo: <code>{escape(role["login"])}</code></span></p>'
        + figure(flow(f"Alur {role['title']}", role["flow"], per_row=4 if len(role["flow"]) > 6 else 3),
                 f"Diagram alur {role['title'].lower()}")
        + "<h4>Penjelasan alur</h4>" + explain
        + "<h4>Cara memakai Rasentra dalam alur ini</h4><ol class='steps'>" + steps + "</ol>"
        + '<h4>Tampilan</h4><div class="shots">' + shots + "</div>"
    )
    return section(f"peran-{role['id']}", role["title"], body, level=3)


CSS = """
:root{--ox:#8b2e1f;--saf:#d9822b;--herb:#5b7f3a;--cream:#faf6ef;--char:#2e2420;--muted:#6b5b53;--line:#e6d9c7}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--char);background:var(--cream);line-height:1.55}
.layout{display:grid;grid-template-columns:270px 1fr;min-height:100vh}
nav{position:sticky;top:0;height:100vh;overflow:auto;background:#fff;border-right:1px solid var(--line);padding:20px 16px}
nav .brand{display:flex;align-items:center;gap:10px;margin-bottom:18px}nav .brand img{height:38px}
nav a{display:block;color:var(--char);text-decoration:none;padding:5px 8px;border-radius:8px;font-size:14px}
nav a:hover{background:var(--cream);color:var(--ox)}nav .sub{padding-left:20px;font-size:13px;color:var(--muted)}
nav h6{margin:16px 8px 6px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--saf)}
main{padding:28px 40px 80px;max-width:1180px}
h1{font-family:Georgia,"Times New Roman",serif;font-size:34px;margin:0 0 6px}
h2{font-family:Georgia,"Times New Roman",serif;font-size:26px;border-bottom:3px solid var(--saf);padding-bottom:6px;margin-top:48px}
h3{font-size:21px;color:var(--ox);margin-top:40px}h4{margin:22px 0 8px}
.lead{font-size:16px}.login{display:inline-block;margin-left:6px;font-size:13px;color:var(--muted)}
code{background:#f1e6d6;padding:1px 6px;border-radius:5px;font-size:.92em}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;margin:12px 0;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:#f6eee2}
.diagram-wrap{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px;margin:16px 0}
.diagram{width:100%;height:auto;display:block}
figcaption{font-size:13px;color:var(--muted);margin-top:8px}
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}
.shot{margin:0;background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px}
.shot img{width:100%;border-radius:8px;border:1px solid var(--line);display:block}
.shot.missing div{padding:40px;text-align:center;color:var(--muted);background:var(--cream);border-radius:8px}
ol.steps li{margin:4px 0}.cover{background:#fff;border:1px solid var(--line);border-radius:16px;padding:24px 28px;
border-top:6px solid var(--ox)}.cover p{margin:6px 0}.pill{display:inline-block;background:#f1e6d6;border-radius:999px;
padding:2px 10px;font-size:12px;margin-right:6px}
@media (max-width:900px){.layout{grid-template-columns:1fr}nav{position:static;height:auto}main{padding:20px 16px}}
@media print{nav{display:none}.layout{display:block}}
"""


def build():
    spec = []
    spec.append(section("arsitektur", "1. Gambar arsitektur Rasentra Odoo",
                        figure(architecture(), "Rasentra Central di kantor pusat, Rasentra Lokal di tiap outlet, SAP B1 per CV. "
                               "Semua komponen Odoo 18 Community + OCA (fastapi, queue_job).")
                        + "<p>Rasentra dibangun ulang di atas <b>Odoo 18 Community</b> tanpa modul Enterprise. Central "
                          "menyimpan master, aturan dan proyeksi data HQ, serta satu-satunya pihak yang berbicara dengan "
                          "SAP. Setiap outlet menjalankan Rasentra Lokal sehingga penjualan, dapur dan inventory tetap "
                          "berjalan walau internet putus; data disinkronkan lewat kontrak API yang sama dengan versi "
                          "Laravel.</p>"))
    spec.append(section("ruang-lingkup", "2. Ruang lingkup dan prinsip", table(
        ["Aspek", "Ketentuan"],
        [("Perusahaan", "CV Solo Kulina Utama (sap_solo) dan CV Lombok Kulina Utama (sap_lombok), data terpisah per perusahaan."),
         ("Outlet", "Meatshop dengan grill corner dan restoran (R&B Solo, El Primo Lombok). Lombok memakai WITA."),
         ("Platform", "Odoo 18 Community + OCA; tanpa Enterprise, tanpa layanan IAP."),
         ("Offline", "Lokal tetap melayani saat koneksi ke Central putus; outbox mengirim ulang saat tersambung."),
         ("Idempoten", "Setiap event punya UUID; event berulang tidak membuat data ganda di Central maupun SAP."),
         ("Audit", "Approval, perubahan status pack, posting SAP dan impor XML tercatat dengan pelaku dan alasan.")])))
    spec.append(section("peta-modul", "3. Peta modul", figure(module_map(), "Modul Rasentra dan lapisannya")
                        + table(["Modul", "Tanggung jawab"], MODULES)))
    concepts = (
        "<h3>4.1 Pack ID</h3>" + figure(pack_states(), "Status Pack ID dari pusat sampai terjual, rusak atau dibuang")
        + "<p>Pack ID adalah label kemasan daging hasil timbang pusat. Berat, harga label, batch dan kedaluwarsa "
          "melekat pada pack, sehingga kasir tidak mengetik berat dan stok dapat dilacak per kemasan.</p>"
        + "<h3>4.2 Sinkronisasi Central–Lokal</h3>" + figure(sync_sequence(), "Urutan pesan sinkron")
        + "<p>Transaksi di outlet selalu ditulis ke outbox dalam transaksi database yang sama, lalu dikirim agen "
          "sinkron. Central membalas ack per event. Arah sebaliknya, master (harga, promo, resep, tarif) diterbitkan "
          "sebagai publikasi berversi yang ditarik Lokal memakai kursor.</p>"
        + "<h3>4.3 Maker-checker dan versi</h3>" + figure(maker_checker(), "Versi aturan dan persetujuan")
        + "<h3>4.4 Cooking fee</h3>" + figure(cooking_paths(), "Jasa masak dari pack di keranjang atau dari struk retail")
        + "<h3>4.5 Dapur</h3>" + figure(kitchen_flow(), "Dari pesanan ke tiket station, konsumsi resep dan penyajian")
        + "<h3>4.6 SAP dan XML</h3>" + figure(sap_flow(), "Posting Service Layer dan staging NMEXML")
    )
    spec.append(section("konsep", "4. Konsep inti", concepts))
    spec.append(section("peran", "5. Peran dan hak akses", table(
        ["Peran", "Grup Odoo", "Akses utama"],
        [("Admin pusat", "Rasentra / Admin pusat", "Semua menu Central, perusahaan, pengguna, perangkat"),
         ("Merchandising", "Rasentra / Merchandising", "Dashboard, produk & harga, promo, resep & cooking fee, laporan"),
         ("Finance", "Rasentra / Finance", "Dashboard, Status Central, SAP, rekonsiliasi, XML, laporan, audit"),
         ("Kepala outlet", "Rasentra / Kepala outlet + POS Manager", "Approval PIN, opname, tutup sesi dan hari"),
         ("Kasir / pelayan", "POS User + karyawan pos_hr", "Penjualan, pembayaran, meja; void/refund hanya mengajukan"),
         ("Chef / dapur", "Rasentra / Dapur", "Layar dapur, resep (baca), produksi batch"),
         ("Gudang", "Rasentra / Petugas gudang", "Handheld terima/cek/waste, opname"),
         ("Semua peran", "Pengguna internal", "Menu Spesifikasi & Panduan")])))
    spec.append(section("integrasi", "6. Integrasi", table(
        ["Antarmuka", "Arah", "Isi"],
        [("/api/v1/sync/events", "Lokal → Central", "order.finalized, order.returned, stock.adjusted, day.closed, cash"),
         ("/api/v1/sync/changes", "Central → Lokal", "publikasi berversi: harga, promo, resep, cooking fee, karyawan"),
         ("/api/v1/sync/ack, /heartbeat", "Lokal → Central", "status penerapan, antrean outbox, selisih jam, hari buka"),
         ("SAP B1 Service Layer", "Central → SAP", "Invoices, IncomingPayments, CreditNotes, InventoryGenExits/Entries"),
         ("NMEXML MSI/MSR", "File → Central", "staging dokumen sumber; jalur posting per outlet = xml | service_layer")])))
    spec.append(section("nonfungsional", "7. Keamanan dan kebutuhan non-fungsional", table(
        ["Kebutuhan", "Implementasi"],
        [("Keamanan data", "Aturan perusahaan dan outlet; token perangkat di-hash; kredensial SAP hanya di Central."),
         ("XML aman", "Tanpa DTD/entity, tanpa jaringan, maks. 20 MB dan 500.000 elemen."),
         ("Zona waktu", "Tanggal bisnis per outlet (WIB Solo, WITA Lombok)."),
         ("Kinerja", "Scan pack dan finalisasi struk di server Lokal; Central diproses batch dan cron."),
         ("Ringan", "Tema hanya warna dan SVG kecil; tanpa font web atau pustaka tambahan.")])))
    spec.append(section("pengujian", "8. Pengujian", table(["Kode", "Skenario"], TESTS)
                        + "<p>Semua modul diuji dengan <code>odoo.tests</code> (TransactionCase, HttpCase dan tour POS/KDS). "
                          "Skrip <code>scripts/run-tests.sh</code> menjalankan seluruh uji di database baru.</p>"))
    spec.append(section("demo", "9. Instalasi dan data demo",
                        "<p>Pasang <code>rasentra_demo_solo</code> dan/atau <code>rasentra_demo_lombok</code>. Keduanya "
                        "memasang <code>rasentra_demo</code> (katalog, resep, pengguna pusat) beserta semua modul Rasentra. "
                        "Kata sandi semua pengguna demo: <code>rasentra</code>.</p>"
                        + table(["Login", "Peran", "PIN POS"], LOGINS)))
    spec.append(section("migrasi", "10. Catatan migrasi dari Laravel", table(
        ["Hal", "Catatan"],
        [("Kontrak API", "Endpoint dan format event /api/v1/sync tetap, sehingga Lokal Laravel dan Lokal Odoo bisa hidup berdampingan selama migrasi."),
         ("Urutan outlet", "Migrasikan satu outlet per waktu: pasang Lokal Odoo, terbitkan snapshot master, uji paralel satu hari, lalu pindahkan perangkat."),
         ("Master", "Produk, harga, promo, resep dan mapping SAP dimuat di Central lalu diterbitkan; Lokal tidak diisi manual."),
         ("Pack ID", "Pack berstatus received/available dipindah bersama berat dan kedaluwarsa; pack terjual cukup sebagai histori di Central."),
         ("SAP", "Aktifkan posting_channel per outlet sebelum XML dan Service Layer dipakai bersamaan, agar satu kejadian tidak diposting dua kali."),
         ("Uji terima", "Jalankan U01–U38 di database baru dan uji gangguan (putus jaringan, proses dihentikan).")])))

    guide = ["<p class='lead'>Setiap peran memiliki diagram alur, penjelasan, langkah memakai Rasentra dalam alur "
             "tersebut dan screenshot dari database demo.</p>"]
    guide += [role_section(r) for r in ROLES]

    nav = ['<div class="brand"><img src="img/logo.svg" alt="Rasentra"/></div>',
           "<h6>Spesifikasi</h6>",
           '<a href="#spesifikasi">Pendahuluan</a>', '<a href="#arsitektur">1. Arsitektur</a>',
           '<a href="#ruang-lingkup">2. Ruang lingkup</a>', '<a href="#peta-modul">3. Peta modul</a>',
           '<a href="#konsep">4. Konsep inti</a>', '<a href="#peran">5. Peran & hak akses</a>',
           '<a href="#integrasi">6. Integrasi</a>', '<a href="#nonfungsional">7. Non-fungsional</a>',
           '<a href="#pengujian">8. Pengujian</a>', '<a href="#demo">9. Instalasi & demo</a>',
           '<a href="#migrasi">10. Migrasi</a>', "<h6>Panduan per peran</h6>",
           '<a href="#panduan">Pengantar</a>']
    nav += [f'<a class="sub" href="#peran-{r["id"]}">{escape(r["title"])}</a>' for r in ROLES]

    html = f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Rasentra · Spesifikasi & Panduan</title><style>{CSS}</style></head>
<body><div class="layout"><nav>{''.join(nav)}</nav><main>
<section id="spesifikasi" class="cover"><h1>Spesifikasi Perangkat Lunak Rasentra Odoo</h1>
<p><span class="pill">Odoo 18 Community</span><span class="pill">Indoguna Group</span><span class="pill">CV Solo &amp; CV Lombok</span></p>
<p>Rasentra adalah sistem operasional meatshop dan restoran Indoguna: penjualan daging ber-Pack ID, restoran dengan dapur
digital, inventory outlet, dan integrasi ke SAP Business One. Dokumen ini dimulai dengan gambar arsitektur, dilanjutkan
konsep inti dan panduan penggunaan per peran.</p></section>
{''.join(spec)}
<h2 id="panduan">Panduan penggunaan per peran</h2>
{''.join(guide)}
<p style="margin-top:60px;color:var(--muted);font-size:13px">Dibangun dari rasentra_docs/tools/build_docs.py.</p>
</main></div></body></html>"""
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as handle:
        handle.write(html)
    return os.path.join(DOCS, "index.html")


if __name__ == "__main__":
    print(build())
