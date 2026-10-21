import csv

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.choices import PROPERTY_TYPES, REPRESENTED_SIDES
from core.models import User
from core.money import format_cents
from core.permissions import has_perm, require, require_perm
from crm.models import Organization
from deals.models import TRANSACTION_TYPES

from . import services

FINANCIAL = {"earned", "receipts", "designated", "distributions", "outstanding", "expected"}
METRICS = {
    "sales": ("Closed sales volume", services.closed_sales_volume),
    "business": ("Business asset sales", services.closed_business_asset_volume),
    "leases": ("Executed leases", services.executed_leases),
    "pipeline": ("Expected pipeline", services.pipeline),
    "unknown_commission": ("Closed deals with unknown commission", services.closed_without_commission),
    "expected": ("Expected commissions (active deals)", services.pipeline_commissions),
    "earned": ("Commissions earned", services.earned_commissions),
    "receipts": ("Cash received by SKW", services.cash_receipts),
    "designated": ("Designated broker's actual receipts", services.designated_broker_receipts),
    "distributions": ("Distributions paid", services.distributions),
    "outstanding": ("Outstanding balances", services.outstanding_balances),
}


def _filter_context(request, f):
    year = timezone.localdate().year
    return {
        "f": f, "years": list(range(year + 1, year - 12, -1)),
        "clients": Organization.objects.filter(is_client=True),
        "title_companies": Organization.objects.filter(org_type="title_company"),
        "brokers": User.objects.exclude(role="read_only"),
        "property_types": PROPERTY_TYPES, "transaction_types": TRANSACTION_TYPES, "sides": REPRESENTED_SIDES,
        "params": request.GET,
    }


@require_perm("view")
def report_index(request):
    f = services.filters_from_params(request.GET, default_year=timezone.localdate().year)
    data = {"sales": services.closed_sales_volume(f), "business": services.closed_business_asset_volume(f),
            "leases": services.executed_leases(f), "pipeline": services.pipeline(f),
            "unknown_commission": services.closed_without_commission(f)}
    if has_perm(request.user, "reports.financial"):
        data.update({"expected": services.pipeline_commissions(f), "earned": services.earned_commissions(f),
                     "receipts": services.cash_receipts(f), "designated": services.designated_broker_receipts(f),
                     "distributions": services.distributions(f), "outstanding": services.outstanding_balances(f)})
    return render(request, "reports/index.html", {**_filter_context(request, f), "r": data, "qs": f.querystring()})


@require_perm("view")
def report_detail(request, metric):
    if metric not in METRICS:
        from django.http import Http404

        raise Http404
    if metric in FINANCIAL:
        require(request.user, "reports.financial")
    title, fn = METRICS[metric]
    f = services.filters_from_params(request.GET)
    if not any(k in request.GET for k in ("year", "start", "end")) and metric not in {"outstanding", "expected", "pipeline"}:
        f = services.filters_from_params({**request.GET.dict(), "year": timezone.localdate().year})
    result = fn(f)
    if request.GET.get("export") == "csv":
        return _csv(metric, result)
    return render(request, "reports/detail.html", {**_filter_context(request, f), "metric": metric, "title": title,
                                                   "result": result, "qs": f.querystring()})


def _csv(metric, result):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="report-{metric}.csv"'
    w = csv.writer(response)
    if "deals" in result:
        w.writerow(["Deal ID", "Deal", "Type", "Closing / execution date", "Consideration", "Lease consideration", "Lease SF"])
        for d in result["deals"]:
            w.writerow([d.internal_id, d.name, d.get_transaction_type_display(), d.actual_closing_date,
                        format_cents(d.actual_closing_price_cents), format_cents(d.lease_total_consideration_cents),
                        d.lease_area_sf or ""])
    elif metric == "pipeline":
        w.writerow(["Deal ID", "Deal", "Stage", "Expected value", "Basis"])
        for r in result["rows"]:
            w.writerow([r["deal"].internal_id, r["deal"].name, r["deal"].stage.name, format_cents(r["value"]), r["basis"]])
    elif metric == "earned":
        w.writerow(["Deal", "Installment", "Earned on", "Amount"])
        for i in result["rows"]:
            w.writerow([i.agreement.deal.name, i.label, i.earned_on, format_cents(i.amount_cents)])
    elif metric in {"receipts", "designated", "distributions"}:
        w.writerow(["Entry #", "Date", "Deal", "Type", "Recipient", "Reference", "Signed amount"])
        for r in result["rows"]:
            e = r["entry"]
            w.writerow([e.pk, e.entry_date, e.agreement.deal.name, e.get_entry_type_display(),
                        e.allocation.recipient_name if e.allocation else "", e.reference, format_cents(r["cents"])])
    elif metric in {"outstanding", "expected"}:
        w.writerow(["Agreement", "Deal", "Status", "Expected receipt", "Earned", "Received", "Outstanding"])
        for r in result["rows"]:
            s = r["summary"]
            w.writerow([r["agreement"].title, r["agreement"].deal.name, s.status, format_cents(s.expected_receipt),
                        s.earned.display(), format_cents(s.received), format_cents(s.outstanding)])
    return response
