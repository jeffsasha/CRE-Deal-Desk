"""Demo-mode sample data.

Everything here is fictional and labeled "SAMPLE"/"(Demo)". It runs only against the
isolated demo database (DEALDESK_DEMO=1) and is arranged so each acceptance flow can
be seen in the running application. See docs/DEMO.md.
"""
import os
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from checklists.services import apply_template
from checklists.models import ChecklistTemplate
from commissions.models import CommissionAgreement, CommissionAllocation, CommissionInstallment
from commissions.services import record_entry
from core.models import User
from crm.models import Contact, Organization
from deadlines.reminders import deliver_due
from deadlines.services import generate_standard_deadlines
from deals import services as deal_services
from deals.models import Activity, CommunicationDraft, DealLink, DealParty, Deposit, Issue, IssueStatement, PriceEvent, Representation, Stage
from deals.drafts import title_status
from documents import services as doc_services
from documents.processing import read_text, run_extraction
from imports import services as import_services
from properties.models import Parcel, Property, PropertyFact, Space

from . import pdf, samples

DEMO_PASSWORD = os.environ.get("DEALDESK_DEMO_PASSWORD", "dealdesk-demo-only")


def _user(username, first, last, role, **extra):
    u, _ = User.objects.get_or_create(username=username, defaults={"first_name": first, "last_name": last, "role": role,
                                                                    "email": f"{username}@example.invalid", **extra})
    u.set_password(DEMO_PASSWORD)
    u.save()
    return u


def _upload(actor, data, filename, **kwargs):
    f = SimpleUploadedFile(filename, data, content_type="application/pdf")
    version, _ = doc_services.upload(f, actor, process=False, **kwargs)
    return version


def _process(version, actor):
    read_text(version)
    version.refresh_from_db()
    return run_extraction(version, actor_id=actor.pk)


def _accept_confident(run, actor, keys=None):
    for f in run.fields.all():
        if f.review_status == "pending" and (keys is None or f.key in keys):
            doc_services.review_field(f, actor, "accept", note="Reviewed against the document (demo seed)")


