import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";

export const COURSES = [
    ["starter", _t("Pembuka")],
    ["main", _t("Utama")],
    ["dessert", _t("Penutup")],
    ["drink", _t("Minuman")],
];

patch(PosStore.prototype, {
    get rasentraKitchenEnabled() {
        return this.rasentraEnabled && this.config.module_pos_restaurant;
    },

    /** Semua kategori menu dianggap kategori dapur agar tombol Kirim ke Dapur muncul tanpa printer. */
    get orderPreparationCategories() {
        const categories = super.orderPreparationCategories;
        if (this.rasentraKitchenEnabled) {
            for (const category of this.models["pos.category"].getAll()) {
                categories.add(category.id);
            }
        }
        return categories;
    },

    /**
     * Kirim ke Dapur: simpan draft ke Rasentra Lokal lalu server membuat tiket delta per station
     * (hanya item baru atau tambahan kuantitas). Printer dapur bawaan tetap mencetak sebagai cadangan.
     */
    async sendOrderInPreparation(order, cancelled = false, course = null) {
        if (this.rasentraKitchenEnabled && order) {
            try {
                await this.syncAllOrders({ orders: [order] });
                const result = await this.data.call("pos.session", "rasentra_kitchen_send", [
                    [this.session.id], order.uuid, course,
                ]);
                if (result?.tickets) {
                    this.notification.add(
                        _t("%s tiket terkirim ke dapur (%s)", result.tickets, result.stations.join(", ")),
                        { type: "success" }
                    );
                }
            } catch (error) {
                this.rasentraAlert(error);
                return;
            }
        }
        return super.sendOrderInPreparation(order, cancelled);
    },

    /** Atur course baris terpilih (pembuka, utama, penutup, minuman). */
    async rasentraSetCourse() {
        const line = this.get_order()?.get_selected_orderline();
        if (!line) {
            return;
        }
        const course = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Course untuk %s", line.get_full_product_name()),
            list: COURSES.map(([id, label]) => ({ id, label, item: id, isSelected: line.rasentra_course === id })),
        });
        if (course) {
            line.rasentra_course = course;
        }
    },

    /** Kirim hanya satu course, mis. tahan hidangan utama sampai pembuka selesai. */
    async rasentraSendCourse() {
        const order = this.get_order();
        if (!order) {
            return;
        }
        const course = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Kirim course ke dapur"),
            list: COURSES.map(([id, label]) => ({ id, label, item: id })),
        });
        if (course) {
            await this.sendOrderInPreparation(order, false, course);
        }
    },
});
