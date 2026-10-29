# Rasentra di Odoo 18 Community

Rasentra untuk Indoguna Group (CV Solo Kulina Utama `sap_solo`, CV Lombok Kulina Utama `sap_lombok`)
dibangun ulang di atas Odoo 18 Community, mengikuti rancangan Rasentra Laravel 13 + MySQL.
Repo ini berisi **tahap 0** (lingkungan, CI) dan **tahap 1** (fondasi: master, Pack ID, audit, sinkron
Central dan Lokal). POS, dapur, inventaris, promo dan integrasi SAP menyusul di tahap berikutnya.

## Isi repo

| Folder | Isi |
| --- | --- |
| `addons/rasentra_core` | Perusahaan dan outlet, wilayah, lokasi, perangkat dan token API, peran petugas, versi harga, approval PIN, audit append-only, profil instalasi |
| `addons/rasentra_pack_id` | Pack ID sebagai `stock.lot`: berat, harga label, kedaluwarsa, status, reservasi dan penjualan dengan kunci baris |
| `addons/rasentra_sync_central` | API `/api/v1/sync` (events, changes, snapshot, ack, heartbeat), inbox event, publikasi master, status sinkron outlet |
| `addons/rasentra_sync_outlet` | Rasentra Lokal: outbox event, pengiriman dengan backoff, tarik publikasi, bootstrap snapshot, heartbeat, konsol sinkron |
| `oca/` | Submodule OCA cabang 18.0: `queue`, `rest-framework`, `web-api`, `server-tools` |
| `config/` | Konfigurasi Odoo untuk profil Central dan Lokal |
| `scripts/run-tests.sh` | Pasang semua modul di database kosong dan jalankan tes |

Semua modul berlisensi LGPL-3 dan hanya memakai Odoo Community serta modul OCA.

## Menjalankan

```sh
git clone --recurse-submodules https://github.com/rucisoft-web/rasentra-odoo.git
cd rasentra-odoo
docker compose --profile central up --build     # http://localhost:8069, database rasentra_central
docker compose --profile lokal up --build       # http://localhost:8070, database rasentra_lokal
```

Saat pertama kali, buat database lalu pasang modul:

```sh
docker compose run --rm central odoo -c /etc/odoo/rasentra/odoo-central.conf -i rasentra_sync_central,rasentra_pack_id --stop-after-init
docker compose run --rm lokal odoo -c /etc/odoo/rasentra/odoo-lokal.conf -i rasentra_sync_outlet,rasentra_pack_id --stop-after-init
```

## Profil Central dan Lokal

Profil ditentukan oleh parameter sistem (Pengaturan > Teknis > Parameter Sistem):

| Parameter | Central | Lokal |
| --- | --- | --- |
| `rasentra.profile` | `central` | `lokal` (bawaan) |
| `rasentra.outlet_code` | - | kode outlet, terisi otomatis saat bootstrap |
| `rasentra.central_url` | - | mis. `https://central.indoguna.co.id` |
| `rasentra.central_token` | - | token perangkat server outlet dari Central |
| `rasentra.device_code` | - | kode perangkat server outlet, dipakai sebagai `source_id` event |

Langkah memasang outlet baru:

1. Di Central: buat outlet dan perangkat ber-app **Server Rasentra Lokal**, lalu tekan **Buat token baru**. Token hanya tampil sekali.
2. Di Lokal: isi `rasentra.central_url`, `rasentra.central_token` dan `rasentra.device_code`.
3. Di Lokal: menu **Rasentra > Sinkron > Sinkron dengan Central**, tekan **Uji koneksi**, lalu **Bootstrap dari snapshot**.
4. Setelah itu cron tiap menit mengantrekan job `queue_job` untuk kirim outbox, tarik publikasi dan heartbeat.

## Kontrak sinkron

Sama dengan Rasentra Laravel:

- `POST /api/v1/sync/events` menerima maksimal 500 event. Hasil per event: `accepted`, `duplicate` (dengan `ack_ref` yang sama), atau `rejected`. `source_id` wajib sama dengan kode perangkat pemilik token, dan checksum adalah SHA-256 dari `json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION)`.
- `GET /api/v1/sync/changes?cursor=` mengembalikan 200 publikasi per halaman dengan `next_cursor` dan `has_more`.
- `GET /api/v1/sync/snapshot` hanya untuk perangkat server Rasentra Lokal karena berisi PIN petugas.
- `POST /api/v1/sync/ack` dan `POST /api/v1/sync/heartbeat` mengisi layar **Status sinkron outlet** di Central.
- Outbox Lokal: backoff `min(900, 5 x 2^percobaan)` detik dengan jitter 50 sampai 100 persen, berhenti (`parked`) setelah 20 percobaan, timeout 15 detik.
- Puller berhenti tepat sebelum publikasi pertama yang gagal diterapkan, lalu mengirim ack.

Event yang dikirim Rasentra Lokal Laravel bisa diterima Central Odoo apa adanya, sehingga outlet bisa
dipindahkan satu per satu. Arah sebaliknya tidak: payload publikasi master Central Odoo memakai format
Odoo (kunci `default_code` produk, `uuid` outlet dan versi harga, `rasentra_uuid` petugas), jadi Rasentra
Lokal Laravel tidak bisa menarik master dari Central Odoo.

## Tes

```sh
scripts/run-tests.sh --db_host=localhost --db_user=odoo --db_password=odoo
```

Atau di dalam container (skrip ikut terpasang lewat volume `./scripts`):

```sh
docker compose run --rm central /mnt/rasentra/scripts/run-tests.sh --db_host=db --db_user=odoo --db_password=odoo
```

CI di `.github/workflows/test.yml`
menjalankan skrip yang sama di image `odoo:18.0` dengan PostgreSQL 16.

## Catatan tahap berikutnya

- `stock_barcodes` (OCA `stock-logistics-barcode`) baru ditambahkan di tahap inventaris karena butuh
  OCA `web` dan `stock-logistics-workflow`.
- Penerimaan Pack ID lewat `stock.move` (barang masuk, transfer) ada di tahap inventaris; tahap 1 baru
  menyediakan reservasi dan penjualan.
- Batas laju API sinkron diserahkan ke nginx di depan Odoo.
- PIN petugas di `hr.employee` disimpan Odoo sebagai teks biasa, berbeda dengan hash di Laravel.
