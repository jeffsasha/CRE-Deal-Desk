"""Default checklist templates. Editable in Settings after seeding.

Title commitment, final owner's title policy, lender's title policy, and property /
casualty insurance are deliberately separate items.
"""

SALE = [
    ("Contract and escrow", [
        ("Executed purchase agreement on file", ""),
        ("All amendments executed and on file", ""),
        ("Effective date confirmed against contract definition", ""),
        ("Escrow opened with title company", ""),
        ("Earnest money receipt confirmed by escrow", ""),
        ("Additional deposit(s) confirmed", ""),
        ("Notice addresses and designated recipients confirmed", ""),
    ]),
    ("Title", [
        ("Title company, branch, escrow officer and file number recorded", ""),
        ("Title commitment received", ""),
        ("Schedule B / C exceptions and requirements reviewed", ""),
        ("Exception documents received and reviewed", ""),
        ("Liens, easements and restrictions reviewed", ""),
        ("Title objection letter delivered (if any)", ""),
        ("Seller cure / response received", ""),
        ("Lien releases obtained", ""),
        ("Updated title commitment received", ""),
    ]),
    ("Survey", [
        ("Existing survey obtained", ""),
        ("New survey ordered", "new_survey"),
        ("Survey received", ""),
        ("Survey reviewed (encroachments, access, exceptions)", ""),
        ("Surveyor certifications correct", ""),
        ("Survey accepted by title company", ""),
        ("Survey accepted by lender", "financing"),
    ]),
    ("Physical and environmental diligence", [
        ("General property inspection", ""),
        ("Roof inspection", ""),
        ("HVAC inspection", ""),
        ("Electrical and plumbing review", ""),
        ("Structural review (if concerns noted)", ""),
        ("Repair estimates obtained", ""),
        ("Phase I environmental site assessment", "environmental"),
        ("Further environmental investigation (if recommended)", "environmental"),
        ("Seller disclosures received", ""),
        ("Seller document gaps identified and requested", ""),
    ]),
    ("Use and governmental matters", [
        ("Flood zone determined and source recorded", ""),
        ("Deed restrictions / permitted use verified", ""),
        ("Zoning or land-use regime verified where applicable", ""),
        ("Permits and certificate of occupancy reviewed", ""),
        ("Utilities confirmed", ""),
        ("Access and parking confirmed", ""),
        ("Operating license / permit dependencies identified", "license_dependency"),
    ]),
    ("Income and tenant diligence", [
        ("Rent roll received", "income_property"),
        ("Leases and amendments received", "income_property"),
        ("Operating statements / financials received", "income_property"),
        ("Security deposits schedule received", "income_property"),
        ("Tenant estoppels received", "income_property"),
        ("SNDAs received", "financing"),
        ("Arrears report reviewed", "income_property"),
        ("CAM reconciliations reviewed", "income_property"),
        ("Service contracts reviewed", "income_property"),
    ]),
    ("Financing and insurance", [
        ("Loan application submitted", "financing"),
        ("Loan commitment received", "financing"),
        ("Appraisal received", "financing"),
        ("Lender conditions satisfied", "financing"),
        ("Property insurance quote received", ""),
        ("Property insurance binder issued", ""),
        ("Property insurance coverage effective at closing", ""),
        ("Lender-required coverage confirmed", "financing"),
    ]),
    ("Closing", [
        ("Closing statement reviewed and approved", ""),
        ("Deed reviewed", ""),
        ("Authority and entity documents delivered", ""),
        ("Prorations and tax items reviewed", ""),
        ("Lien release payoffs confirmed", ""),
        ("Closing funds confirmed by title", ""),
        ("Recording confirmed", ""),
        ("Possession / keys delivered", ""),
        ("Commission payment confirmed at closing", ""),
    ]),
    ("Post-closing", [
        ("Recorded documents received", ""),
        ("Final owner's title insurance policy received", ""),
        ("Lender's title insurance policy received", "lender_title"),
        ("Endorsements received", ""),
        ("Unresolved post-closing items cleared", ""),
        ("Final commission reconciliation", ""),
        ("Archival review", ""),
    ]),
]

