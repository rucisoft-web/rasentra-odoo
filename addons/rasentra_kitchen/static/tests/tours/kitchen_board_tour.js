import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("RasentraKitchenBoardTour", {
    steps: () => [
        { trigger: ".o_rasentra_kds_brand" },
        { trigger: ".o_rasentra_card .o_rasentra_item:contains('Sirloin Steak')" },
        { trigger: ".o_rasentra_item:contains('Sirloin Steak') .flex-grow-1", run: "click" },
        { trigger: ".o_rasentra_item.status-in_preparation:contains('Sirloin Steak')" },
        { trigger: "button:contains('Expeditor')", run: "click" },
        { trigger: ".o_rasentra_card .o_rasentra_item:contains('Es teh')" },
        { trigger: "button:contains('Antrean')", run: "click" },
        { trigger: ".o_rasentra_queue h3:contains('Disiapkan')" },
        { trigger: "button:contains('Analisis')", run: "click" },
        { trigger: ".o_rasentra_analytics h5:contains('Per station')" },
        { trigger: "button:contains('Produksi')", run: "click" },
        { trigger: ".o_rasentra_production select", run: "selectByLabel Saus BBQ v1" },
        { trigger: ".o_rasentra_production td:contains('Tomat')" },
    ],
});
