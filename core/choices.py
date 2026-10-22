"""Shared choice lists."""
from django.utils.translation import gettext_lazy as _

PROPERTY_TYPES = [
    ("retail", _("Retail")),
    ("restaurant", _("Restaurant")),
    ("office", _("Office")),
    ("industrial", _("Industrial")),
    ("warehouse", _("Warehouse")),
    ("land", _("Land")),
    ("multifamily", _("Multifamily")),
    ("mixed_use", _("Mixed-use")),
    ("other", _("Other")),
]

# Explicit units for every rate or charge. Never store a bare number.
RATE_UNITS = [
    ("usd_total", _("Lump sum ($)")),
    ("usd_sf_year", _("$/SF/year")),
    ("usd_sf_month", _("$/SF/month")),
    ("usd_month", _("Monthly lump sum ($/month)")),
    ("usd_year", _("Annual lump sum ($/year)")),
]
RATE_UNIT_SUFFIX = {
    "usd_total": "",
    "usd_sf_year": "/SF/yr",
    "usd_sf_month": "/SF/mo",
    "usd_month": "/mo",
    "usd_year": "/yr",
}

VERIFICATION_CHOICES = [
    ("unverified", _("Unverified")),
    ("marketing", _("Marketing statement (unverified)")),
    ("verified", _("Verified")),
    ("conflicting", _("Conflicting sources")),
]

REPRESENTED_SIDES = [
    ("buyer", _("Buyer")),
    ("seller", _("Seller")),
    ("landlord", _("Landlord")),
    ("tenant", _("Tenant")),
]

TIME_ZONES = [
    ("America/Chicago", _("Central (America/Chicago)")),
    ("America/New_York", _("Eastern (America/New_York)")),
    ("America/Denver", _("Mountain (America/Denver)")),
    ("America/Phoenix", _("Arizona (America/Phoenix)")),
    ("America/Los_Angeles", _("Pacific (America/Los_Angeles)")),
    ("UTC", _("UTC")),
]
