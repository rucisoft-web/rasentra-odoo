import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { TextInputPopup } from "@point_of_sale/app/utils/input_popups/text_input_popup";
import { rasentraBridge } from "@rasentra_pos_meatshop/app/bridge";

const METHODS = [
    ["grill", _t("Grill")],
    ["pan_sear", _t("Pan sear")],
    ["fry", _t("Goreng")],
    ["steam", _t("Kukus")],
    ["bbq", _t("Bakar")],
];
const DONENESS = [
    ["rare", "Rare"],
    ["medium_rare", "Medium rare"],
    ["medium", "Medium"],
    ["medium_well", "Medium well"],
    ["well_done", "Well done"],
];

async function choose(dialog, title, options) {
    return makeAwaitable(dialog, SelectionPopup, {
        title,
        list: options.map(([id, label]) => ({ id, label, item: id })),
    });
}

patch(PosStore.prototype, {
    rasentraPromoEligible(line) {
        return !line.rasentra_cooking_job_uuid && super.rasentraPromoEligible(line);
    },

    /** Instruksi masak: metode, kematangan, porsi, catatan saus/alergi. */
    async rasentraCookingInstructions() {
        const method = await choose(this.dialog, _t("Metode masak"), METHODS);
        if (!method) {
            return false;
        }
        const doneness = await choose(this.dialog, _t("Kematangan"), DONENESS);
        const portions = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Jumlah porsi"),
            startingValue: "1",
        });
        const note = await makeAwaitable(this.dialog, TextInputPopup, {
            title: _t("Saus / alergi (boleh kosong)"),
            placeholder: _t("Contoh: saus lada hitam; alergi kacang"),
        });
        const [sauce, allergy] = (note || "").split(";").map((part) => part.trim());
        return {
            method,
            doneness: doneness || false,
            portions: parseInt(portions || "1") || 1,
            sauce: sauce || false,
            allergy_note: allergy || false,
        };
    },

    async rasentraAddCookingLine(order, result) {
        const product = this.models["product.product"].get(result.service_product_id);
        if (!product) {
            this.rasentraAlert(_t("Produk jasa masak belum tersedia di POS ini."));
            return false;
        }
        const line = await this.addLineToOrder(
            { product_id: product, qty: 1, price_unit: parseFloat(result.fee) },
            order,
            { merge: false },
            false
        );
        line.rasentra_cooking_job_uuid = result.job_uuid;
        line.full_product_name = result.label;
        line.rasentra_cooking_pack = result.pack_code;
        line.setNote(`Pack ${result.pack_code}`);
        return line;
    },

    /** Masak Pack ID yang dipilih di keranjang (daging belum dibayar). */
    async rasentraCookSelectedPack() {
        const order = this.get_order();
        const packLine = order?.get_selected_orderline();
        const packCode = packLine && this.rasentraPackCode(packLine);
        if (!packCode) {
            this.rasentraAlert(_t("Pilih baris Pack ID daging yang akan dimasak."));
            return;
        }
        const instructions = await this.rasentraCookingInstructions();
        if (!instructions) {
            return;
        }
        try {
            const result = await this.data.call("pos.session", "rasentra_cooking_request", [
                [this.session.id], order.uuid, packCode, instructions, this.rasentraEmployeeId(),
            ]);
            await this.rasentraAddCookingLine(order, result);
        } catch (error) {
            this.rasentraAlert(error);
        }
    },

    /** Masak daging yang sudah dibayar di kasir retail: scan struk dan Pack ID asal, tagih jasa saja. */
    async rasentraCookFromReceipt() {
        const order = this.get_order() || this.add_new_order();
        const docNo = await makeAwaitable(this.dialog, TextInputPopup, {
            title: _t("Nomor struk retail"),
            placeholder: "SLO-MS-261028-00001",
        });
        if (!docNo) {
            return;
        }
        const packCode = await makeAwaitable(this.dialog, TextInputPopup, {
            title: _t("Scan Pack ID pada struk"),
        });
        if (!packCode) {
            return;
        }
        const instructions = await this.rasentraCookingInstructions();
        if (!instructions) {
            return;
        }
        try {
            const result = await this.data.call("pos.session", "rasentra_cooking_from_receipt", [
                [this.session.id], order.uuid, docNo.trim(), packCode.trim(), instructions,
                this.rasentraEmployeeId(),
            ]);
            if (result.kind === "blocked") {
                this.rasentraAlert(result.message);
                return;
            }
            await this.rasentraAddCookingLine(order, result);
        } catch (error) {
            this.rasentraAlert(error);
        }
    },

    /** Baris jasa dihapus: batalkan job. Setelah dimasak butuh alasan dan PIN kepala outlet. */
    async rasentraCancelCooking(order, line) {
        let reason = _t("Void kasir");
        let approval = null;
        for (;;) {
            let result;
            try {
                result = await this.data.call("pos.session", "rasentra_cooking_cancel", [
                    [this.session.id], line.rasentra_cooking_job_uuid, reason, this.rasentraEmployeeId(), approval,
                ]);
            } catch (error) {
                this.rasentraAlert(error);
                return;
            }
            if (result.kind !== "approval_required") {
                if (result.remove_pack) {
                    const packLine = order.lines.find((l) => this.rasentraPackCode(l) === result.pack_code);
                    if (packLine) {
                        order.removeOrderline(packLine);
                    }
                    this.rasentraAlert(_t("Daging sudah dimasak: Pack %s dicatat sebagai waste.", result.pack_code));
                }
                return;
            }
            reason = await makeAwaitable(this.dialog, TextInputPopup, {
                title: _t("Sudah dimasak. Alasan pembatalan"),
            });
            if (!reason) {
                return;
            }
            approval = await this.rasentraAskApproval(result.message);
            if (!approval) {
                return;
            }
        }
    },
});


patch(PosOrder.prototype, {
    removeOrderline(line) {
        const store = rasentraBridge.store;
        const jobLines = [line, ...this.lines.filter(
            (l) => l.rasentra_cooking_job_uuid && store?.rasentraPackCode(line) &&
                l.rasentra_cooking_pack === store.rasentraPackCode(line)
        )].filter((l) => l.rasentra_cooking_job_uuid);
        const removed = super.removeOrderline(...arguments);
        if (removed && !this.finalized && store) {
            for (const jobLine of jobLines) {
                if (jobLine !== line) {
                    super.removeOrderline(jobLine);
                }
                store.rasentraCancelCooking(this, jobLine);
            }
        }
        return removed;
    },
});
