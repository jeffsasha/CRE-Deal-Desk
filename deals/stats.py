"""Deals header totals: sales and lease consideration by actual closing date,
and actual SKW cash received by receipt date, including active deals.

Each closed deal is counted once. Sales and lease consideration are never added
together; business-asset sales are reported on their own line. Unknown amounts are
counted separately, never as zero.
"""
from dataclasses import dataclass, field

from commissions import simple
from reports.services import cash_receipts, filters_from_params

from .models import BUSINESS_TYPES, LEASE_TYPES, Deal, Stage


@dataclass
class ClosedTotals:
    count: int = 0
    sales: int = 0
    sales_count: int = 0
    sales_unknown: int = 0
    leases: int = 0
    lease_count: int = 0
    lease_unknown: int = 0
    business: int = 0
    business_count: int = 0
    commission: int = 0
    commission_unknown: int = 0
    received: int = 0
    years: list = field(default_factory=list)


def closed_deals(year=None):
    qs = Deal.objects.filter(archived_at__isnull=True, stage__category=Stage.CATEGORY_CLOSED,
                             actual_closing_date__isnull=False)
    if year:
        qs = qs.filter(actual_closing_date__year=year)
    return qs


def closed_years():
    dates = Deal.objects.filter(archived_at__isnull=True, stage__category=Stage.CATEGORY_CLOSED,
                                actual_closing_date__isnull=False).dates("actual_closing_date", "year", order="DESC")
    return [d.year for d in dates]


def totals(year=None, with_commission=True):
    t = ClosedTotals(years=closed_years())
    if with_commission:
        all_receipts = cash_receipts(filters_from_params({}))
        t.years = sorted(set(t.years) | {row["entry"].entry_date.year for row in all_receipts["rows"]}, reverse=True)
        t.received = cash_receipts(filters_from_params({"year": year}))["total"] if year else all_receipts["total"]
    for deal in closed_deals(year):
        t.count += 1
        if deal.transaction_type in LEASE_TYPES:
            t.lease_count += 1
            if deal.lease_total_consideration_cents is None:
                t.lease_unknown += 1
            else:
                t.leases += deal.lease_total_consideration_cents
        elif deal.transaction_type in BUSINESS_TYPES:
            t.business_count += 1
            t.business += deal.actual_closing_price_cents or 0
        else:
            t.sales_count += 1
            if deal.actual_closing_price_cents is None:
                t.sales_unknown += 1
            else:
                t.sales += deal.actual_closing_price_cents
        if with_commission:
            c = simple.for_deal(deal)
            if c.expected is None:
                t.commission_unknown += 1
            else:
                t.commission += c.expected
    return t
