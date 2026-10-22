"""Demo-mode sample data.

Everything here is fictional and labeled "SAMPLE"/"(Demo)". It runs only against the
isolated demo database (DEALDESK_DEMO=1). It shows the key-date timelines and SKW
commission figures the way a real workspace would. See docs/DEMO.md.
"""
import os
from datetime import timedelta

from django.utils import timezone

from checklists.services import apply_template, template_for
from commissions import simple
from core.models import User
from crm.models import Contact, Organization
from deals import keydates, listing
from deals import services as deal_services
from deals.models import DealParty, Representation, Stage
from properties.models import Property

DEMO_PASSWORD = os.environ.get("DEALDESK_DEMO_PASSWORD", "dealdesk-demo-only")


def _user(username, first, last, role, **extra):
    u, _ = User.objects.get_or_create(username=username, defaults={"first_name": first, "last_name": last, "role": role,
                                                                    "email": f"{username}@example.invalid", **extra})
    u.set_password(DEMO_PASSWORD)
    u.save()
    return u


def _prop(name, street, ptype):
    return Property.objects.create(name=name, street=street, city="Houston", state="TX", property_type=ptype)


def _deal(actor, name, prop, ttype, stage, side, client, **fields):
    deal = deal_services.create_deal(actor, properties=[prop] if prop else [], name=name, transaction_type=ttype,
                                     stage=Stage.objects.get(key=stage), responsible_broker=actor, client=client, **fields)
    Representation.objects.create(deal=deal, side=side, is_skw=True, broker_user=actor)
    DealParty.objects.create(deal=deal, role=side, organization=client)
    tpl = template_for(deal)
    if tpl:
        apply_template(deal, tpl, {}, actor)
    return deal


