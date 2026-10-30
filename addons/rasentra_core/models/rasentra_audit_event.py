import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RasentraAuditEvent(models.Model):
    """Jejak audit append-only (padanan audit_events). Tidak bisa diubah atau dihapus,
    baik lewat ORM maupun SQL langsung (dijaga trigger PostgreSQL)."""

    _name = "rasentra.audit.event"
    _description = "Audit Rasentra"
    _order = "id desc"
    _log_access = False

    created_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now, index=True)
    outlet_id = fields.Many2one("rasentra.outlet", readonly=True, index=True)
    actor_id = fields.Many2one("res.users", readonly=True)
    actor_employee_id = fields.Many2one("hr.employee", readonly=True)
    approver_employee_id = fields.Many2one("hr.employee", readonly=True)
    action = fields.Char(required=True, readonly=True, index=True)
    subject_model = fields.Char(readonly=True)
    subject_ref = fields.Char(readonly=True, index=True)
    before = fields.Json(readonly=True)
    after = fields.Json(readonly=True)
    reason = fields.Char(readonly=True)
    amount = fields.Float(digits=(18, 2), readonly=True)
    correlation_id = fields.Char(readonly=True)
    details = fields.Text(compute="_compute_details")

    def init(self):
        self.env.cr.execute(
            """
            CREATE OR REPLACE FUNCTION rasentra_audit_append_only() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'rasentra_audit_event bersifat append-only';
            END;
            $$ LANGUAGE plpgsql;
            DROP TRIGGER IF EXISTS rasentra_audit_append_only ON rasentra_audit_event;
            CREATE TRIGGER rasentra_audit_append_only
                BEFORE UPDATE OR DELETE ON rasentra_audit_event
                FOR EACH ROW EXECUTE FUNCTION rasentra_audit_append_only();
            """
        )

    def _compute_details(self):
        for event in self:
            event.details = json.dumps({"before": event.before, "after": event.after}, indent=2, default=str)

    def write(self, vals):
        raise UserError(_("Audit tidak bisa diubah."))

    def unlink(self):
        raise UserError(_("Audit tidak bisa dihapus."))

    @api.model
    def record(self, action, subject=None, actor=None, employee=None, approver=None, reason=None,
               amount=None, before=None, after=None, outlet=None, correlation_id=None):
        """Catat satu kejadian. `subject` boleh recordset atau string 'model:ref'."""
        if subject is None:
            model, ref = None, None
        elif isinstance(subject, str):
            model, _sep, ref = subject.partition(":")
        else:
            model = subject._name
            ref = getattr(subject, "uuid", None) or str(subject.id)
        if outlet is None and subject is not None and not isinstance(subject, str):
            if subject._name == "rasentra.outlet":
                outlet = subject
            elif "outlet_id" in subject._fields:
                outlet = subject.outlet_id
        return self.sudo().create(
            {
                "action": action,
                "subject_model": model,
                "subject_ref": ref,
                "actor_id": (actor or self.env.user).id,
                "actor_employee_id": employee.id if employee else False,
                "approver_employee_id": approver.id if approver else False,
                "reason": reason,
                "amount": float(amount) if amount is not None else 0.0,
                "before": before or None,
                "after": after or None,
                "outlet_id": outlet.id if outlet else False,
                "correlation_id": correlation_id or self.env.context.get("rasentra_correlation_id"),
            }
        )
