import * as ProductScreen from "@point_of_sale/../tests/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/tours/utils/payment_screen_util";
import * as ReceiptScreen from "@point_of_sale/../tests/tours/utils/receipt_screen_util";
import * as Chrome from "@point_of_sale/../tests/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/tours/utils/dialog_util";
import { registry } from "@web/core/registry";
import { scan_barcode } from "@point_of_sale/../tests/tours/utils/common";

// U01 di layar POS: dua Pack ID dipindai, promo 10% dihitung server saat bayar, struk tercetak.
registry.category("web_tour.tours").add("RasentraPackScanTour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            scan_barcode("PK-T00184"),
            ProductScreen.selectedOrderlineHas("Sirloin AUS", "1.50", "300,000.00"),
            scan_barcode("PK-T00191"),
            ProductScreen.selectedOrderlineHas("Sirloin AUS", "1.75", "350,000.00"),
            ProductScreen.totalAmountIs("650,000.00"),
            // Pack yang sama tidak boleh masuk dua kali.
            scan_barcode("PK-T00184"),
            Dialog.confirm(),
            ProductScreen.clickPayButton(),
            PaymentScreen.totalIs("585,000.00"),
            PaymentScreen.clickPaymentMethod("Bank"),
            PaymentScreen.clickValidate(),
            ReceiptScreen.isShown(),
            Chrome.endTour(),
        ].flat(),
});
