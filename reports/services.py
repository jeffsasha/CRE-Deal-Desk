"""Reporting. The dashboard and the Reports screens both call these functions, so the
numbers on each are the same by construction, and every total carries the records
that produced it.

Rules:
- Closed sales volume uses each deal's deal-level actual consideration exactly once,
  dated by the actual closing date. Property allocations are never added on top.
- Lease consideration and business-asset consideration are reported separately and
  labeled; they are never added to sales volume.
- Unknown amounts are counted as unknown, never as zero.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from commissions.ledger import effective_entries, summarize
from commissions.models import CommissionAgreement, CommissionInstallment, LedgerEntry
from core.money import Total
from deals.models import BUSINESS_TYPES, LEASE_TYPES, SALE_TYPES, Deal, Stage


@dataclass
class Filters:
    start: date | None = None
    end: date | None = None
    label: str = "All dates"
    client: int | None = None
    property_type: str = ""
    transaction_type: str = ""
    side: str = ""
    broker: int | None = None
    title_company: int | None = None

    def querystring(self):
        from urllib.parse import urlencode

        params = {
            "start": self.start.isoformat() if self.start else "",
            "end": self.end.isoformat() if self.end else "",
            "client": self.client or "",
            "property_type": self.property_type,
            "transaction_type": self.transaction_type,
            "side": self.side,
            "broker": self.broker or "",
            "title_company": self.title_company or "",
        }
        return urlencode({k: v for k, v in params.items() if v})


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def filters_from_params(params, default_year=None):
    f = Filters()
    year = _int(params.get("year"))
    quarter = _int(params.get("quarter"))
    month = _int(params.get("month"))
    if params.get("start") or params.get("end"):
        f.start, f.end = _date(params.get("start")), _date(params.get("end"))
        f.label = f"{f.start or '…'} to {f.end or '…'}"
    elif year or default_year:
        year = year or default_year
        if month:
            f.start = date(year, month, 1)
            f.end = (date(year + (month == 12), month % 12 + 1, 1)) - timedelta(days=1)
            f.label = f.start.strftime("%B %Y")
        elif quarter:
            m = (quarter - 1) * 3 + 1
            f.start = date(year, m, 1)
            f.end = (date(year + (m + 3 > 12), (m + 2) % 12 + 1, 1)) - timedelta(days=1)
            f.label = f"Q{quarter} {year}"
        else:
            f.start, f.end = date(year, 1, 1), date(year, 12, 31)
            f.label = str(year)
    f.client = _int(params.get("client"))
    f.property_type = params.get("property_type", "") or ""
    f.transaction_type = params.get("transaction_type", "") or ""
    f.side = params.get("side", "") or ""
    f.broker = _int(params.get("broker"))
    f.title_company = _int(params.get("title_company"))
    return f


def _in_range(qs, field, f):
    if f.start:
        qs = qs.filter(**{f"{field}__gte": f.start})
    if f.end:
        qs = qs.filter(**{f"{field}__lte": f.end})
    return qs


def filter_deals(qs, f):
    qs = qs.filter(archived_at__isnull=True)
    if f.client:
        qs = qs.filter(client_id=f.client)
    if f.property_type:
        qs = qs.filter(deal_properties__property__property_type=f.property_type)
    if f.transaction_type:
        qs = qs.filter(transaction_type=f.transaction_type)
    if f.side:
        qs = qs.filter(representations__is_skw=True, representations__side=f.side)
    if f.broker:
        qs = qs.filter(Q(responsible_broker_id=f.broker) | Q(representations__broker_user_id=f.broker))
    if f.title_company:
        qs = qs.filter(parties__role="title_company", parties__organization_id=f.title_company)
    return qs.distinct()


def _closed(types, f):
    qs = Deal.objects.filter(transaction_type__in=types, stage__category=Stage.CATEGORY_CLOSED)
    qs = _in_range(filter_deals(qs, f), "actual_closing_date", f)
    return qs.select_related("stage", "client").order_by("actual_closing_date")


def closed_sales_volume(f):
    deals = list(_closed(SALE_TYPES, f))
    total = Total()
    for d in deals:
        total.add(d.actual_closing_price_cents, d)
    return {"label": "Closed sales volume (by actual closing date)", "deals": deals, "total": total}


def closed_business_asset_volume(f):
    deals = list(_closed(BUSINESS_TYPES, f))
    total = Total()
    for d in deals:
        total.add(d.actual_closing_price_cents, d)
    return {"label": "Business asset sales — consideration (reported separately)", "deals": deals, "total": total}


def executed_leases(f):
    deals = list(_closed(LEASE_TYPES, f))
    consideration = Total()
    area = 0
    area_unknown = 0
    for d in deals:
        consideration.add(d.lease_total_consideration_cents, d)
        if d.lease_area_sf is None:
            area_unknown += 1
        else:
            area += d.lease_area_sf
    return {
        "label": "Executed leases (by execution date) — not included in sales volume",
        "deals": deals,
        "count": len(deals),
        "area_sf": area,
        "area_unknown": area_unknown,
        "consideration": consideration,
    }


def expected_value(deal):
    """Best available expected value for an active deal, with its label."""
    if deal.executed_contract_price_cents is not None:
        return deal.executed_contract_price_cents, "Executed contract price"
    latest = deal.price_events.filter(kind__in=["counteroffer", "offer", "asking"]).order_by("-event_date", "-id").first()
    if latest:
        return latest.amount_cents, latest.get_kind_display()
    return None, "Unknown"


def pipeline(f):
    qs = filter_deals(Deal.objects.filter(stage__category=Stage.CATEGORY_ACTIVE), f).select_related("stage")
    sales, leases = Total(), Total()
    rows = []
    for d in qs:
        value, basis = expected_value(d)
        if d.is_lease:
            leases.add(d.lease_total_consideration_cents, d)
        else:
            sales.add(value, d)
        rows.append({"deal": d, "value": value if not d.is_lease else d.lease_total_consideration_cents, "basis": basis})
    return {
        "label": "Expected pipeline (active deals, not closed)",
        "rows": rows,
        "sales_total": sales,
        "lease_total": leases,
    }


def _agreements(f):
    deals = filter_deals(Deal.objects.all(), f)
    return CommissionAgreement.objects.filter(deal__in=deals, archived_at__isnull=True).exclude(status="void")


def earned_commissions(f):
    qs = CommissionInstallment.objects.filter(earned_status="earned", agreement__in=_agreements(f))
    qs = _in_range(qs, "earned_on", f).select_related("agreement__deal").order_by("earned_on")
    total = Total()
    for inst in qs:
        total.add(inst.amount_cents, inst)
    return {"label": "Commissions earned (by earned date, amounts due to SKW)", "rows": list(qs), "total": total}


def _ledger_rows(f, kinds, designated_broker_only=False):
    entries = LedgerEntry.objects.filter(agreement__in=_agreements(f)).select_related(
        "agreement__deal", "reverses__allocation__recipient_user", "allocation__recipient_user"
    )
    entries = _in_range(entries, "entry_date", f).order_by("entry_date", "id")
    rows, total = [], 0
    for entry, kind, cents, _alloc in effective_entries(entries):
        if kind not in kinds:
            continue
        if designated_broker_only:
            alloc = entry.reverses.allocation if entry.entry_type == "reversal" else entry.allocation
            if not alloc or not alloc.is_designated_broker:
                continue
        rows.append({"entry": entry, "cents": cents, "kind": kind})
        total += cents
    return rows, total


def cash_receipts(f):
    rows, total = _ledger_rows(f, {"receipt"})
    return {"label": "Cash received by SKW (by receipt date, net of refunds and reversals)", "rows": rows, "total": total}


def designated_broker_receipts(f):
    rows, total = _ledger_rows(f, {"distribution", "direct_payment"}, designated_broker_only=True)
    return {"label": "Designated broker's actual receipts (by payment date)", "rows": rows, "total": total}


def distributions(f):
    rows, total = _ledger_rows(f, {"distribution", "direct_payment"})
    return {"label": "Distributions paid (by payment date)", "rows": rows, "total": total}


def outstanding_balances(f, today=None):
    """As of today; period filters do not apply to balances."""
    today = today or timezone.localdate()
    agreements = (
        CommissionAgreement.objects.filter(
            deal__in=filter_deals(Deal.objects.all(), Filters(**{**f.__dict__, "start": None, "end": None}))
        )
        .exclude(status__in=["void", "draft"])
        .filter(archived_at__isnull=True)
        .select_related("deal")
    )
    receivable = Total()
    unpaid_dist = Total()
    rows = []
    for a in agreements:
        s = summarize(a, today=today)
        if s.outstanding is None or s.outstanding != 0:
            receivable.add(s.outstanding, a)
        dist_unknown = any(ln.allocated is None for ln in s.payer_lines + s.internal_lines if ln.allocation.recipient_type != "skw")
        dist_unpaid = sum(
            ln.unpaid for ln in s.payer_lines + s.internal_lines
            if ln.allocation.recipient_type != "skw" and ln.unpaid is not None and ln.unpaid > 0
        )
        if dist_unknown:
            unpaid_dist.add(None, a)
        elif dist_unpaid:
            unpaid_dist.add(dist_unpaid, a)
        if (s.outstanding or 0) != 0 or s.outstanding is None or dist_unpaid or dist_unknown:
            rows.append({"agreement": a, "summary": s, "dist_unpaid": dist_unpaid, "dist_unknown": dist_unknown})
    return {
        "label": "Outstanding balances (as of today)",
        "rows": rows,
        "receivable": receivable,
        "unpaid_distributions": unpaid_dist,
    }


def pipeline_commissions(f=None):
    """Commission SKW expects to receive on active (not yet closed) deals."""
    qs = CommissionAgreement.objects.filter(deal__stage__category=Stage.CATEGORY_ACTIVE, archived_at__isnull=True)
    qs = qs.exclude(status="void")
    if f is not None:
        qs = qs.filter(deal__in=filter_deals(Deal.objects.all(), f))
    total = Total()
    rows = []
    for a in qs.select_related("deal"):
        s = summarize(a)
        total.add(s.expected_receipt, a)
        rows.append({"agreement": a, "summary": s})
    return {"label": "Expected commissions on active deals (not yet closed)", "rows": rows, "total": total}


def closed_without_commission(f):
    deals = _closed(SALE_TYPES | LEASE_TYPES | BUSINESS_TYPES, f)
    with_agreement = CommissionAgreement.objects.exclude(status="void").values_list("deal_id", flat=True)
    rows = list(deals.exclude(pk__in=with_agreement))
    return {"label": "Closed deals with unknown commission (no agreement recorded)", "deals": rows}


def full_report(f):
    return {
        "sales": closed_sales_volume(f),
        "business": closed_business_asset_volume(f),
        "leases": executed_leases(f),
        "pipeline": pipeline(f),
        "expected": pipeline_commissions(f),
        "earned": earned_commissions(f),
        "receipts": cash_receipts(f),
        "designated": designated_broker_receipts(f),
        "distributions": distributions(f),
        "outstanding": outstanding_balances(f),
        "unknown_commission": closed_without_commission(f),
    }
