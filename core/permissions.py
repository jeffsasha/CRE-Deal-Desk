"""Role-based permissions, enforced on the server for every view.

Templates hide controls a user cannot use, but the decorators and helpers here are
the actual gate: a read-only user who crafts a POST still receives HTTP 403.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

ADMIN = "admin"
BROKER = "broker"
COORDINATOR = "coordinator"
READ_ONLY = "read_only"

ALL_ROLES = {ADMIN, BROKER, COORDINATOR, READ_ONLY}
STAFF = {ADMIN, BROKER, COORDINATOR}
BROKERS = {ADMIN, BROKER}

PERMISSIONS = {
    "view": ALL_ROLES,
    "edit": STAFF,
    "client.details": STAFF,  # client emails, phones, notes
    "document.confidential": BROKERS,
    "document.archive": BROKERS,
    "commission.view": BROKERS,
    "salary.manage": BROKERS,
    "commission.edit": BROKERS,
    "reports.financial": BROKERS,
    "import": STAFF,
    "import.revert": BROKERS,
    "audit.view": BROKERS,
    "settings.manage": {ADMIN},
    "users.manage": {ADMIN},
}

PERMISSION_LABELS = {
    "view": "View deals, properties, deadlines and standard documents",
    "edit": "Create and edit operational records",
    "client.details": "See client contact details",
    "document.confidential": "Open confidential documents",
    "document.archive": "Archive documents",
    "commission.view": "View commission ledger",
    "salary.manage": "Manage own salary records",
    "commission.edit": "Edit commission records",
    "reports.financial": "View financial reports",
    "import": "Run historical imports",
    "import.revert": "Revert import batches",
    "audit.view": "View audit log",
    "settings.manage": "Manage workspace settings",
    "users.manage": "Manage users and roles",
}


def has_perm(user, perm):
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if perm not in PERMISSIONS:
        raise KeyError(f"Unknown permission: {perm}")
    return user.role in PERMISSIONS[perm]


def require(user, perm):
    if not has_perm(user, perm):
        raise PermissionDenied(f"Your role does not allow: {PERMISSION_LABELS.get(perm, perm)}")


def require_perm(perm):
    """View decorator. Also blocks state-changing methods for users without `edit`."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            require(request.user, perm)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def require_edit_on_post(view):
    """GET needs `view`; any other method needs `edit`."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require(request.user, "view")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            require(request.user, "edit")
        return view(request, *args, **kwargs)

    return wrapped


def role_matrix():
    roles = [(ADMIN, "Administrator"), (BROKER, "Broker"), (COORDINATOR, "Coordinator"), (READ_ONLY, "Read-only")]
    rows = []
    for perm, label in PERMISSION_LABELS.items():
        rows.append({"label": label, "cells": [role in PERMISSIONS[perm] for role, _ in roles]})
    return roles, rows
