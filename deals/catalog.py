"""Catalogs of contract terms and trigger events.

Contract terms are values approved from executed documents (or entered manually by a
user). Trigger events are things that actually happened on a date (effective date,
receipt of the title commitment, ...). Deadlines are computed from both by explicit
rules; nothing here supplies a default period.
"""

# key: (label, value type, category, applies to)
#   value types: date, days, cents, text, int, decimal
TERM_CATALOG = {
    "parties": ("Parties", "text", "General", "all"),
    "property_description": ("Property description", "text", "General", "all"),
    "effective_date_definition": ("Effective date definition", "text", "Dates", "all"),
    "purchase_price": ("Purchase price", "cents", "Economics", "sale"),
    "earnest_money_amount": ("Earnest money amount", "cents", "Earnest money", "sale"),
    "earnest_money_holder": ("Earnest money holder / escrow agent", "text", "Earnest money", "sale"),
    "earnest_money_deposit_days": ("Earnest money deposit period (days after effective date)", "days", "Earnest money", "sale"),
    "earnest_money_refundability": ("Earnest money refundability conditions", "text", "Earnest money", "sale"),
    "additional_deposit_amount": ("Additional deposit amount", "cents", "Earnest money", "sale"),
    "additional_deposit_trigger": ("Additional deposit / go-hard trigger", "text", "Earnest money", "sale"),
    "feasibility_period_days": ("Feasibility / inspection period (days)", "days", "Due diligence", "sale"),
    "termination_notice": ("Termination and notice requirements", "text", "Due diligence", "all"),
    "title_commitment_delivery_days": ("Title commitment delivery (days after effective date)", "days", "Title & survey", "sale"),
    "survey_delivery_days": ("Survey delivery (days after effective date)", "days", "Title & survey", "sale"),
    "title_objection_days": ("Title & survey objection period (days after receipt of later of commitment and survey)", "days", "Title & survey", "sale"),
    "cure_period_days": ("Seller cure period (days after objection)", "days", "Title & survey", "sale"),
    "financing_contingency_days": ("Financing contingency (days after effective date)", "days", "Financing", "sale"),
    "appraisal_contingency": ("Appraisal contingency", "text", "Financing", "sale"),
    "closing_date": ("Closing date", "date", "Closing", "sale"),
    "closing_days_after_effective": ("Closing (days after effective date)", "days", "Closing", "sale"),
    "outside_closing_date": ("Outside closing date", "date", "Closing", "sale"),
    "extension_options": ("Extension options", "text", "Closing", "all"),
    "possession_delivery": ("Possession and delivery conditions", "text", "Closing", "all"),
    "notice_recipients": ("Required notices and designated recipients", "text", "Notices", "all"),
    "commission_provision": ("Commission provisions", "text", "Commission", "all"),
    "closing_preconditions": ("Preconditions to closing", "text", "Closing", "all"),
    "weekend_holiday_rule": ("Weekend / holiday extension clause", "text", "Dates", "all"),
    # Lease economics
    "lease_term_months": ("Lease term (months)", "int", "Lease", "lease"),
    "base_rent": ("Base rent (with unit)", "text", "Lease", "lease"),
    "rent_escalations": ("Rent escalations", "text", "Lease", "lease"),
    "nnn_estimate": ("NNN / operating expense estimate", "text", "Lease", "lease"),
    "security_deposit": ("Security deposit", "cents", "Lease", "lease"),
    "ti_allowance": ("Tenant improvement allowance", "text", "Lease", "lease"),
    "free_rent": ("Free / abated rent", "text", "Lease", "lease"),
    "commencement_date": ("Commencement date", "date", "Lease", "lease"),
    "rent_commencement": ("Rent commencement", "text", "Lease", "lease"),
    "permitted_use": ("Permitted use", "text", "Lease", "lease"),
    "renewal_options": ("Renewal / notice options", "text", "Lease", "lease"),
    "guaranty": ("Guaranty", "text", "Lease", "lease"),
    "lease_total_consideration": ("Total lease consideration (as stated or calculated)", "cents", "Lease", "lease"),
}

TERM_CATEGORY_ORDER = [
    "General", "Dates", "Economics", "Earnest money", "Due diligence", "Title & survey",
    "Financing", "Closing", "Notices", "Commission", "Lease",
]

# Events that trigger deadlines. Each must be recorded with the actual date it
# occurred; upload dates are never substituted.
EVENT_CATALOG = {
    "effective_date": "Effective date (as defined in the contract)",
    "title_commitment_received": "Title commitment received",
    "title_documents_received": "Title exception documents received",
    "survey_received": "Survey received",
    "seller_documents_delivered": "Seller due diligence documents delivered",
    "title_objection_delivered": "Title / survey objection notice delivered",
    "feasibility_termination_notice": "Feasibility termination notice delivered",
    "financing_approval": "Financing approval received",
    "appraisal_received": "Appraisal received",
    "lease_execution": "Lease fully executed",
    "landlord_consent": "Landlord consent received",
    "delivery_of_premises": "Premises delivered",
    "occupancy": "Tenant occupancy / opening",
    "permit_issued": "Building permit issued",
    "closing": "Closing occurred",
}


def term_label(key):
    return TERM_CATALOG.get(key, (key.replace("_", " ").capitalize(),))[0]


def term_type(key):
    entry = TERM_CATALOG.get(key)
    return entry[1] if entry else "text"


def event_label(key):
    return EVENT_CATALOG.get(key, key.replace("_", " ").capitalize())
