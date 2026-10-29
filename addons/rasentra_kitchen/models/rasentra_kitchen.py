import hashlib
import math
import secrets
from datetime import timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.rasentra_core.models.product_template import KITCHEN_STATIONS
from odoo.addons.rasentra_core.tools import RasentraError, qty

STATION_TARGET_MINUTES = {"grill": 15, "hot": 10, "cold": 8, "bar": 5, "pastry": 10, "packing": 5}
ACTIVE = ("queued", "acknowledged", "in_preparation", "ready", "cancel_requested")
STATION_VIEW = ("queued", "acknowledged", "in_preparation", "cancel_requested")
PICKUP_CHANNELS = ("takeaway", "pickup", "delivery")
RANK = {"queued": 0, "acknowledged": 0, "in_preparation": 1, "ready": 2}


class RasentraKitchen(models.AbstractModel):
    """Rasentra Kitchen (port KitchenService + KitchenBoard). Mengirim hanya delta ke station, sehingga
    koneksi ulang tidak memasak ulang seluruh pesanan. Status maju satu langkah per bump:
    Baru → Dimasak → Siap → Disajikan; station hanya sampai Siap, Disajikan oleh expeditor/pelayan."""

    _name = "rasentra.kitchen"
    _description = "Rasentra Kitchen"

    # ---- helpers ------------------------------------------------------------------------

    @api.model
    def _check_user(self):
        user = self.env.user
        if not (user.has_group("rasentra_core.group_rasentra_kitchen") or user.has_group("point_of_sale.group_pos_user")
                or user.has_group("rasentra_core.group_rasentra_outlet_head")):
            raise AccessError(_("Layar dapur hanya untuk pengguna dapur, POS, atau kepala outlet."))

    @api.model
    def _employee(self):
        return self.env.user.employee_id

    @api.model
    def _outlet(self, outlet_id=None):
        Outlet = self.env["rasentra.outlet"].sudo()
        if outlet_id:
            return Outlet.browse(int(outlet_id)).exists()
        return self.env["rasentra.profile"].current_outlet() or Outlet.search([("has_restaurant", "=", True)], limit=1)

    @api.model
    def _kitchen_location(self, outlet):
        ledger = self.env["rasentra.stock.ledger"]
        own = outlet.sudo().location_ids.filtered(lambda l: l.rasentra_type == "kitchen" and l.active)[:1]
        return own or ledger.location(outlet, "stock")

    @api.model
    def stations(self):
        params = self.env["ir.config_parameter"].sudo()
        return [
            {"code": code, "name": name,
             "target_minutes": int(params.get_param(f"rasentra.kitchen.target.{code}", STATION_TARGET_MINUTES[code]))}
            for code, name in KITCHEN_STATIONS
        ]

    @api.model
    def _target_seconds(self, station):
        return next((s["target_minutes"] for s in self.stations() if s["code"] == station), 10) * 60

    @api.model
    def _notify(self, outlet, station=None):
        self.env["bus.bus"]._sendone(f"rasentra_kitchen_{outlet.id}", "rasentra_kitchen/updated",
                                     {"station": station})

    @api.model
    def _new_bump_code(self):
        Ticket = self.env["rasentra.kitchen.ticket"].sudo()
        while True:
            code = str(10000000 + secrets.randbelow(90000000))
            if not Ticket.search_count([("bump_code", "=", code)]):
                return code

    @api.model
    def _line_modifier_keys(self, line):
        keys = [v.product_attribute_value_id.rasentra_modifier_key
                for v in line.attribute_value_ids if v.product_attribute_value_id.rasentra_modifier_key]
        return keys

    @api.model
    def _order_label(self, order):
        if "table_id" in order._fields and order.table_id:
            return _("Meja %s", order.table_id.table_number)
        if order.rasentra_queue_no:
            return _("No. %s", order.rasentra_queue_no)
        return order.tracking_number and _("Pesanan %s", order.tracking_number) or order.pos_reference or order.name

    @api.model
    def _order_channel(self, order):
        if "takeaway" in order._fields and order.takeaway:
            return "takeaway"
        return order.config_id.rasentra_channel or "restaurant"

    # ---- kirim ke dapur ---------------------------------------------------------------

    @api.model
    def send(self, order, course=None):
        """Kirim baris yang belum dikirim. `course` membatasi ke satu gelombang (pembuka, utama, penutup)."""
        order = order.sudo()
        self.env.cr.execute("SELECT id FROM pos_order WHERE id = %s FOR UPDATE", [order.id])
        outlet = order.config_id.rasentra_outlet_id
        if not outlet:
            raise RasentraError("kitchen_no_outlet", _("POS ini belum terhubung ke outlet Rasentra."))
        Item = self.env["rasentra.kitchen.item"].sudo()
        Job = self.env["rasentra.cooking.job"].sudo()
        employee = order.employee_id
        pending = []
        for line in order.lines.filtered(lambda l: l.product_id.kitchen_station and not l.rasentra_promo_uuid):
            if course and (line.rasentra_course or "main") != course:
                continue
            if not line.uuid:
                continue
            sent_items = Item.search([("line_uuid", "=", line.uuid), ("status", "!=", "cancelled")], order="id desc")
            sent = sum((qty(i.quantity) for i in sent_items), qty(0))
            current = qty(line.qty)
            if current < sent:
                # Kuantitas dikurangi setelah dikirim: batalkan item terakhir sampai tidak melebihi.
                for item in sent_items:
                    if sent <= current:
                        break
                    self._void_item(item, employee, _("Kuantitas dikurangi kasir"))
                    sent -= qty(item.quantity)
            delta = current - sent
            if delta > 0:
                pending.append((line, delta))

        tickets = self.env["rasentra.kitchen.ticket"].sudo()
        label, channel = self._order_label(order), self._order_channel(order)
        for station in dict.fromkeys(line.product_id.kitchen_station for line, _d in pending):
            existing = self.env["rasentra.kitchen.ticket"].sudo().search_count([("order_uuid", "=", order.uuid)])
            ticket = tickets.create({
                "outlet_id": outlet.id, "pos_order_id": order.id, "order_uuid": order.uuid, "station": station,
                "sequence": existing + 1, "bump_code": self._new_bump_code(), "label": label, "channel": channel,
                "course": course or False,
            })
            for line, delta in [(l, d) for l, d in pending if l.product_id.kitchen_station == station]:
                job = Job.search([("uuid", "=", line.rasentra_cooking_job_uuid)], limit=1) \
                    if line.rasentra_cooking_job_uuid else Job
                instructions = {
                    "product": line.full_product_name or line.product_id.name,
                    "modifiers": line.attribute_value_ids.mapped("name") or None,
                    "course": line.rasentra_course or None,
                    "note": line.customer_note or line.note or None,
                    **(job._instructions() if job else {}),
                }
                Item.create({
                    "ticket_id": ticket.id, "line_uuid": line.uuid, "pos_order_line_id": line.id,
                    "product_id": line.product_id.id, "quantity": float(delta),
                    "instructions": {k: v for k, v in instructions.items() if v},
                    "modifier_keys": self._line_modifier_keys(line),
                    "cooking_job_uuid": line.rasentra_cooking_job_uuid or False,
                })
            ticket.invalidate_recordset()
            tickets |= ticket
        if tickets and channel in PICKUP_CHANNELS and not order.rasentra_queue_no:
            order.rasentra_queue_no = self._next_queue_no(order, outlet)
        for station in set(tickets.mapped("station")):
            self._notify(outlet, station)
        if tickets:
            self.env["rasentra.audit.event"].record("kitchen.sent", order, employee=employee, outlet=outlet,
                                                    after={"tickets": tickets.mapped("bump_code"), "course": course})
        return tickets

    @api.model
    def _next_queue_no(self, order, outlet):
        # Nomor antrean per outlet per hari usaha (1..999), dipanggil di layar antrean pickup.
        start = fields.Datetime.now() - timedelta(hours=18)
        last = self.env["pos.order"].sudo().search(
            [("rasentra_outlet_id", "=", outlet.id), ("rasentra_queue_no", "!=", 0), ("create_date", ">=", start)],
            order="id desc", limit=1)
        return (last.rasentra_queue_no % 999) + 1 if last else 1

    # ---- langkah status -----------------------------------------------------------------

    def _consume(self, item):
        """Mulai memasak: konsumsi bahan sesuai versi resep aktif, sekali untuk item ini."""
        line_job = self.env["rasentra.cooking.job"].sudo().search([("uuid", "=", item.cooking_job_uuid)], limit=1) \
            if item.cooking_job_uuid else None
        if line_job:
            # Resep jasa hanya memuat bahan tambahan; daging pelanggan tidak dipotong lagi.
            version = line_job.rule_id.recipe_version_id
            line_job.mark_cooking()
        else:
            version = self.env["rasentra.recipe"].active_version_for(item.product_id)
        if not version:
            return
        outlet = item.ticket_id.outlet_id
        ledger = self.env["rasentra.stock.ledger"]
        kitchen = self._kitchen_location(outlet)
        production = ledger.virtual(outlet.company_id, "production")
        Event = self.env["rasentra.consumption.event"].sudo()
        for need in version.explode(item.quantity, item.modifier_keys or []):
            move = ledger.move(need["product"], need["quantity"], kitchen, production,
                               f"{item.ticket_id.bump_code} {item.product_id.default_code or ''}".strip())
            Event.create({"outlet_id": outlet.id, "source_type": "kitchen_item", "source_ref": str(item.id),
                          "recipe_version_id": version.id, "product_id": need["product"].id,
                          "quantity": float(need["quantity"]), "reason": "sale", "move_id": move.id})
        item.recipe_version_id = version

    def _start(self, item):
        if item.status in ("in_preparation", "ready", "served"):
            return item
        if item.status in ("cancelled", "cancel_requested"):
            raise RasentraError.conflict("item_cancelled", _("Item sudah dibatalkan."))
        self._consume(item)
        item.write({"status": "in_preparation", "started_at": fields.Datetime.now(),
                    "acknowledged_at": item.acknowledged_at or fields.Datetime.now()})
        return item

    def _ready(self, item):
        item.write({"status": "ready", "ready_at": fields.Datetime.now()})

    def _served(self, item):
        item.write({"status": "served", "served_at": fields.Datetime.now()})
        if item.cooking_job_uuid:
            self.env["rasentra.cooking.job"].sudo().search([("uuid", "=", item.cooking_job_uuid)]).mark_served()

    def _cancel(self, item, employee, reason):
        """Sebelum masak: tanpa konsumsi. Sesudah masak: bahan yang terpakai menjadi waste (dokumen untuk SAP)."""
        if item.status == "cancelled":
            return item
        after_cook = bool(item.started_at) or item.status in ("in_preparation", "ready", "served")
        if after_cook:
            events = self.env["rasentra.consumption.event"].sudo().search(
                [("source_type", "=", "kitchen_item"), ("source_ref", "=", str(item.id)), ("reason", "!=", "waste")])
            if events:
                events.write({"reason": "waste"})
                # Stok sudah keluar saat konsumsi; dokumen ini memindahkan pencatatannya ke waste.
                self.env["rasentra.stock.adjustment"].record(
                    "waste", item.ticket_id.outlet_id,
                    [{"product": e.product_id, "quantity": e.quantity, "from_state": "available", "to_state": None}
                     for e in events],
                    employee=employee, reason=_("Batal setelah dimasak: %s", reason),
                    source_type="kitchen_item", source_ref=str(item.id))
        item.write({"status": "cancelled", "cancel_reason": item.cancel_reason or reason})
        self.env["rasentra.audit.event"].record(
            "kitchen.cancel_after_cook" if after_cook else "kitchen.cancel_before_cook",
            f"rasentra.kitchen.item:{item.id}", employee=employee, reason=reason, outlet=item.ticket_id.outlet_id)
        return item

    def _void_item(self, item, employee, reason):
        """Kasir mem-void baris yang sudah dikirim: belum dimasak langsung batal; sedang/siap = minta batal."""
        if item.status in ("cancelled", "served", "cancel_requested"):
            return
        if not item.started_at and item.status in ("queued", "acknowledged"):
            self._cancel(item, employee, reason)
        else:
            item.write({"status": "cancel_requested", "cancel_reason": reason})
            self.env["rasentra.audit.event"].record("kitchen.cancel_requested", f"rasentra.kitchen.item:{item.id}",
                                                    employee=employee, reason=reason, outlet=item.ticket_id.outlet_id)
        self._notify(item.ticket_id.outlet_id, item.ticket_id.station)

    @api.model
    def line_voided(self, line_uuids, employee=None, reason=None):
        items = self.env["rasentra.kitchen.item"].sudo().search(
            [("line_uuid", "in", list(line_uuids)), ("status", "in", ("queued", "acknowledged", "in_preparation", "ready"))])
        for item in items:
            self._void_item(item, employee, reason or _("Void kasir"))

    @api.model
    def split_transfer(self, original, new, moves):
        """Pindahkan item dapur dari baris order asal ke baris order hasil split (padanan split bill)."""
        Item = self.env["rasentra.kitchen.item"].sudo()
        Line = self.env["pos.order.line"].sudo()
        for move in moves:
            if not move.get("to_line_uuid"):
                continue
            remaining = qty(move["qty"])
            target = Line.search([("uuid", "=", move["to_line_uuid"])], limit=1)
            for item in Item.search([("line_uuid", "=", move["from_line_uuid"]), ("status", "!=", "cancelled")],
                                    order="id desc"):
                if remaining <= 0:
                    break
                vals = {"line_uuid": move["to_line_uuid"], "pos_order_line_id": target.id}
                if qty(item.quantity) <= remaining:
                    remaining -= qty(item.quantity)
                    item.write(vals)
                else:
                    item.copy(dict(vals, quantity=float(remaining), status=item.status,
                                   started_at=item.started_at, ready_at=item.ready_at))
                    item.quantity = float(qty(item.quantity) - remaining)
                    remaining = qty(0)
        if moves:
            self.env["rasentra.audit.event"].record("kitchen.split", new, outlet=new.config_id.rasentra_outlet_id,
                                                    after={"from": original.uuid, "lines": len(moves)})

    # ---- API layar (dipanggil lewat ORM dari aplikasi OWL) --------------------------------

    @api.model
    def board(self, outlet_id=None, station=None):
        """Tiket aktif per station, atau semua station (expeditor) bila station kosong."""
        self._check_user()
        outlet = self._outlet(outlet_id)
        Item = self.env["rasentra.kitchen.item"].sudo()
        statuses = STATION_VIEW if station else ACTIVE
        domain = [("outlet_id", "=", outlet.id), ("status", "in", statuses)]
        if station:
            domain.append(("station", "=", station))
        tickets = Item.search(domain).ticket_id.sorted("id")[:80]
        now = fields.Datetime.now()
        if station:
            tickets.item_ids.filtered(lambda i: i.status == "queued").write(
                {"status": "acknowledged", "acknowledged_at": now})
        warn = float(self.env["ir.config_parameter"].sudo().get_param("rasentra.kitchen.warn_ratio", 0.75))
        cards = [self._card(t, now, warn, bool(station)) for t in tickets]
        if not station:
            grouped = {}
            for card in cards:
                grouped.setdefault(card["order_uuid"], []).append(card)
            cards = []
            for group in grouped.values():
                items = [dict(i, station=c["station"]) for c in group for i in c["items"]]
                levels = {c["level"] for c in group}
                cards.append({
                    "order_uuid": group[0]["order_uuid"], "label": group[0]["label"], "channel": group[0]["channel"],
                    "elapsed": max(c["elapsed"] for c in group),
                    "level": "late" if "late" in levels else ("warn" if "warn" in levels else "ok"),
                    "items": items, "tickets": [c["id"] for c in group],
                    "complete": any(i["status"] == "ready" for i in items)
                    and all(i["status"] in ("ready", "cancel_requested") for i in items),
                })
        return {"station": station or None, "outlet": {"id": outlet.id, "name": outlet.display_name},
                "stations": self.stations(), "server_time": fields.Datetime.to_string(now), "tickets": cards,
                "version": self.version(outlet.id)}

    @api.model
    def _card(self, ticket, now, warn, station_view):
        target = self._target_seconds(ticket.station)
        elapsed = max(0, int((now - ticket.create_date).total_seconds()))
        ratio = elapsed / target if target else 0
        shown = (*STATION_VIEW, "ready", "cancelled") if station_view else ACTIVE
        return {
            "id": ticket.id, "order_uuid": ticket.order_uuid, "station": ticket.station, "bump_code": ticket.bump_code,
            "sequence": ticket.sequence, "label": ticket.label, "channel": ticket.channel, "course": ticket.course,
            "created_at": fields.Datetime.to_string(ticket.create_date), "elapsed": elapsed, "target": target,
            "level": "late" if ratio >= 1 else ("warn" if ratio >= warn else "ok"),
            "items": [
                {"id": i.id, "status": i.status, "quantity": f"{i.quantity:g}", "instructions": i.instructions or {},
                 "cancel_reason": i.cancel_reason or None}
                for i in ticket.item_ids if i.status in shown
            ],
        }

    @api.model
    def bump_item(self, item_id, expeditor=False):
        self._check_user()
        item = self.env["rasentra.kitchen.item"].sudo().browse(int(item_id)).exists()
        if not item:
            raise RasentraError("item_unknown", _("Item tidak ditemukan."), 404)
        self.env.cr.execute("SELECT id FROM rasentra_kitchen_item WHERE id = %s FOR UPDATE", [item.id])
        if item.status in ("queued", "acknowledged"):
            self._start(item)
        elif item.status == "in_preparation":
            self._ready(item)
        elif item.status == "ready":
            if not expeditor:
                raise RasentraError.conflict("needs_expeditor", _("Item sudah Siap. Penyajian dikonfirmasi expeditor."))
            self._served(item)
        else:
            raise RasentraError.conflict("item_closed", _("Item sudah selesai atau dibatalkan."))
        item.bumped_by_id = self._employee()
        self._notify(item.ticket_id.outlet_id, item.ticket_id.station)
        return item.status

    @api.model
    def bump_ticket(self, ticket_id, expeditor=False):
        """Item paling belakang statusnya dimajukan bersama: satu sentuhan memajukan seluruh tiket."""
        self._check_user()
        ticket = self.env["rasentra.kitchen.ticket"].sudo().browse(int(ticket_id)).exists()
        allowed = ("queued", "acknowledged", "in_preparation", "ready") if expeditor else ("queued", "acknowledged", "in_preparation")
        items = ticket.item_ids.filtered(lambda i: i.status in allowed)
        if not items:
            raise RasentraError.conflict("ticket_done", _("Tiket ini sudah selesai di station."))
        lowest = min(RANK[i.status] for i in items)
        for item in items.filtered(lambda i: RANK[i.status] == lowest):
            {0: self._start, 1: self._ready, 2: self._served}[lowest](item)
            item.bumped_by_id = self._employee()
        self._notify(ticket.outlet_id, ticket.station)
        return True

    @api.model
    def bump_by_code(self, code, outlet_id=None, expeditor=False):
        self._check_user()
        outlet = self._outlet(outlet_id)
        ticket = self.env["rasentra.kitchen.ticket"].sudo().search(
            [("outlet_id", "=", outlet.id), ("bump_code", "=", (code or "").strip())], limit=1)
        if not ticket:
            raise RasentraError("ticket_unknown", _("Tiket %s tidak ditemukan di outlet ini.", code), 404)
        return self.bump_ticket(ticket.id, expeditor)

    @api.model
    def recall(self, item_id):
        """Kembalikan item Siap ke Dimasak bila salah sentuh (tanpa konsumsi ulang)."""
        self._check_user()
        item = self.env["rasentra.kitchen.item"].sudo().browse(int(item_id)).exists()
        if item.status != "ready":
            raise RasentraError.conflict("cannot_recall", _("Hanya item Siap yang bisa dikembalikan."))
        item.write({"status": "in_preparation", "ready_at": False})
        self._notify(item.ticket_id.outlet_id, item.ticket_id.station)
        return True

    @api.model
    def confirm_cancel(self, item_id):
        """Station mengonfirmasi permintaan batal dari kasir (bahan yang terpakai menjadi waste)."""
        self._check_user()
        item = self.env["rasentra.kitchen.item"].sudo().browse(int(item_id)).exists()
        if item.status != "cancel_requested":
            raise RasentraError.conflict("no_cancel_request", _("Item ini tidak sedang diminta batal."))
        self._cancel(item, self._employee(), item.cancel_reason or _("Void kasir"))
        self._notify(item.ticket_id.outlet_id, item.ticket_id.station)
        return True

    @api.model
    def version(self, outlet_id=None):
        """Penanda perubahan papan yang murah dihitung; layar memuat ulang hanya bila berubah."""
        outlet = self._outlet(outlet_id)
        self.env["rasentra.kitchen.item"].flush_model()
        self.env.cr.execute(
            """SELECT count(*), max(write_date), coalesce(sum(length(status)), 0) FROM rasentra_kitchen_item
               WHERE outlet_id = %s AND create_date >= now() at time zone 'utc' - interval '12 hours'""",
            [outlet.id])
        row = self.env.cr.fetchone()
        return hashlib.sha1("|".join(str(v) for v in row).encode()).hexdigest()[:12]

    @api.model
    def queue(self, outlet_id=None):
        """Layar antrean pickup: Disiapkan selama ada item belum Siap; Siap diambil saat semua Siap."""
        self._check_user()
        outlet = self._outlet(outlet_id)
        linger = int(self.env["ir.config_parameter"].sudo().get_param("rasentra.kitchen.queue_linger_minutes", 3))
        now = fields.Datetime.now()
        tickets = self.env["rasentra.kitchen.ticket"].sudo().search(
            [("outlet_id", "=", outlet.id), ("channel", "in", PICKUP_CHANNELS),
             ("create_date", ">=", now - timedelta(hours=12))])
        preparing, ready = [], []
        for order in tickets.pos_order_id.filtered("rasentra_queue_no"):
            items = tickets.filtered(lambda t: t.pos_order_id == order).item_ids.filtered(
                lambda i: i.status not in ("cancelled", "cancel_requested"))
            if not items:
                continue
            if all(i.status == "served" for i in items):
                if max(items.mapped("served_at")) < now - timedelta(minutes=linger):
                    continue
                ready.append({"no": order.rasentra_queue_no, "served": True,
                              "at": fields.Datetime.to_string(max(items.mapped("ready_at") or [now]))})
            elif all(i.status in ("ready", "served") for i in items):
                ready.append({"no": order.rasentra_queue_no, "served": False,
                              "at": fields.Datetime.to_string(max(items.mapped("ready_at")))})
            else:
                preparing.append({"no": order.rasentra_queue_no})
        ready.sort(key=lambda r: r["at"], reverse=True)
        preparing.sort(key=lambda r: r["no"])
        return {"preparing": preparing, "ready": ready, "server_time": fields.Datetime.to_string(now)}

    @api.model
    def analytics(self, outlet_id=None, date_from=None, date_to=None):
        """Waktu saji dari tiket dibuat sampai Siap: rata-rata, p50, p90 per station, menu dan jam."""
        self._check_user()
        outlet = self._outlet(outlet_id)
        date_to = fields.Datetime.to_datetime(date_to) if date_to else fields.Datetime.now()
        date_from = fields.Datetime.to_datetime(date_from) if date_from else date_to - timedelta(days=7)
        items = self.env["rasentra.kitchen.item"].sudo().search(
            [("outlet_id", "=", outlet.id), ("ready_at", "!=", False), ("ticket_id.create_date", ">=", date_from),
             ("ticket_id.create_date", "<=", date_to)])
        tz = pytz.timezone(outlet.tz or "Asia/Jakarta")
        rows = []
        for item in items:
            created = item.ticket_id.create_date
            rows.append({
                "station": item.station,
                "product": (item.instructions or {}).get("product") or item.product_id.name,
                "hour": pytz.utc.localize(created).astimezone(tz).hour,
                "total": max(0, (item.ready_at - created).total_seconds()),
                "wait": max(0, (item.started_at - created).total_seconds()) if item.started_at else None,
                "cook": max(0, (item.ready_at - item.started_at).total_seconds()) if item.started_at else None,
            })

        def summarize(group, station=None):
            totals = sorted(r["total"] for r in group)
            target = self._target_seconds(station) if station else None
            waits = [r["wait"] for r in group if r["wait"] is not None]
            cooks = [r["cook"] for r in group if r["cook"] is not None]
            return {
                "count": len(totals),
                "avg_seconds": round(sum(totals) / len(totals)) if totals else 0,
                "p50_seconds": int(_percentile(totals, 0.5)),
                "p90_seconds": int(_percentile(totals, 0.9)),
                "avg_wait_seconds": round(sum(waits) / len(waits)) if waits else 0,
                "avg_cook_seconds": round(sum(cooks) / len(cooks)) if cooks else 0,
                "target_seconds": target,
                "late": sum(1 for t in totals if t > target) if target else None,
            }

        def by(key, station_key=False):
            groups = {}
            for row in rows:
                groups.setdefault(row[key], []).append(row)
            return [dict({key: k}, **summarize(g, k if station_key else None)) for k, g in groups.items()]

        return {
            "from": fields.Datetime.to_string(date_from), "to": fields.Datetime.to_string(date_to),
            "overall": summarize(rows),
            "by_station": sorted(by("station", True), key=lambda r: r["station"]),
            "by_product": sorted(by("product"), key=lambda r: -r["avg_seconds"]),
            "by_hour": sorted(by("hour"), key=lambda r: r["hour"]),
        }

    # ---- produksi dari layar dapur ------------------------------------------------------

    @api.model
    def production_options(self, outlet_id=None):
        self._check_user()
        versions = self.env["rasentra.recipe.version"].sudo().search(
            [("state", "=", "approved"), ("kind", "=", "stocked_prep")])
        return {
            "recipes": [{"id": v.id, "name": v.display_name, "yield": f"{v.yield_quantity:g}",
                         "uom": v.recipe_id.product_id.uom_id.name,
                         "inputs": [{"product_id": n["product"].id, "name": n["product"].name,
                                     "quantity": str(n["quantity"]), "uom": n["product"].uom_id.name}
                                    for n in v.explode(v.yield_quantity)]}
                        for v in versions],
            "loss_reasons": self.env["rasentra.production.batch"].loss_reasons(),
            "tolerance_percent": float(self.env["rasentra.production.batch"]._tolerance_percent()),
        }

    @api.model
    def produce_recipe(self, version_id, quantity, actual_output, actual_inputs=None, loss_reason=None, outlet_id=None):
        self._check_user()
        version = self.env["rasentra.recipe.version"].sudo().browse(int(version_id))
        inputs = {int(k): v for k, v in (actual_inputs or {}).items()}
        batch = self.env["rasentra.production.batch"].sudo().produce_from_recipe(
            self._outlet(outlet_id), self._employee(), version, quantity, actual_output, inputs, loss_reason or None)
        return {"doc_no": batch.doc_no, "loss": f"{batch.loss_quantity:g}", "loss_percent": round(batch.loss_percent, 2)}


def _percentile(values, p):
    if not values:
        return 0
    return values[max(0, math.ceil(p * len(values)) - 1)]
