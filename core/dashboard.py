"""Dashboard metrics. Each metric returns a count/amount and the URL of the list that
shows exactly those records."""
from datetime import timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.permissions import has_perm
from deadlines.models import Deadline
from deals.models import Deal, Stage
from reports import services as reports

TOPICS = {
    "title": (_("Title"), Q(category__iexact="Title")),
    "survey": (_("Survey"), Q(category__iexact="Survey")),
    "insurance": (_("Property insurance"), Q(title__icontains="property insurance")),
    "financing": (_("Financing"), Q(category__iexact="Financing and insurance") & ~Q(title__icontains="insurance")),
    "inspection": (_("Inspections"), Q(category__iexact="Physical and environmental diligence")),
}


def topic_filter(topic):
    return TOPICS[topic][1]


PROGRESS_KINDS = [("all", _("All")), ("sale", _("Sales & acquisitions")), ("lease", _("Leases")), ("business", _("Business assets"))]


def deal_progress(kind="all", with_commission=False):
    """One row per active or on-hold deal: stage, key-date timeline (Effective Date →
    Feasibility Period → Closing Date, or Commencement for leases) and, if allowed,
    SKW's expected and received commission."""
    from commissions import simple
    from deals import keydates, listing
    from deals.models import BUSINESS_TYPES, LEASE_TYPES, SALE_TYPES

    path = list(Stage.objects.filter(enabled=True, category__in=[Stage.CATEGORY_ACTIVE, Stage.CATEGORY_CLOSED])
                .order_by("order"))
    index = {s.pk: i for i, s in enumerate(path)}
    deals = Deal.objects.filter(archived_at__isnull=True,
                                stage__category__in=[Stage.CATEGORY_ACTIVE, Stage.CATEGORY_ON_HOLD])
    types = {"sale": SALE_TYPES, "lease": LEASE_TYPES, "business": BUSINESS_TYPES}.get(kind)
    if types:
        deals = deals.filter(transaction_type__in=types)
    deals = list(deals.select_related("stage").prefetch_related("representations"))
    today = timezone.localdate()
    key_by_deal = {}
    for d in Deadline.objects.filter(deal__in=deals, state="open", template_key__in=keydates.KEY_TEMPLATES):
        key_by_deal.setdefault(d.deal_id, []).append(d)
    rows = []
    for deal in deals:
        current = index.get(deal.stage_id)
        tl = keydates.timeline(deal, key_by_deal.get(deal.pk, []), today)
        nxt = tl["next"]
        rows.append({
            "deal": deal, "tl": tl, "on_hold": deal.stage.category == Stage.CATEGORY_ON_HOLD,
            "position": current if current is not None else -1,
            "stage_no": (current + 1) if current is not None else None, "stage_total": len(path),
            "next": nxt, "next_soon": bool(nxt and nxt["days_left"] is not None and nxt["days_left"] <= 7),
            "skw": simple.for_deal(deal) if with_commission else None,
            "section": listing.section(deal), "property": deal.primary_property,
            "asking": listing.asking_display(deal), "dom": listing.days_on_market(deal, today),
            "expires_soon": bool(deal.listing_expires_on and (deal.listing_expires_on - today).days <= 30),
        })
    far = today + timedelta(days=99999)
    rows.sort(key=lambda r: (r["on_hold"], r["next"]["date"] if r["next"] else far, -r["position"]))
    listings = sorted((r for r in rows if r["section"] == "listing"),
                      key=lambda r: (r["on_hold"], r["deal"].listing_expires_on or far, r["deal"].name))
    return {"rows": rows, "path": path, "kinds": PROGRESS_KINDS, "kind": kind,
            "contract": [r for r in rows if r["section"] == "contract"], "listings": listings,
            "searches": [r for r in rows if r["section"] == "search"]}


def build(user, params):
    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    dl = Deadline.objects.filter(state="open", deal__archived_at__isnull=True,
                                 deal__stage__category__in=[Stage.CATEGORY_ACTIVE, Stage.CATEGORY_ON_HOLD])
    computed = dl.filter(computation="computed")
    url = reverse
    show_money = has_perm(user, "commission.view")
    kind = params.get("kind", "all") if params.get("kind") in dict(PROGRESS_KINDS) else "all"
    progress = deal_progress(kind, with_commission=show_money)
    data = {
        "today": today,
        "progress": progress,
        "deadlines": {
            "overdue": (computed.filter(current_date__lt=today).exclude(category="feasibility").count(), f"{url('deadline_list')}?bucket=overdue"),
            "week": (computed.filter(current_date__gte=today, current_date__lte=week_end).count(), f"{url('deadline_list')}?bucket=week"),
        },
        "upcoming": list(computed.filter(current_date__gte=today, current_date__lte=today + timedelta(days=14))
                         .select_related("deal").order_by("current_date")[:8]),
        "open_deals": len(progress["rows"]) if kind == "all" else Deal.objects.filter(
            archived_at__isnull=True, stage__category__in=[Stage.CATEGORY_ACTIVE, Stage.CATEGORY_ON_HOLD]).count(),
    }
    if show_money:
        rows = progress["rows"] if kind == "all" else deal_progress("all", with_commission=True)["rows"]
        expected = [r["skw"].expected for r in rows]
        f = reports.filters_from_params({"year": today.year})
        data["fin"] = {
            "expected": sum(x for x in expected if x is not None),
            "expected_unknown": sum(1 for x in expected if x is None),
            "outstanding": sum(r["skw"].outstanding for r in rows if r["skw"].outstanding is not None),
            "received_year": reports.cash_receipts(f)["total"],
            "year": today.year,
        }
    return data
