from odoo import fields, models

from ..tools import uuid7


class RasentraUuidMixin(models.AbstractModel):
    """Kunci lintas instalasi. Central dan Lokal hanya saling menyebut `uuid`, tidak pernah `id`."""

    _name = "rasentra.uuid.mixin"
    _description = "Rasentra UUID"

    uuid = fields.Char(
        string="UUID", required=True, readonly=True, copy=False, index=True, default=lambda self: uuid7()
    )

    _sql_constraints = [("uuid_unique", "unique(uuid)", "UUID harus unik.")]
