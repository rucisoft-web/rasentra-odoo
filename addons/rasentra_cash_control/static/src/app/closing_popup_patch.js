import { patch } from "@web/core/utils/patch";
import { parseFloat } from "@web/views/fields/parsers";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";

patch(ClosePosPopup.prototype, {
    /** Hitungan per metode bayar Rasentra, dari kolom "counted" di popup tutup kasir. */
    rasentraCounts() {
        const counts = {};
        for (const [id, value] of Object.entries(this.state.payments)) {
            const method = this.pos.models["pos.payment.method"].get(parseInt(id));
            const code =
                method?.rasentra_method || (method?.is_cash_count ? "cash" : "edc_manual");
            counts[code] = (counts[code] || 0) + parseFloat(value.counted || "0");
        }
        return counts;
    },

    async rasentraCloseCheck(approval = null) {
        let result;
        try {
            result = await this.pos.data.call("pos.session", "rasentra_close_check", [
                [this.pos.session.id], this.rasentraCounts(), this.pos.rasentraEmployeeId(), approval,
            ]);
        } catch (error) {
            this.pos.rasentraAlert(error);
            return false;
        }
        if (result.kind === "approval_required") {
            const granted = await this.pos.rasentraAskApproval(result.message);
            return granted ? this.rasentraCloseCheck(granted) : false;
        }
        return result.successful;
    },

    async closeSession() {
        // Hitungan dan selisih dicatat (dan disetujui bila perlu) sebelum Odoo menutup sesi.
        if (this.pos.rasentraEnabled && !(await this.rasentraCloseCheck())) {
            return;
        }
        return super.closeSession(...arguments);
    },
});
