"""Shared choice lists."""

PROPERTY_TYPES = [
    ("retail", "Retail"),
    ("restaurant", "Restaurant"),
    ("office", "Office"),
    ("industrial", "Industrial"),
    ("warehouse", "Warehouse"),
    ("land", "Land"),
    ("multifamily", "Multifamily"),
    ("mixed_use", "Mixed-use"),
    ("other", "Other"),
]

# Explicit units for every rate or charge. Never store a bare number.
RATE_UNITS = [
    ("usd_total", "Lump sum ($)"),
    ("usd_sf_year", "$/SF/year"),
    ("usd_sf_month", "$/SF/month"),
    ("usd_month", "Monthly lump sum ($/month)"),
    ("usd_year", "Annual lump sum ($/year)"),
]
RATE_UNIT_SUFFIX = {
    "usd_total": "",
    "usd_sf_year": "/SF/yr",
    "usd_sf_month": "/SF/mo",
    "usd_month": "/mo",
    "usd_year": "/yr",
}

VERIFICATION_CHOICES = [
    ("unverified", "Unverified"),
    ("marketing", "Marketing statement (unverified)"),
    ("verified", "Verified"),
    ("conflicting", "Conflicting sources"),
]

REPRESENTED_SIDES = [
    ("buyer", "Buyer"),
    ("seller", "Seller"),
    ("landlord", "Landlord"),
    ("tenant", "Tenant"),
]

TIME_ZONES = [
    ("America/Chicago", "Central (America/Chicago)"),
    ("America/New_York", "Eastern (America/New_York)"),
    ("America/Denver", "Mountain (America/Denver)"),
    ("America/Phoenix", "Arizona (America/Phoenix)"),
    ("America/Los_Angeles", "Pacific (America/Los_Angeles)"),
    ("UTC", "UTC"),
]
