import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { rasentraBridge } from "./bridge";

const APPROVER_ROLES = ["outlet_head", "admin"];
export const PROMO_PRODUCT_CODE = "RASENTRA-PROMO";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        rasentraBridge.store = this;
    },

    get rasentraEnabled() {
        // rasentra.outlet tidak dimuat ke POS, jadi relasinya hanya ada di nilai mentah config.
        return Boolean(this.config.raw?.rasentra_outlet_id);
    },

    rasentraEmployeeId() {
        const cashier = this.get_cashier();
        return this.config.module_pos_hr && cashier ? cashier.id : false;
    },

    rasentraAlert(error) {
        this.dialog.add(AlertDialog, {
            title: _t("Rasentra"),
            body: error?.data?.message || error?.message || String(error),
        });
    },

    /**
     * Scan Pack ID: kunci kemasan di server lalu tambah baris dengan berat dan harga dari server.
     * Mengembalikan false bila kode bukan Pack ID, agar POS memakai pencarian barcode biasa.
     */
    async rasentraScan(code, approval = null) {
        if (!this.rasentraEnabled) {
            return false;
        }
        let order = this.get_order() || this.add_new_order();
        let result;
        try {
            result = await this.data.call("pos.session", "rasentra_scan", [
                [this.session.id], code, order.uuid, this.rasentraEmployeeId(), approval,
            ]);
        } catch (error) {
            this.rasentraAlert(error);
            return true;
        }
        if (!result) {
            return false;
        }
        if (result.kind === "approval_required") {
            const granted = await this.rasentraAskApproval(result.message);
            return granted ? this.rasentraScan(code, granted) : true;
        }
        const line = await this.addLineToCurrentOrder(
            {
                product_id: result.product_id,
                qty: parseFloat(result.quantity),
                price_unit: parseFloat(result.unit_price),
            },
            { merge: false },
            false
        );
        if (line && !line.pack_lot_ids.length) {
            line.setPackLotLines({
                modifiedPackLotLines: {},
                newPackLotLines: [{ lot_name: result.pack_code }],
                setQuantity: false,
            });
        }
        if (line) {
            line.rasentra_label_price = result.label_price ? parseFloat(result.label_price) : false;
        }
        return true;
    },

    async rasentraAskApproval(message) {
        const approvers = (this.models["hr.employee"]?.getAll() || []).filter(
            (employee) =>
                APPROVER_ROLES.includes(employee.rasentra_role) &&
                employee.id !== this.rasentraEmployeeId()
        );
        if (!approvers.length) {
            this.rasentraAlert(_t("Tidak ada kepala outlet yang dapat menyetujui di kasir ini."));
            return false;
        }
        const approver = await makeAwaitable(this.dialog, SelectionPopup, {
            title: message || _t("Butuh persetujuan kepala outlet"),
            list: approvers.map((employee) => ({
                id: employee.id,
                label: employee.name,
                item: employee,
            })),
        });
        if (!approver) {
            return false;
        }
        const pin = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("PIN %s", approver.name),
            formatDisplayedValue: (value) => value.replace(/./g, "•"),
        });
        return pin ? { approver_id: approver.id, pin } : false;
    },

    rasentraPackCode(line) {
        return line.pack_lot_ids?.[0]?.lot_name || false;
    },

    /** Lepas kunci kemasan saat baris dihapus atau order dibuang. */
    rasentraRelease(order, lines, reason) {
        if (!this.rasentraEnabled) {
            return;
        }
        for (const line of lines) {
            const code = this.rasentraPackCode(line);
            if (!code) {
                continue;
            }
            this.data
                .call("pos.session", "rasentra_release", [
                    [this.session.id], code, order.uuid, this.rasentraEmployeeId(), reason,
                ])
                .catch((error) => console.warn("Rasentra: gagal melepas kemasan", code, error));
        }
    },

    removeOrder(order, removeFromServer = true) {
        if (order && !order.finalized) {
            this.rasentraRelease(order, order.lines, "order_void");
        }
        return super.removeOrder(...arguments);
    },

    /**
     * Hitung promo di server dan tulis sebagai baris "Diskon promo" negatif, satu per versi promo.
     * Server menghitung ulang saat finalisasi; selisih ditandai untuk ditinjau.
     */
    async rasentraApplyPromotions(order) {
        for (const line of [...order.lines]) {
            if (line.rasentra_promo_uuid) {
                line.delete();
            }
        }
        const saleLines = order.lines.filter((line) => line.qty > 0);
        if (!saleLines.length) {
            return true;
        }
        const promoProduct = this.models["product.product"].find(
            (product) => product.default_code === PROMO_PRODUCT_CODE
        );
        let result;
        try {
            result = await this.data.call("pos.session", "rasentra_evaluate", [
                [this.session.id],
                saleLines.map((line) => ({
                    uuid: line.uuid,
                    product_id: line.product_id.id,
                    qty: String(line.qty),
                    price_unit: String(line.price_unit),
                })),
            ]);
        } catch (error) {
            this.rasentraAlert(error);
            return false;
        }
        if (result.promotions.length && !promoProduct) {
            this.rasentraAlert(_t("Produk %s belum tersedia di POS.", PROMO_PRODUCT_CODE));
            return false;
        }
        for (const promotion of result.promotions) {
            const line = await this.addLineToOrder(
                { product_id: promoProduct, qty: 1, price_unit: -parseFloat(promotion.amount) },
                order,
                { merge: false },
                false
            );
            line.rasentra_promo_uuid = promotion.uuid;
            line.full_product_name = promotion.name;
        }
        return true;
    },

    async pay() {
        const order = this.get_order();
        if (this.rasentraEnabled && order && !order.lines.some((line) => line.refunded_orderline_id)) {
            if (!(await this.rasentraApplyPromotions(order))) {
                return;
            }
        }
        return super.pay(...arguments);
    },
});
