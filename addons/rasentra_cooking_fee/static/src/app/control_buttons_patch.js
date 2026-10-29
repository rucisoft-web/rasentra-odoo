import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";

patch(ControlButtons.prototype, {
    get rasentraCookingEnabled() {
        return this.pos.rasentraEnabled;
    },
});
