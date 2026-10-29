import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

patch(ProductScreen.prototype, {
    async _barcodeProductAction(code) {
        // Pack ID dikunci di server lebih dulu; SKU dan barcode timbangan tetap lewat jalur Odoo.
        if (await this.pos.rasentraScan(code.code)) {
            this.numberBuffer.reset();
            return;
        }
        return super._barcodeProductAction(...arguments);
    },
});
