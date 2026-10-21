from datetime import date, datetime
from decimal import Decimal

from .models import AuditLog


def _plain(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "pk"):
        return f"{value} (#{value.pk})"
    return value


def audit(actor, action, obj=None, changes=None, note=""):
    """Record a meaningful change. `changes` maps field -> (old, new)."""
    clean = {}
    for field, pair in (changes or {}).items():
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            clean[field] = [_plain(pair[0]), _plain(pair[1])]
        else:
            clean[field] = _plain(pair)
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        model_label=obj._meta.label if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        object_repr=str(obj)[:255] if obj is not None else "",
        changes=clean,
        note=note,
    )


def diff(instance, original, fields):
    """Return {field: (old, new)} for tracked fields that changed."""
    out = {}
    for field in fields:
        old = original.get(field)
        new = getattr(instance, field)
        if old != new:
            out[field] = (old, new)
    return out


def snapshot(instance, fields):
    return {field: getattr(instance, field) for field in fields}
