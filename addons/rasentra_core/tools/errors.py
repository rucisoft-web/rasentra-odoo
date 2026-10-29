from odoo.exceptions import UserError


class RasentraError(UserError):
    """Padanan App\\Support\\DomainException: kode mesin + pesan untuk kasir + status HTTP."""

    def __init__(self, code, message, status=422, context=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.context = context or {}

    @classmethod
    def conflict(cls, code, message, context=None):
        return cls(code, message, 409, context)

    @classmethod
    def needs_approval(cls, code, message, context=None):
        return cls(code, message, 403, dict(context or {}, approval_required=True))
