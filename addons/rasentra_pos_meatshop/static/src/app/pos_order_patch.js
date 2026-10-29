import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { rasentraBridge } from "./bridge";

patch(PosOrder.prototype, {
    removeOrderline(line) {
        const lines = line.getAllLinesInCombo();
        const removed = super.removeOrderline(...arguments);
        if (removed && !this.finalized) {
            rasentraBridge.store?.rasentraRelease(this, lines, "line_void");
        }
        return removed;
    },
});
