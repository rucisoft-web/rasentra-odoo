import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount, useState } from "@odoo/owl";
import { FloorScreen } from "@pos_restaurant/app/floor_screen/floor_screen";

const REFRESH_MS = 10000;

/** Peta meja tablet: status kunjungan (terisi / minta tagihan) dan status dapur per meja dari server. */
patch(FloorScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.rasentraMap = useState({ tables: {} });
        if (!this.pos.rasentraKitchenEnabled) {
            return;
        }
        let timer = null;
        const refresh = async () => {
            try {
                this.rasentraMap.tables = await this.pos.data.call("pos.session", "rasentra_table_map", [
                    [this.pos.session.id],
                ]);
            } catch {
                // Offline: peta tetap memakai data terakhir.
            }
        };
        onMounted(() => {
            refresh();
            timer = setInterval(refresh, REFRESH_MS);
        });
        onWillUnmount(() => clearInterval(timer));
    },
    rasentraTableInfo(table) {
        return this.rasentraMap?.tables?.[table.id] || null;
    },
});