def seed(today=None, log=print):
    today = today or timezone.localdate()
    ago = lambda n: today - timedelta(days=n)  # noqa: E731
    ahead = lambda n: today + timedelta(days=n)  # noqa: E731

    _user("demo-admin", "Avery", "Admin (Demo)", "admin", is_staff=True)
    broker = _user("demo-broker", "Dana", "Broker (Demo)", "broker", is_designated_broker=True,
                   job_title="Designated broker (demo)")
    _user("demo-coordinator", "Casey", "Coordinator (Demo)", "coordinator")
    _user("demo-viewer", "Riley", "Viewer (Demo)", "read_only")
    log("Users created (password in docs/DEMO.md).")

    clients = {n: Organization.objects.create(name=f"SAMPLE {n} (Demo)", org_type="client_entity")
               for n in ["Gessner Partners", "Westpark Holdings", "Kirby Dental", "Bayou Logistics", "Harbor Cafe Group",
                         "Example Industrial Trust"]}
    title_co = Organization.objects.create(name="Example Title Company (Demo)", org_type="title_company")
    Contact.objects.create(first_name="Erin", last_name="Escrow (Demo)", organization=title_co, roles="Escrow officer",
                           email="escrow@example.invalid")

    # 1. Purchase in the Feasibility Period.
    d1 = _deal(broker, "SAMPLE Gessner office purchase", _prop("SAMPLE 1550 Gessner Rd", "1550 Gessner Rd", "office"),
               "purchase", "due_diligence", "buyer", clients["Gessner Partners"])
    keydates.save(d1, {"effective_date": ago(18), "feasibility_days": 30, "closing_mode": "days", "closing_days": 60}, broker)
    simple.set_expected(d1, 8_550_000, broker)

    # 2. Listing past Feasibility, fixed Closing Date, weekend rule from the contract.
    d2 = _deal(broker, "SAMPLE Westpark retail center sale", _prop("SAMPLE 9800 Westpark Dr", "9800 Westpark Dr", "retail"),
               "sale", "preparing_to_close", "seller", clients["Westpark Holdings"])
    keydates.save(d2, {"effective_date": ago(52), "feasibility_days": 30, "closing_mode": "date", "closing_date": ahead(12),
                       "next_business_day": True}, broker)
    simple.set_expected(d2, 12_000_000, broker)

    # 3. Tenant-side lease with a Commencement Date.
    d3 = _deal(broker, "SAMPLE Kirby dental suite lease", _prop("SAMPLE 2400 Kirby Dr", "2400 Kirby Dr", "office"),
               "lease", "under_contract", "tenant", clients["Kirby Dental"])
    keydates.save(d3, {"effective_date": ago(9), "commencement_date": ahead(48)}, broker)
    simple.set_expected(d3, 1_840_000, broker)

    # 4. Just signed; key dates not entered yet, commission unknown.
    _deal(broker, "SAMPLE Harbor Cafe business sale", None, "business_asset", "negotiating", "seller",
          clients["Harbor Cafe Group"])

    # 5. On hold.
    d5 = _deal(broker, "SAMPLE Bayou warehouse purchase", _prop("SAMPLE 77 Bayou Industrial Ct", "77 Bayou Industrial Ct",
                                                                   "industrial"),
               "purchase", "on_hold", "buyer", clients["Bayou Logistics"])
    keydates.save(d5, {"effective_date": ago(40), "feasibility_days": 45, "closing_mode": "days", "closing_days": 90}, broker)
    simple.set_expected(d5, 6_200_000, broker)

    # 6. Closed sale, paid in two parts; an earlier terminated attempt on the same property.
    industrial = _prop("SAMPLE 1200 Example Industrial Pkwy", "1200 Example Industrial Pkwy", "industrial")
    _deal(broker, "SAMPLE 2025 acquisition attempt — Example Industrial", industrial, "purchase", "terminated", "buyer",
          clients["Example Industrial Trust"], termination_reason="Buyer terminated during the Feasibility Period (demo).")
    d6 = _deal(broker, "SAMPLE Example Industrial sale", industrial, "sale", "under_contract", "seller",
               clients["Example Industrial Trust"])
    keydates.save(d6, {"effective_date": ago(110), "feasibility_days": 30, "closing_mode": "days", "closing_days": 75}, broker)
    simple.set_expected(d6, 9_600_000, broker)
    deal_services.close_deal(d6, broker, actual_closing_date=ago(35), total_cents=640_000_000)
    simple.record_receipt(d6, 4_800_000, ago(33), broker, reference="Wire SAMPLE-001")
    simple.record_receipt(d6, 4_800_000, ago(5), broker, reference="Check SAMPLE-1042")

    # 7. Listings: on the market, SKW representing the seller / landlord.
    for n in ["Westheimer Pad Owner", "Memorial Office Partners", "Katy Flex Holdings", "Clinic Group"]:
        clients[n] = Organization.objects.create(name=f"SAMPLE {n} (Demo)", org_type="client_entity")
    l1 = _deal(broker, "SAMPLE Westheimer retail pad sale", _prop("SAMPLE 4100 Westheimer Rd", "4100 Westheimer Rd", "retail"),
               "sale", "listed", "seller", clients["Westheimer Pad Owner"])
    listing.save(l1, {"listing_date": ago(64), "listing_expires_on": ahead(20), "asking_price_cents": 245_000_000,
                      "asking_price_unit": "usd_total"}, broker)
    simple.set_expected(l1, 7_350_000, broker)
    l2 = _deal(broker, "SAMPLE Memorial office suite lease", _prop("SAMPLE 9 Memorial City Way", "9 Memorial City Way", "office"),
               "lease", "listed", "landlord", clients["Memorial Office Partners"])
    listing.save(l2, {"listing_date": ago(21), "listing_expires_on": ahead(160), "asking_price_cents": 2_850,
                      "asking_price_unit": "usd_sf_year"}, broker)
    l3 = _deal(broker, "SAMPLE Katy flex building sale", _prop("SAMPLE 2200 Katy Fwy", "2200 Katy Fwy", "industrial"),
               "sale", "loi", "seller", clients["Katy Flex Holdings"])
    listing.save(l3, {"listing_date": ago(90), "listing_expires_on": ahead(90), "asking_price_cents": 590_000_000,
                      "asking_price_unit": "usd_total"}, broker)
    simple.set_expected(l3, 17_700_000, broker)

    # 8. A buyer search not yet under contract.
    _deal(broker, "SAMPLE Medical office search", None, "purchase", "touring", "buyer", clients["Clinic Group"])
    log("Sample deals created.")
