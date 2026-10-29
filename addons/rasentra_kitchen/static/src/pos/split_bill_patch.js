import { patch } from "@web/core/utils/patch";
import { SplitBillScreen } from "@pos_restaurant/app/split_bill_screen/split_bill_screen";

/**
 * Split bill: baris yang sudah dikirim ke dapur pindah ke order baru beserta item KDS-nya,
 * tidak dianggap void dan tidak dikirim ulang.
 */
patch(SplitBillScreen.prototype, {
    async preSplitOrder(originalOrder, newOrder) {
        await super.preSplitOrder(...arguments);
        if (!this.pos.rasentraKitchenEnabled) {
            return;
        }
        this._rasentraSplit = originalOrder.lines
            .filter((line) => this.qtyTracker[line.uuid])
            .map((line) => ({ from_line_uuid: line.uuid, qty: this.qtyTracker[line.uuid] }));
        await this.pos.data
            .call("pos.session", "rasentra_kitchen_split_begin", [[this.pos.session.id], originalOrder.uuid])
            .catch(() => {});
    },

    async postSplitOrder(originalOrder, newOrder) {
        await super.postSplitOrder(...arguments);
        if (!this._rasentraSplit) {
            return;
        }
        const moves = this._rasentraSplit.map((move, index) => ({
            ...move,
            to_line_uuid: newOrder.lines[index]?.uuid,
        }));
        this._rasentraSplit = null;
        await this.pos.data
            .call("pos.session", "rasentra_kitchen_split_done", [
                [this.pos.session.id], originalOrder.uuid, newOrder.uuid, moves,
            ])
            .catch((error) => this.pos.rasentraAlert(error));
    },
});
