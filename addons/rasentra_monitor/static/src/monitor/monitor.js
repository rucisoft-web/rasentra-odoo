import { Component, onWillStart, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const REFRESH_MS = 30000;
const SAP_LABELS = {
    posted: "Terposting",
    pending: "Menunggu",
    waiting_dependency: "Menunggu induk",
    partially_posted: "Parsial",
    needs_review: "Perlu dicek",
    failed: "Gagal",
    posting: "Sedang diposting",
    validated: "Tervalidasi",
};

/** Status Central: satu layar untuk tim finance/IT memantau outlet, sinkron dan SAP. */
export class RasentraMonitor extends Component {
    static template = "rasentra_monitor.Status";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ data: null, busy: false });
        this.sapLabels = SAP_LABELS;
        onWillStart(() => this.load());
        let timer;
        onMounted(() => (timer = setInterval(() => this.load(), REFRESH_MS)));
        onWillUnmount(() => clearInterval(timer));
    }

    async load() {
        this.state.data = await this.orm.call("rasentra.monitor", "status", []);
    }

    sapEntries(counts) {
        return Object.entries(counts || {}).map(([status, n]) => ({ status, n, label: SAP_LABELS[status] || status }));
    }

    heartbeatText(outlet) {
        if (outlet.heartbeat_minutes === null) {
            return "-";
        }
        return outlet.heartbeat_minutes < 1 ? "baru saja" : `${outlet.heartbeat_minutes} menit lalu`;
    }

    async run(method, okText) {
        this.state.busy = true;
        try {
            const result = await this.orm.call("rasentra.monitor", method, []);
            const parts = Object.entries(result || {}).map(([k, v]) =>
                typeof v === "object" ? `${k}: ${v.ok ? "OK" : "gagal"}` : `${k} ${v}`
            );
            this.notification.add(parts.length ? `${okText}: ${parts.join(", ")}` : `${okText}: tidak ada antrean`, {
                type: "success",
            });
            await this.load();
        } finally {
            this.state.busy = false;
        }
    }

    async open(name) {
        const action = await this.orm.call("rasentra.monitor", "open_action", [name]);
        if (action) {
            this.action.doAction(action);
        }
    }
}

registry.category("actions").add("rasentra_monitor.status", RasentraMonitor);
