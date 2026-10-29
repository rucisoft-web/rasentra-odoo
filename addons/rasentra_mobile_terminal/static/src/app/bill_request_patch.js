import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";

/** Cetak tagihan dari tablet juga menandai meja "minta tagihan" agar kasir dan pelayan lain melihatnya. */
patch(ControlButtons.prototype, {
    async clickPrintBill() {
        const order = this.pos.get_order();
        if (this.pos.rasentraKitchenEnabled && order?.table_id) {
            try {
                await this.pos.syncAllOrders({ orders: [order] });
                await this.pos.data.call("pos.session", "rasentra_request_bill", [
                    [this.pos.session.id], order.uuid, this.pos.rasentraEmployeeId(),
                ]);
            } catch (error) {
                console.warn("rasentra_request_bill", error);
            }
        }
        return super.clickPrintBill(...arguments);
    },
});