LEASE = [
    ("LOI and negotiation", [
        ("LOI executed or terms agreed", ""),
        ("Permitted use confirmed (deed restrictions, exclusives)", ""),
        ("Lease draft received", ""),
        ("Lease comments returned", ""),
    ]),
    ("Execution", [
        ("Lease fully executed", ""),
        ("Guaranty executed", ""),
        ("Security deposit received", ""),
        ("Initial rent received", ""),
        ("Tenant insurance certificate received", ""),
    ]),
    ("Premises and construction", [
        ("Delivery condition confirmed", ""),
        ("TI allowance amount and reimbursement conditions confirmed", "construction"),
        ("Construction plans approved", "construction"),
        ("Building permits issued", "construction"),
        ("Construction complete", "construction"),
        ("Hood, grease trap and food-service utilities confirmed", "restaurant"),
        ("Certificate of occupancy issued", ""),
    ]),
    ("Dates and economics", [
        ("Commencement date confirmed in writing", ""),
        ("Rent commencement date confirmed", ""),
        ("Free rent period recorded", ""),
        ("Rent escalations recorded", ""),
        ("NNN estimates recorded", ""),
        ("Renewal and notice option dates recorded", ""),
    ]),
    ("Commission", [
        ("Commission agreement executed", ""),
        ("Commission installment at execution invoiced", ""),
        ("Commission installment at occupancy / opening invoiced", ""),
    ]),
]

LAND = [
    ("Contract and escrow", [
        ("Executed purchase agreement on file", ""),
        ("Effective date confirmed against contract definition", ""),
        ("Earnest money receipt confirmed by escrow", ""),
    ]),
    ("Title and survey", [
        ("Title commitment received", ""),
        ("Exception documents reviewed", ""),
        ("Survey received", ""),
        ("Survey reviewed (access, encroachments, easements)", ""),
    ]),
    ("Land diligence", [
        ("Flood zone and floodplain determined", ""),
        ("Utilities availability (water, sewer, MUD) confirmed", ""),
        ("Deed restrictions and permitted use verified", ""),
        ("Platting / replat requirements identified", ""),
        ("Phase I environmental site assessment", "environmental"),
        ("Geotechnical report (if needed)", ""),
        ("Wetlands / detention requirements reviewed", ""),
    ]),
    ("Closing", [
        ("Closing statement reviewed", ""),
        ("Recording confirmed", ""),
        ("Final owner's title insurance policy received", ""),
        ("Commission payment confirmed", ""),
    ]),
]

BUSINESS = [
    ("Agreement", [
        ("Executed asset purchase agreement on file", ""),
        ("Asset schedules attached and reviewed", ""),
        ("Inventory count method agreed", ""),
        ("Equipment list and condition confirmed", ""),
    ]),
    ("Dependencies", [
        ("Landlord consent obtained", ""),
        ("New lease executed (linked lease deal)", ""),
        ("Operating licenses / permits transferable or reissued", "license_dependency"),
        ("Tax clearance / sales tax certificate", ""),
    ]),
    ("Closing", [
        ("Bill of sale prepared", ""),
        ("Equipment transfer completed", ""),
        ("Inventory transfer completed", ""),
        ("Closing statement reviewed", ""),
        ("Commission payment confirmed", ""),
    ]),
]

TEMPLATES = [
    ("acquisition", "Acquisition (purchase)", ["purchase"], SALE),
    ("disposition", "Disposition (sale / listing)", ["sale"], SALE),
    ("lease", "Commercial lease", ["lease", "lease_renewal", "lease_expansion", "lease_assignment"], LEASE),
    ("land", "Land acquisition or sale", ["land_purchase", "land_sale"], LAND),
    ("business_asset", "Business asset sale", ["business_asset"], BUSINESS),
]


def ensure_default_templates():
    from .models import ChecklistTemplate, TemplateItem

    for key, name, types, sections in TEMPLATES:
        tpl, created = ChecklistTemplate.objects.get_or_create(key=key, defaults={"name": name, "transaction_types": types})
        if not created and tpl.items.exists():
            continue
        order = 0
        for category, items in sections:
            for title, condition in items:
                order += 10
                TemplateItem.objects.create(template=tpl, category=category, title=title, condition=condition, order=order)
