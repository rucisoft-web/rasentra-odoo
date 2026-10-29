import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

/** Spesifikasi & Panduan ditampilkan di dalam backend (iframe ke halaman yang hanya bisa dibuka setelah login). */
export class RasentraDocs extends Component {
    static template = "rasentra_docs.Docs";
    static props = ["*"];

    get src() {
        const page = this.props.action?.params?.page || "index.html";
        const anchor = this.props.action?.params?.anchor;
        return `/rasentra/docs/${page}${anchor ? "#" + anchor : ""}`;
    }
}

registry.category("actions").add("rasentra_docs.viewer", RasentraDocs);
