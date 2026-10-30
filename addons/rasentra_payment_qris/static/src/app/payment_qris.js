import { _t } from "@web/core/l10n/translation";
import { PaymentInterface } from "@point_of_sale/app/payment/payment_interface";
import { register_payment_method } from "@point_of_sale/app/store/pos_store";

const POLL_MS = 2000;
const TIMEOUT_MS = 120000;

/**
 * QRIS/EDC terintegrasi: buat tagihan di server, tunggu konfirmasi provider. Timeout = "uncertain":
 * kasir wajib cek status lagi, tidak boleh meminta pelanggan membayar ulang.
 */
export class PaymentRasentraQris extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.intents = {};
        this.cancelled = {};
    }

    call(method, ...args) {
        return this.pos.data.call("pos.session", method, [[this.pos.session.id], ...args]);
    }

    async send_payment_request(uuid) {
        await super.send_payment_request(...arguments);
        const order = this.pos.get_order();
        const line = order.payment_ids.find((p) => p.uuid === uuid);
        let intent = this.intents[uuid];
        if (!intent || ["failed", "cancelled"].includes(intent.status)) {
            intent = await this.call("rasentra_payment_start", order.uuid, this.payment_method_id.id, line.amount);
            this.intents[uuid] = intent;
        }
        line.set_payment_status("waitingCard");
        line.rasentraQr = intent.qr_string;
        this.cancelled[uuid] = false;
        const started = Date.now();
        while (!this.cancelled[uuid]) {
            intent = await this.call("rasentra_payment_status", intent.uuid);
            this.intents[uuid] = intent;
            if (intent.status === "succeeded") {
                line.transaction_id = intent.uuid;
                line.card_type = "QRIS";
                return true;
            }
            if (intent.status === "failed") {
                this.pos.rasentraAlert(_t("Pembayaran ditolak provider."));
                return false;
            }
            if (Date.now() - started > TIMEOUT_MS) {
                await this.call("rasentra_payment_timeout", intent.uuid);
                this.pos.rasentraAlert(
                    _t("Status pembayaran belum pasti. Cek status lagi; jangan minta pelanggan membayar ulang.")
                );
                line.set_payment_status("retry");
                return false;
            }
            await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        }
        return false;
    }

    async send_payment_cancel(order, uuid) {
        await super.send_payment_cancel(...arguments);
        const intent = this.intents[uuid];
        this.cancelled[uuid] = true;
        if (intent && intent.status === "pending") {
            try {
                this.intents[uuid] = await this.call("rasentra_payment_cancel", intent.uuid);
            } catch (error) {
                this.pos.rasentraAlert(error);
                return false;
            }
        }
        return true;
    }
}

register_payment_method("rasentra_qris", PaymentRasentraQris);
