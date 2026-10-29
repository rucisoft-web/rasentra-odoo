import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const STATUS_LABELS = {
    queued: _t("Baru"),
    acknowledged: _t("Baru"),
    in_preparation: _t("Dimasak"),
    ready: _t("Siap"),
    served: _t("Disajikan"),
    cancel_requested: _t("Minta batal"),
    cancelled: _t("Batal"),
};

function fmtSeconds(seconds) {
    const s = Math.max(0, Math.round(seconds || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Rasentra Kitchen: papan station, expeditor, antrean pickup, analisis waktu saji dan produksi batch.
 * Data dari model rasentra.kitchen lewat ORM; pembaruan lewat bus.bus dengan cadangan polling versi.
 */
export class RasentraKitchenBoard extends Component {
    static template = "rasentra_kitchen.Board";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.busService = useService("bus_service");
        const saved = window.localStorage?.getItem("rasentra_kitchen_view");
        this.state = useState({
            view: saved || "station",
            station: window.localStorage?.getItem("rasentra_kitchen_station") || "grill",
            board: null,
            queue: null,
            analytics: null,
            production: null,
            produce: { version_id: false, quantity: "", actual_output: "", loss_reason: "", inputs: {} },
            bumpCode: "",
            tick: 0,
        });
        this.version = null;
        onWillStart(() => this.load());
        onMounted(() => {
            this.poll = setInterval(() => this.checkVersion(), 3000);
            this.clock = setInterval(() => this.state.tick++, 1000);
        });
        onWillUnmount(() => {
            clearInterval(this.poll);
            clearInterval(this.clock);
            if (this.channel) {
                this.busService.deleteChannel(this.channel);
            }
        });
    }

    get statusLabels() {
        return STATUS_LABELS;
    }

    fmt(seconds) {
        return fmtSeconds(seconds);
    }

    elapsed(card) {
        return card.elapsed + this.state.tick;
    }

    level(card) {
        const ratio = this.elapsed(card) / (card.target || 600);
        if (ratio >= 1) {
            return "late";
        }
        return ratio >= 0.75 ? "warn" : card.level === "late" ? "late" : "ok";
    }

    async call(method, args = [], kwargs = {}) {
        try {
            return await this.orm.call("rasentra.kitchen", method, args, kwargs);
        } catch (error) {
            this.notification.add(error.data?.message || error.message, { type: "danger" });
            return null;
        }
    }

    subscribe(outletId) {
        const channel = `rasentra_kitchen_${outletId}`;
        if (this.channel === channel) {
            return;
        }
        this.channel = channel;
        this.busService.addChannel(channel);
        this.busService.subscribe("rasentra_kitchen/updated", () => this.load());
    }

    async load() {
        const view = this.state.view;
        if (view === "station" || view === "expeditor") {
            const board = await this.call("board", [], {
                station: view === "station" ? this.state.station : false,
            });
            if (board) {
                this.state.board = board;
                this.state.tick = 0;
                this.version = board.version;
                this.subscribe(board.outlet.id);
            }
        } else if (view === "queue") {
            this.state.queue = await this.call("queue");
        } else if (view === "analytics") {
            this.state.analytics = await this.call("analytics");
        } else if (view === "production") {
            this.state.production = await this.call("production_options");
        }
    }

    async checkVersion() {
        if (this.state.view === "queue") {
            return this.load();
        }
        if (!["station", "expeditor"].includes(this.state.view)) {
            return;
        }
        const version = await this.orm.call("rasentra.kitchen", "version", []).catch(() => null);
        if (version && version !== this.version) {
            await this.load();
        }
    }

    setView(view) {
        this.state.view = view;
        window.localStorage?.setItem("rasentra_kitchen_view", view);
        this.load();
    }

    setStation(station) {
        this.state.station = station;
        window.localStorage?.setItem("rasentra_kitchen_station", station);
        this.load();
    }

    get expeditor() {
        return this.state.view === "expeditor";
    }

    async bumpItem(item) {
        await this.call("bump_item", [item.id], { expeditor: this.expeditor });
        await this.load();
    }

    async bumpTicket(ticketId) {
        await this.call("bump_ticket", [ticketId], { expeditor: this.expeditor });
        await this.load();
    }

    async recall(item) {
        await this.call("recall", [item.id]);
        await this.load();
    }

    async confirmCancel(item) {
        await this.call("confirm_cancel", [item.id]);
        await this.load();
    }

    async onBumpCode(ev) {
        if (ev.key !== "Enter" || !this.state.bumpCode) {
            return;
        }
        await this.call("bump_by_code", [this.state.bumpCode], { expeditor: this.expeditor });
        this.state.bumpCode = "";
        await this.load();
    }

    instructionText(instructions) {
        const parts = [];
        for (const key of ["modifiers", "doneness", "method", "sauce", "note", "allergy"]) {
            const value = instructions[key];
            if (value) {
                parts.push(Array.isArray(value) ? value.join(", ") : value);
            }
        }
        if (instructions.pack_id) {
            parts.push(`Pack ${instructions.pack_id} · ${instructions.raw_weight} kg`);
        }
        return parts.join(" · ");
    }

    get selectedRecipe() {
        const id = parseInt(this.state.produce.version_id);
        return this.state.production?.recipes.find((r) => r.id === id);
    }

    async produce() {
        const p = this.state.produce;
        const result = await this.call("produce_recipe", [
            parseInt(p.version_id), p.quantity, p.actual_output, p.inputs, p.loss_reason || false,
        ]);
        if (result) {
            this.notification.add(
                _t("Produksi %(doc)s tercatat, susut %(loss)s (%(pct)s%%)", {
                    doc: result.doc_no, loss: result.loss, pct: result.loss_percent,
                }),
                { type: "success" }
            );
            this.state.produce = { version_id: false, quantity: "", actual_output: "", loss_reason: "", inputs: {} };
        }
    }
}

registry.category("actions").add("rasentra_kitchen.board", RasentraKitchenBoard);