def seed(today=None, log=print):
    today = today or timezone.localdate()
    o = samples.offsets(today)

    admin = _user("demo-admin", "Avery", "Admin (Demo)", "admin", is_staff=True)
    broker = _user("demo-broker", "Dana", "Broker (Demo)", "broker", is_designated_broker=True,
                   job_title="Designated broker (demo)", email_reminders=True)
    coord = _user("demo-coordinator", "Casey", "Coordinator (Demo)", "coordinator")
    _user("demo-viewer", "Riley", "Viewer (Demo)", "read_only")
    log("Users created (password in docs/DEMO.md).")

    title_co = Organization.objects.create(name="Example Title Company (Demo)", org_type="title_company",
                                           branch_name="Sample Galleria branch", phone="(000) 555-0100")
    escrow = Contact.objects.create(first_name="Erin", last_name="Escrow (Demo)", organization=title_co,
                                    roles="Escrow officer", email="escrow@example.invalid", phone="(000) 555-0101")
    survey_co = Organization.objects.create(name="Sample Survey Co. (Demo)", org_type="surveyor")
    surveyor = Contact.objects.create(first_name="Sam", last_name="Surveyor (Demo)", organization=survey_co, roles="Surveyor",
                                      email="survey@example.invalid")
    lender = Organization.objects.create(name="Sample Community Bank (Demo)", org_type="lender")
    coop = Organization.objects.create(name="Sample Cooperating Brokerage (Demo)", org_type="brokerage")
    inspector_co = Organization.objects.create(name="Sample Inspections (Demo)", org_type="inspection")
    client_a = Organization.objects.create(name="Sample Buyer Holdings LLC", org_type="client_entity", is_client=True)
    client_b = Organization.objects.create(name="Sample Logistics Partners LLC", org_type="client_entity", is_client=True)
    client_c = Organization.objects.create(name="Sample Holdings Trust", org_type="client_entity", is_client=True)
    Contact.objects.create(first_name="Lee", last_name="Sample", organization=client_a, is_client=True, title="Manager",
                           email="lee@example.invalid", phone="(000) 555-0123")
    stage = {s.key: s for s in Stage.objects.all()}

    # --- Flow 1: one property, a terminated deal and a later closed deal --------------
    p1 = Property.objects.create(name="SAMPLE 1200 Example Industrial Pkwy", street="1200 Example Industrial Pkwy",
                                 city="Houston", postal_code="77000", county="Harris", property_type="industrial",
                                 building_area_sf=Decimal("48000"), land_area_sf=Decimal("196000"),
                                 size_source="Appraisal district record (sample)", size_verified_on=today - timedelta(days=400),
                                 ownership_entity="Sample Industrial Owner LP")
    Parcel.objects.create(property=p1, parcel_id="SAMPLE-0001-0001", county="Harris", land_area_sf=Decimal("120000"))
    Parcel.objects.create(property=p1, parcel_id="SAMPLE-0001-0002", county="Harris", land_area_sf=Decimal("76000"))
    PropertyFact.objects.create(property=p1, category="industrial", key="clear_height", label="Clear height", value="24", unit="ft",
                                source="Listing flyer (sample)", verification="marketing")
    PropertyFact.objects.create(property=p1, category="industrial", key="dock_high_doors", label="Dock-high doors", value="6",
                                source="Site visit notes", verification="unverified")
    PropertyFact.objects.create(property=p1, category="flood", key="flood_zone", label="FEMA flood zone", value="Zone X (unshaded)",
                                source="FEMA flood map viewer, panel SAMPLE (fictional)", verification="verified",
                                verified_by=broker, verified_on=today - timedelta(days=300))
    deal_a = deal_services.create_deal(admin, properties=[p1], name="SAMPLE 1200 Example Industrial — 2025 acquisition attempt",
                                       transaction_type="purchase", stage=stage["negotiating"], client=client_a,
                                       responsible_broker=broker)
    for kind, amt, days in [("asking", 260000000, 420), ("offer", 230000000, 410), ("counteroffer", 250000000, 405)]:
        PriceEvent.objects.create(deal=deal_a, kind=kind, amount_cents=amt, event_date=today - timedelta(days=days),
                                  created_by=broker, party="Seller" if kind != "offer" else "Buyer")
    Issue.objects.create(deal=deal_a, property=p1, title="Roof membrane failure noted in inspection", category="roof",
                         severity="high", status="closed", discovered_on=today - timedelta(days=395),
                         disclosure_finding="not_found", disclosure_note="Not found in the seller materials we reviewed.")
    deal_services.change_stage(deal_a, stage["terminated"], broker,
                               "Buyer terminated during the feasibility period after roof findings (sample).")

    deal_b = deal_services.create_deal(admin, properties=[p1], name="SAMPLE 1200 Example Industrial — 2026 sale to Sample Holdings Trust",
                                       transaction_type="purchase", stage=stage["preparing_to_close"], client=client_c,
                                       responsible_broker=broker)
    Representation.objects.create(deal=deal_b, side="buyer", is_skw=True, broker_user=broker)
    DealParty.objects.create(deal=deal_b, role="title_company", organization=title_co, contact=escrow, file_number="GF-SAMPLE-1001")
    deal_services.set_term(deal_b, "purchase_price", 245000000, broker, note="Demo seed: entered manually")
    closing_b = today - timedelta(days=150)
    deal_services.close_deal(deal_b, broker, actual_closing_date=closing_b, total_cents=245000000,
                             note="Funding and recording confirmed by title (sample).")
    # Flow 11: partial receipts and separate designated-broker distributions.
    ag_b = CommissionAgreement.objects.create(deal=deal_b, title="SAMPLE buyer-side commission — 1200 Example Industrial",
                                              payer=title_co, payer_name="Seller via title at closing", represented_side="buyer",
                                              basis_type="percentage", basis_description="Gross sales price",
                                              basis_amount_cents=245000000, rate_percent=Decimal("3.0"),
                                              earning_conditions="Earned and payable at closing per listing agreement (sample).")
    skw_b = CommissionAllocation.objects.create(agreement=ag_b, level="payer", recipient_type="skw", recipient_name="SKW Realty LLC",
                                                method="percent_of_gross", percent=Decimal("50"))
    CommissionAllocation.objects.create(agreement=ag_b, level="payer", recipient_type="cooperating_broker",
                                        recipient_name=coop.name, recipient_org=coop, method="percent_of_gross",
                                        percent=Decimal("50"), paid_through_skw=False,
                                        notes="Paid directly by title to the cooperating brokerage.")
    db_b = CommissionAllocation.objects.create(agreement=ag_b, level="internal", recipient_type="designated_broker",
                                               recipient_name=broker.display_name, recipient_user=broker,
                                               method="percent_of_skw", percent=Decimal("70"))
    CommissionAllocation.objects.create(agreement=ag_b, level="internal", recipient_type="house", recipient_name="SKW house share",
                                        method="percent_of_skw", percent=Decimal("30"))
    inst_b = CommissionInstallment.objects.create(agreement=ag_b, label="At closing", amount_cents=3675000,
                                                  earned_status="earned", earned_on=closing_b, invoice_number="INV-SAMPLE-101",
                                                  invoice_date=closing_b - timedelta(days=5), due_date=closing_b)
    record_entry(ag_b, broker, entry_type="receipt", amount_cents=2000000, entry_date=closing_b + timedelta(days=4),
                 installment=inst_b, reference="Wire SAMPLE-A")
    record_entry(ag_b, broker, entry_type="receipt", amount_cents=1675000, entry_date=closing_b + timedelta(days=19),
                 installment=inst_b, reference="Check SAMPLE-1188")
    record_entry(ag_b, broker, entry_type="distribution", amount_cents=1400000, entry_date=closing_b + timedelta(days=25),
                 allocation=db_b, reference="ACH SAMPLE-D1", notes="Partial distribution")
    log("Flow 1 and 11: property with terminated + closed deals; partial receipts and distributions.")

    # --- Flows 3 & 4: scanned contract, ambiguous effective date ---------------------
    p2 = Property.objects.create(name="SAMPLE 8800 Sample Westpark Dr", street="8800 Sample Westpark Dr", city="Houston",
                                 postal_code="77000", county="Harris", property_type="retail",
                                 building_area_sf=Decimal("22500"))
    deal_c = deal_services.create_deal(admin, properties=[p2], name="SAMPLE Westpark retail center acquisition",
                                       transaction_type="purchase", stage=stage["under_contract"], client=client_a,
                                       responsible_broker=broker, is_blocked=True,
                                       blocked_by="Example Title Company (Demo)",
                                       blocker_description="Title company has not yet acknowledged receipt of the contract and earnest money; the effective date cannot be established.",
                                       next_action="Obtain title company's receipt date", next_action_owner="Escrow officer")
    deal_c.team.add(coord)
    Representation.objects.create(deal=deal_c, side="buyer", is_skw=True, broker_user=broker)
    DealParty.objects.create(deal=deal_c, role="title_company", organization=title_co, contact=escrow, file_number="GF-SAMPLE-2002")
    v_c = _upload(coord, pdf.scanned_pdf(samples.ambiguous_contract(o["c_signed_seller"], o["c_signed_buyer"])),
                  "sample-westpark-contract-scan.pdf", title="SAMPLE Westpark purchase agreement (scanned)",
                  category="contract", deal=deal_c, delivered_on=o["c_signed_buyer"],
                  delivery_evidence="Email from buyer's counsel (sample)")
    run_c = _process(v_c, coord)
    if run_c.status == "succeeded":
        doc_services.set_execution_status(v_c, "confirmed_executed", broker,
                                          "Fully signed copy received from buyer's counsel (sample).")
        _accept_confident(run_c, broker)
        for f in run_c.fields.filter(key="earnest_money_deposit_days", review_status="needs_review"):
            doc_services.review_field(f, broker, "accept", note="Business days — deadline rule set to business days")
        doc_services.publish(run_c, deal_c, broker)
    else:
        log(f"  Scanned contract extraction did not succeed ({run_c.error[:80]}); entering terms manually.")
        for key, value in [("purchase_price", 420000000), ("feasibility_period_days", 60), ("title_commitment_delivery_days", 15),
                           ("survey_delivery_days", 15), ("title_objection_days", 10)]:
            deal_services.set_term(deal_c, key, value, broker, note="Demo seed: entered manually")
    generate_standard_deadlines(deal_c, actor=broker)
    feas_c = deal_c.deadlines.filter(template_key="feasibility_expiration").first()
    if feas_c:
        from deadlines.services import create_deadline

        create_deadline(actor=broker, deal=deal_c, name="Closing date", category="closing", rule_type="offset",
                        trigger_keys=[f"deadline:{feas_c.pk}"], offset_days=30, source_version=v_c, source_page=2,
                        source_section="7. Closing", responsible_user=broker,
                        source_clause="Closing shall occur on or before the thirtieth (30th) day after the expiration of the Feasibility Period.")
    em_c = deal_c.deadlines.filter(template_key="earnest_money_deposit").first()
    if em_c:
        from core.models import HolidayCalendar
        from deadlines.services import recompute

        em_c.day_basis = "business"
        em_c.holiday_calendar = HolidayCalendar.objects.get(code="us-federal")
        em_c.source_clause = "Within three (3) business days after the Effective Date, Buyer shall deposit earnest money..."
        em_c.confirmation = "confirmed"
        em_c.save()
        recompute(em_c, actor=broker, reason="Rule set to business days per contract")
    Deposit.objects.create(deal=deal_c, kind="earnest_money", amount_cents=10000000, holder=title_co, due_deadline=em_c,
                           refundability="needs_review",
                           refundability_note="Refundability depends on termination notice timing; not determined from dates alone.")
    log("Flows 3 & 4: scanned contract reviewed; effective date left unresolved, deadlines await the trigger.")

    # --- Flows 5–10: executed contract, receipts, checklist, HVAC credit, amendments ---
    p3 = Property.objects.create(name="SAMPLE 4400 Sample Gessner Rd", street="4400 Sample Gessner Rd", city="Houston",
                                 postal_code="77000", county="Harris", property_type="warehouse",
                                 building_area_sf=Decimal("36000"), land_area_sf=Decimal("130000"))
    PropertyFact.objects.create(property=p3, category="industrial", key="clear_height", label="Clear height", value="28", unit="ft",
                                source="Survey and site measurement (sample)", verification="verified", verified_by=broker,
                                verified_on=today - timedelta(days=10))
    deal_d = deal_services.create_deal(admin, properties=[p3], name="SAMPLE Gessner warehouse acquisition",
                                       transaction_type="purchase", stage=stage["due_diligence"], client=client_b,
                                       responsible_broker=broker, financing_status="pending",
                                       financing_terms="65% LTV acquisition loan (sample)",
                                       next_action="Review survey exceptions with title", next_action_owner="Dana Broker (Demo)",
                                       next_action_due=today + timedelta(days=2))
    deal_d.team.add(coord)
    Representation.objects.create(deal=deal_d, side="buyer", is_skw=True, broker_user=broker)
    Representation.objects.create(deal=deal_d, side="seller", is_skw=False, broker_name="Seller unrepresented (sample)")
    DealParty.objects.create(deal=deal_d, role="title_company", organization=title_co, contact=escrow, file_number="GF-SAMPLE-3003",
                             is_notice_recipient=True)
    DealParty.objects.create(deal=deal_d, role="surveyor", organization=survey_co, contact=surveyor)
    DealParty.objects.create(deal=deal_d, role="lender", organization=lender)
    DealParty.objects.create(deal=deal_d, role="inspector", organization=inspector_co)
    v_d = _upload(coord, pdf.text_pdf(samples.executed_contract(o["d_effective"], o["d_closing"])),
                  "sample-gessner-contract-executed.pdf", title="SAMPLE Gessner contract of sale (executed)",
                  category="contract", deal=deal_d, delivered_on=o["d_effective"], delivery_evidence="DocuSign completion email (sample)")
    run_d = _process(v_d, coord)
    doc_services.set_execution_status(v_d, "confirmed_executed", broker, "Fully executed copy from title company (sample).")
    _accept_confident(run_d, broker)
    doc_services.publish(run_d, deal_d, broker)
    generate_standard_deadlines(deal_d, actor=broker)
    deal_services.record_event(deal_d, "title_commitment_received", today - timedelta(days=6), broker,
                               evidence_note="Commitment emailed by escrow officer (sample).")
    deal_services.record_event(deal_d, "survey_received", today - timedelta(days=3), broker,
                               evidence_note="Survey PDF received from surveyor (sample).")
    em_d = deal_d.deadlines.filter(template_key="earnest_money_deposit").first()
    Deposit.objects.create(deal=deal_d, kind="earnest_money", amount_cents=7500000, holder=title_co, due_deadline=em_d,
                           sent_on=o["d_effective"] + timedelta(days=2), refundability="unknown",
                           notes="Wire sent; escrow has not confirmed receipt (sample).")
    tpl = ChecklistTemplate.objects.get(key="acquisition")
    apply_template(deal_d, tpl, {"financing": True, "environmental": True, "lender_title": True}, broker)
    items = {i.title: i for i in deal_d.checklist_items.all()}

    def set_item(title, status, **dates):
        it = items[title]
        old = it.status
        it.status = status
        for k, v in dates.items():
            setattr(it, k, v)
        from checklists.services import update_item

        update_item(it, broker, old)

    set_item("Survey received", "received", received_on=today - timedelta(days=3), owner=coord)
    set_item("Survey reviewed (encroachments, access, exceptions)", "under_review", received_on=today - timedelta(days=3),
             owner=broker, follow_up_on=today + timedelta(days=1), unresolved_issues="Possible fence encroachment on east line.")
    set_item("Title commitment received", "received", received_on=today - timedelta(days=6), owner=coord)
    set_item("Schedule B / C exceptions and requirements reviewed", "in_progress", owner=broker)
    set_item("Property insurance quote received", "requested", requested_on=today - timedelta(days=2), owner=coord,
             follow_up_on=today - timedelta(days=1))
    set_item("Executed purchase agreement on file", "approved", approved_on=o["d_effective"], owner=coord)
    set_item("Escrow opened with title company", "approved", approved_on=o["d_effective"] + timedelta(days=1))
    set_item("Earnest money receipt confirmed by escrow", "blocked", blocked_reason="Waiting on escrow receipt confirmation")
    hvac = Issue.objects.create(deal=deal_d, property=p3, title="Rooftop HVAC units near end of service life", category="hvac",
                                severity="high", discovered_on=today - timedelta(days=8), responsible=broker,
                                description="Two of three RTUs are original equipment; inspector recommends replacement.",
                                requested_remedy="Price credit at closing", requested_credit_cents=4500000,
                                estimated_cost_cents=5200000, counterparty_response="Seller is considering; no response yet.",
                                resolution_status="proposed", disclosure_finding="not_found",
                                disclosure_note="HVAC age not found in the seller disclosures we reviewed.")
    IssueStatement.objects.create(issue=hvac, party="Sample Inspections (Demo)", statement="RTU-1 and RTU-2 are beyond typical service life.",
                                  statement_date=today - timedelta(days=8), document_date=today - timedelta(days=9),
                                  delivered_on=today - timedelta(days=8), receipt_evidence="Inspection report emailed (sample)",
                                  recorded_by=broker)
    PriceEvent.objects.create(deal=deal_d, kind="requested_credit", amount_cents=4500000, event_date=today - timedelta(days=7),
                              party="Buyer", issue=hvac, created_by=broker,
                              notes="Requested credit — not an approved price change.")

    # Flow 7: executed amendment — applied, history preserved.
    v_a1 = _upload(coord, pdf.text_pdf(samples.first_amendment(o["d_amended_closing"])), "sample-gessner-first-amendment.pdf",
                   title="SAMPLE First Amendment — Gessner", category="amendment", deal=deal_d)
    run_a1 = _process(v_a1, coord)
    _accept_confident(run_a1, broker)
    amendment1 = doc_services.prepare_amendment(run_a1, deal_d, broker)
    doc_services.set_execution_status(v_a1, "confirmed_executed", broker, "Fully signed by both parties via DocuSign (sample).")
    doc_services.apply_amendment(amendment1, broker)
    # Flow 6: unsigned extension — prepared, but not effective.
    v_ext = _upload(coord, pdf.text_pdf(samples.unsigned_extension(o["d_unsigned_closing"])), "sample-gessner-second-extension-unsigned.pdf",
                    title="SAMPLE Second Amendment (Extension) — unsigned draft", category="amendment", deal=deal_d)
    run_ext = _process(v_ext, coord)
    _accept_confident(run_ext, broker)
    amendment2 = doc_services.prepare_amendment(run_ext, deal_d, broker)
    try:
        doc_services.apply_amendment(amendment2, broker)
    except ValidationError:
        pass  # expected: execution not confirmed
    Activity.objects.create(deal=deal_d, kind="call", direction="outbound", summary="Call with escrow officer re: earnest money receipt",
                            body="Escrow will confirm receipt once the wire posts (sample).", counterparties="Erin Escrow (Demo)",
                            created_by=coord, occurred_at=timezone.now() - timedelta(days=1))
    CommunicationDraft.objects.create(deal=deal_d, created_by=coord, generated_from="title_status", **title_status(deal_d))
    ag_d = CommissionAgreement.objects.create(deal=deal_d, title="SAMPLE buyer-side commission — Gessner", represented_side="buyer",
                                              payer_name="Seller (per contract)", basis_type="percentage",
                                              basis_description="Purchase price", basis_amount_cents=285000000,
                                              rate_percent=Decimal("2.5"), earning_conditions="Earned at closing (sample).")
    CommissionAllocation.objects.create(agreement=ag_d, level="payer", recipient_type="skw", recipient_name="SKW Realty LLC",
                                        method="percent_of_gross", percent=Decimal("100"))
    CommissionAllocation.objects.create(agreement=ag_d, level="internal", recipient_type="designated_broker",
                                        recipient_name=broker.display_name, recipient_user=broker, method="unknown",
                                        notes="Split not yet agreed — left unknown.")
    CommissionInstallment.objects.create(agreement=ag_d, label="At closing", amount_cents=7125000,
                                         trigger_description="Closing and funding")
    log("Flows 5–10: receipt-triggered deadline, survey under review, separate title/insurance items, HVAC credit, amendments.")

    # --- Flow 13: multi-property closing without double counting -------------------
    p4 = Property.objects.create(name="SAMPLE Pad A — 100 Demo Crossing", street="100 Demo Crossing", city="Houston",
                                 postal_code="77000", property_type="retail", land_area_sf=Decimal("43560"))
    p5 = Property.objects.create(name="SAMPLE Pad B — 120 Demo Crossing", street="120 Demo Crossing", city="Houston",
                                 postal_code="77000", property_type="retail", land_area_sf=Decimal("39000"))
    deal_e = deal_services.create_deal(admin, properties=[p4, p5], name="SAMPLE two-pad portfolio sale",
                                       transaction_type="sale", stage=stage["preparing_to_close"], client=client_c,
                                       responsible_broker=broker)
    Representation.objects.create(deal=deal_e, side="seller", is_skw=True, broker_user=broker)
    DealParty.objects.create(deal=deal_e, role="title_company", organization=title_co, file_number="GF-SAMPLE-5005")
    links = list(deal_e.deal_properties.order_by("id"))
    closing_e = today - timedelta(days=40)
    deal_services.close_deal(deal_e, broker, actual_closing_date=closing_e, total_cents=310000000,
                             allocations={links[0].pk: 170000000, links[1].pk: 140000000},
                             note="Single closing; price allocated between pads per contract exhibit (sample).")
    ag_e = CommissionAgreement.objects.create(deal=deal_e, title="SAMPLE listing commission — two-pad sale", represented_side="seller",
                                              basis_type="flat", flat_amount_cents=9300000, payer_name="Seller")
    CommissionAllocation.objects.create(agreement=ag_e, level="payer", recipient_type="skw", recipient_name="SKW Realty LLC",
                                        method="flat", amount_cents=9300000)
    db_e = CommissionAllocation.objects.create(agreement=ag_e, level="internal", recipient_type="designated_broker",
                                               recipient_name=broker.display_name, recipient_user=broker, method="percent_of_skw",
                                               percent=Decimal("50"))
    inst_e = CommissionInstallment.objects.create(agreement=ag_e, label="At closing", amount_cents=9300000, earned_status="earned",
                                                  earned_on=closing_e)
    record_entry(ag_e, broker, entry_type="receipt", amount_cents=9300000, entry_date=closing_e, installment=inst_e, reference="Title disbursement SAMPLE")
    record_entry(ag_e, broker, entry_type="distribution", amount_cents=4650000, entry_date=closing_e + timedelta(days=7), allocation=db_e,
                 reference="ACH SAMPLE-D2")
    log("Flow 13: multi-property deal closed once with explicit allocations.")

    # --- Lease with installments, and a linked business asset sale --------------------
    p6 = Property.objects.create(name="SAMPLE 2300 Demo Market St", street="2300 Demo Market St", city="Houston", postal_code="77000",
                                 property_type="restaurant", building_area_sf=Decimal("9600"))
    space = Space.objects.create(property=p6, suite="100", area_sf=Decimal("3200"), status="leased", condition="second_generation")
    PropertyFact.objects.create(property=p6, space=space, category="restaurant_retail", key="hood", label="Hood",
                                value="Existing 12 ft Type I hood", source="Landlord flyer (sample)", verification="marketing")
    PropertyFact.objects.create(property=p6, space=space, category="restaurant_retail", key="grease_trap",
                                label="Grease trap / interceptor", value="1,000 gallon interceptor", source="City permit record (sample)",
                                verification="verified", verified_by=broker, verified_on=today - timedelta(days=90))
    deal_f = deal_services.create_deal(admin, properties=[p6], name="SAMPLE Demo Market St Suite 100 — restaurant lease",
                                       transaction_type="lease", stage=stage["negotiating"], responsible_broker=broker,
                                       lease_area_sf=Decimal("3200"), lease_term_months=84, lease_starting_rent=Decimal("32.00"),
                                       lease_rent_unit="usd_sf_year")
    deal_f.deal_properties.update(space=space)
    Representation.objects.create(deal=deal_f, side="tenant", is_skw=True, broker_user=broker)
    exec_f = today - timedelta(days=75)
    deal_services.close_deal(deal_f, broker, actual_closing_date=exec_f, total_cents=76500000,
                             note="Lease fully executed (sample). Consideration as stated in the commission agreement.")
    ag_f = CommissionAgreement.objects.create(deal=deal_f, title="SAMPLE tenant-rep lease commission — Demo Market St",
                                              represented_side="tenant", basis_type="percentage",
                                              basis_description="Aggregate base rent, initial term", basis_amount_cents=76500000,
                                              rate_percent=Decimal("6"), payer_name="Landlord",
                                              earning_conditions="One half at lease execution, one half when tenant opens for business (sample).")
    CommissionAllocation.objects.create(agreement=ag_f, level="payer", recipient_type="skw", recipient_name="SKW Realty LLC",
                                        method="percent_of_gross", percent=Decimal("100"))
    i1 = CommissionInstallment.objects.create(agreement=ag_f, sequence=1, label="At lease execution", amount_cents=2295000,
                                              earned_status="earned", earned_on=exec_f, invoice_number="INV-SAMPLE-201",
                                              invoice_date=exec_f, due_date=exec_f + timedelta(days=30))
    CommissionInstallment.objects.create(agreement=ag_f, sequence=2, label="At tenant opening", amount_cents=2295000,
                                         trigger_description="Tenant opens for business",
                                         expected_payment_date=today + timedelta(days=45))
    record_entry(ag_f, broker, entry_type="receipt", amount_cents=2295000, entry_date=exec_f + timedelta(days=21), installment=i1,
                 reference="Landlord check SAMPLE-7781")
    deal_g = deal_services.create_deal(admin, properties=[p6], name="SAMPLE Demo Bistro — business asset purchase",
                                       transaction_type="business_asset", stage=stage["negotiating"], responsible_broker=broker)
    DealLink.objects.create(from_deal=deal_g, to_deal=deal_f, link_type="linked_business_asset",
                            notes="Asset purchase closes only after the new lease is executed.")
    apply_template(deal_g, ChecklistTemplate.objects.get(key="business_asset"), {"license_dependency": True}, broker)
    log("Lease with installment commissions and a linked business asset sale.")

    # --- Flow 2: historical import with known price, unknown commission --------------
    csv_file = SimpleUploadedFile("sample-historical-deals.csv", samples.historical_csv(today).encode(), content_type="text/csv")
    batch = import_services.create_batch(csv_file, "deals", admin)
    import_services.validate_batch(batch)
    import_services.commit_batch(batch, admin)
    log("Flow 2: historical import committed (one row rejected for missing closing date; LOI kept as LOI).")

    # --- Flow 15: extraction failure and reminder delivery failure --------------------
    v_blank = _upload(coord, pdf.scanned_pdf(samples.blank_scan()), "sample-unreadable-scan.pdf",
                      title="SAMPLE unreadable scan (extraction fails gracefully)", category="contract", deal=deal_c)
    _process(v_blank, coord)
    delivered = deliver_due()
    failed = sum(1 for r in delivered if r.status == "failed")
    log(f"Flow 15: unreadable scan stored with a failed extraction; {len(delivered)} reminders processed, {failed} email failures (SMTP not configured).")
    return {"deals": [deal_a, deal_b, deal_c, deal_d, deal_e, deal_f, deal_g], "batch": batch}
