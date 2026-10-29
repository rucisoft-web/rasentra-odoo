#!/usr/bin/env bash
# Pasang semua modul Rasentra di database kosong lalu jalankan tes bertag `rasentra`.
# Pemakaian: scripts/run-tests.sh [opsi odoo tambahan], mis. --db_host=db --db_user=odoo --db_password=odoo
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ODOO_BIN="${ODOO_BIN:-odoo}"
ODOO_ADDONS="${ODOO_ADDONS:-/usr/lib/python3/dist-packages/odoo/addons}"
DB="${TEST_DB:-rasentra_test_$$}"
MODULES="rasentra_core,rasentra_pack_id,rasentra_promo,rasentra_sync_central,rasentra_sync_outlet"
LOG="$(mktemp)"

ADDONS_PATH="$ODOO_ADDONS,$ROOT/addons"
for repo in "$ROOT"/oca/*/; do ADDONS_PATH="$ADDONS_PATH,${repo%/}"; done

"$ODOO_BIN" -d "$DB" -i "$MODULES" --addons-path="$ADDONS_PATH" \
  --test-enable --test-tags rasentra --stop-after-init --without-demo=all \
  --log-level=info "$@" 2>&1 | tee "$LOG"

# Odoo tidak selalu keluar dengan kode gagal ketika tes gagal, jadi hasilnya dibaca dari log.
if grep -qE " (ERROR|CRITICAL) " "$LOG" || ! grep -qE " 0 failed, 0 error\(s\) of [1-9][0-9]* tests" "$LOG"; then
  echo "Tes Rasentra GAGAL" >&2
  exit 1
fi
echo "Tes Rasentra lulus"
