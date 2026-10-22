"""Listings: deals where SKW represents the seller or landlord and the property is on
the market. A listing is a deal that has not reached a contract stage; once it goes
Under Contract it moves to the Under Contract section of the dashboard.

The listing agreement expiration date becomes a fixed-date deadline so it appears on
the calendar and gets the normal reminders.
"""
from django.db import transaction
from django.utils import timezone

from core.audit import audit
from core.choices import RATE_UNIT_SUFFIX
from deadlines.services import create_deadline, recompute, set_state

from .models import PriceEvent, Stage, log_activity

LISTING_SIDES = {"seller", "landlord"}
LISTING_DEADLINE = "listing_expiration"
FIELDS = ["listing_date", "listing_expires_on", "asking_price_cents", "asking_price_unit"]


def skw_sides(deal):
    return {r.side for r in deal.representations.all() if r.is_skw}


def is_listing_side(deal):
    return bool(skw_sides(deal) & LISTING_SIDES)


def under_contract(deal):
    """Contract stages, or on hold after an Effective Date was entered."""
    if deal.stage.category == Stage.CATEGORY_ON_HOLD:
        return deal.effective_date is not None
    return deal.stage.is_contract_stage and deal.stage.category == Stage.CATEGORY_ACTIVE


def section(deal):
    """'contract', 'listing' or 'search' for an open (active or on-hold) deal."""
    if under_contract(deal):
        return "contract"
    return "listing" if is_listing_side(deal) else "search"


def asking_display(deal):
    if deal.asking_price_cents is None:
        return None
    dollars = deal.asking_price_cents / 100
    text = f"${dollars:,.0f}" if dollars == int(dollars) else f"${dollars:,.2f}"
    return text + RATE_UNIT_SUFFIX.get(deal.asking_price_unit or "usd_total", "")


def days_on_market(deal, today=None):
    if not deal.listing_date:
        return None
    return ((today or timezone.localdate()) - deal.listing_date).days


@transaction.atomic
def save(deal, data, actor):
    before = {f: getattr(deal, f) for f in FIELDS}
    for f in FIELDS:
        setattr(deal, f, data.get(f) if f != "asking_price_unit" else (data.get(f) or "usd_total"))
    changes = {f: (before[f], getattr(deal, f)) for f in FIELDS if before[f] != getattr(deal, f)}
    if not changes:
        return deal
    deal.save(update_fields=FIELDS + ["updated_at"])
    audit(actor, "deal.listing_updated", deal, changes)
    log_activity(deal, "Listing details updated: " + ", ".join(changes), actor=actor)

    # Asking price history (lump-sum prices only; rents keep their unit on the deal).
    if "asking_price_cents" in changes and deal.asking_price_cents is not None and deal.asking_price_unit == "usd_total":
        PriceEvent.objects.create(deal=deal, kind="asking", amount_cents=deal.asking_price_cents,
                                  event_date=timezone.localdate(), created_by=actor, notes="Asking price (listing)")

    if "listing_expires_on" in changes:
        _sync_expiration_deadline(deal, actor)
    return deal


def _sync_expiration_deadline(deal, actor):
    current = deal.deadlines.filter(template_key=LISTING_DEADLINE, state="open").first()
    if deal.listing_expires_on is None:
        if current:
            set_state(current, "cancelled", actor, "Listing expiration removed")
        return
    if current is None:
        create_deadline(actor=actor, deal=deal, name="Listing agreement expires", category="other", rule_type="fixed",
                        fixed_date=deal.listing_expires_on, template_key=LISTING_DEADLINE, is_contractual=True,
                        confirmation="confirmed", responsible_user=deal.responsible_broker, time_zone=deal.time_zone,
                        source_clause="Listing agreement (entered on the listing form)")
    else:
        current.fixed_date = deal.listing_expires_on
        current.save(update_fields=["fixed_date", "updated_at"])
        recompute(current, actor=actor, reason="Listing expiration changed")
