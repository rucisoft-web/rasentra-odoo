import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const CHANNELS = { retail: "Retail meatshop", restaurant: "Restoran", resto: "Restoran", lainnya: "Lainnya" };
const DAYS = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];

export function rupiah(value) {
    const n = Math.round(Number(value || 0));
    return "Rp" + n.toLocaleString("id-ID");
}

/** Dashboard grup Indoguna: penjualan per CV dan outlet, tren 7 hari, kesehatan outlet dan pekerjaan tertunda. */
export class RasentraDashboard extends Component {
    static template = "rasentra_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null });
        this.rupiah = rupiah;
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("rasentra.dashboard", "summary", []);
    }

    get maxDay() {
        return Math.max(1, ...this.state.data.days.map((d) => Number(d.net)));
    }

    barHeight(day) {
        return Math.max(2, (Number(day.net) / this.maxDay) * 100);
    }

    sapEntries(counts) {
        return Object.entries(counts || {});
    }

    dayLabel(date) {
        const d = new Date(date + "T00:00:00");
        return `${DAYS[d.getDay()]} ${d.getDate()}`;
    }

    channelLabel(key) {
        return CHANNELS[key] || key;
    }

    async openMonitor() {
        this.action.doAction("rasentra_monitor.action_monitor_status");
    }

    async openAction(xmlid) {
        this.action.doAction(xmlid);
    }
}

registry.category("actions").add("rasentra_dashboard.main", RasentraDashboard);
