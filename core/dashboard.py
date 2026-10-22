"""Dashboard metrics. Each metric returns a count/amount and the URL of the list that
shows exactly those records."""
from datetime import timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from checklists.models import OPEN_STATUSES, ChecklistItem
from core.permissions import has_perm
from deadlines.models import Deadline, Reminder
from deals.models import Deal, Deposit, Stage
from documents.models import ExtractionRun
from reports import services as reports

TOPICS = {
    "title": ("Title", Q(category__iexact="Title")),
    "survey": ("Survey", Q(category__iexact="Survey")),
    "insurance": ("Property insurance", Q(title__icontains="property insurance")),
    "financing": ("Financing", Q(category__iexact="Financing and insurance") & ~Q(title__icontains="insurance")),
    "inspection": ("Inspections", Q(category__iexact="Physical and environmental diligence")),
}


def topic_filter(topic):
    return TOPICS[topic][1]


PROGRESS_KINDS = [("all", "All"), ("sale", "Sales & acquisitions"), ("lease", "Leases"), ("business", "Business assets")]


def deal_progress(kind="all"):
    """One row per active or on-hold deal: where it sits on the stage path, its
    checklist completion, next open deadline and blockers."""
    from deals.models import BUSINESS_TYPES, LEASE_TYPES, SALE_TYPES

    path = list(Stage.objects.filter(enabled=True, category__in=[Stage.CATEGORY_ACTIVE, Stage.CATEGORY_CLOSED])
                .order_by("order"))
    index = {s.pk: i for i, s in enumerate(path)}
    deals = Deal.objects.filter(archived_at__isnull=True,
                                stage__category__in=[Stage.CATEGORY_ACTIVE, Stage.CATEGORY_ON_HOLD])
    types = {"sale": SALE_TYPES, "lease": LEASE_TYPES, "business": BUSINESS_TYPES}.get(kind)
    if types:
        deals = deals.filter(transaction_type__in=types)
    deals = deals.select_related("stage", "responsible_broker").annotate(
        items_total=Count("checklist_items", distinct=True),
        items_done=Count("checklist_items", filter=Q(checklist_items__status__in=["approved", "waived", "not_applicable"]),
                         distinct=True),
    )
    today = timezone.localdate()
    next_by_deal = {}
    for d in (Deadline.objects.filter(deal__in=deals, state="open", computation="computed")
              .order_by("current_date").only("id", "deal_id", "name", "current_date")):
        next_by_deal.setdefault(d.deal_id, d)
    awaiting = set(Deadline.objects.filter(deal__in=deals, state="open")
                   .exclude(computation="computed").values_list("deal_id", flat=True))
    rows = []
    for deal in deals:
        on_hold = deal.stage.category == Stage.CATEGORY_ON_HOLD
        current = index.get(deal.stage_id)
        steps = []
        for i, s in enumerate(path):
            state = "todo"
            if current is not None:
                state = "done" if i < current else ("current" if i == current else "todo")
            steps.append({"name": s.name, "state": state})
        pct = round(100 * (current + 1) / len(path)) if current is not None else 0
        nxt = next_by_deal.get(deal.pk)
        rows.append({
            "deal": deal, "steps": steps, "pct": pct, "on_hold": on_hold, "position": current if current is not None else -1,
            "stage_no": (current + 1) if current is not None else None, "stage_total": len(path),
            "checklist_pct": round(100 * deal.items_done / deal.items_total) if deal.items_total else None,
            "next": nxt, "next_overdue": bool(nxt and nxt.current_date < today),
            "awaiting": deal.pk in awaiting, "property": deal.primary_property,
        })
    rows.sort(key=lambda r: (r["on_hold"], -r["position"], r["next"].current_date if r["next"] else today + timedelta(days=9999)))
    return {"rows": rows, "path": path, "kinds": PROGRESS_KINDS, "kind": kind}


def build(user, params):
    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    month_end = today + timedelta(days=30)
    active_deals = Deal.objects.filter(archived_at__isnull=True, stage__category=Stage.CATEGORY_ACTIVE)
    dl = Deadline.objects.filter(state="open", deal__archived_at__isnull=True)
    computed = dl.filter(computation="computed")
    url = reverse

    stages = (
        Stage.objects.filter(category__in=[Stage.CATEGORY_ACTIVE, Stage.CATEGORY_ON_HOLD], enabled=True)
        .annotate(n=Count("deals", filter=Q(deals__archived_at__isnull=True)))
        .order_by("order")
    )
    deadlines = {
        "overdue": (computed.filter(current_date__lt=today).count(), f"{url('deadline_list')}?bucket=overdue"),
        "today": (computed.filter(current_date=today).count(), f"{url('deadline_list')}?bucket=today"),
        "week": (computed.filter(current_date__gte=today, current_date__lte=week_end).count(), f"{url('deadline_list')}?bucket=week"),
        "next30": (computed.filter(current_date__gte=today, current_date__lte=month_end).count(), f"{url('deadline_list')}?bucket=next30"),
        "awaiting": (dl.filter(computation="awaiting_trigger").count(), f"{url('deadline_list')}?bucket=awaiting"),
        "needs_review": (dl.filter(computation="needs_review").count(), f"{url('deadline_list')}?bucket=needs_review"),
    }
    feasibility = computed.filter(category="feasibility", current_date__gte=today, current_date__lte=today + timedelta(days=14))
    items_open = ChecklistItem.objects.filter(status__in=OPEN_STATUSES, deal__archived_at__isnull=True,
                                              deal__stage__category=Stage.CATEGORY_ACTIVE)
    overdue_items = items_open.filter(Q(due_date__lt=today) | Q(follow_up_on__lt=today))
    topics = []
    for key, (label, q) in TOPICS.items():
        topics.append({"key": key, "label": label, "n": items_open.filter(q).count(),
                       "url": f"{url('checklist_list')}?topic={key}&open=1"})
    deposits = Deposit.objects.filter(deal__in=active_deals, receipt_confirmed_on__isnull=True, released_on__isnull=True)
    closings = active_deals.filter(
        Q(contractual_closing_date__gte=today, contractual_closing_date__lte=month_end)
        | Q(contractual_closing_date__isnull=True, target_closing_date__gte=today, target_closing_date__lte=month_end)
    )
    review_runs = ExtractionRun.objects.filter(
        status="succeeded", fields__review_status__in=["pending", "needs_review"],
        version__document__archived_at__isnull=True,
    ).distinct()
    failed_runs = ExtractionRun.objects.filter(status="failed", version__document__archived_at__isnull=True)
    failed_runs = [r for r in failed_runs if not r.version.extraction_runs.filter(created_at__gt=r.created_at).exists()]
    blocked = active_deals.filter(is_blocked=True)

    period = params.get("period", "year")
    year = today.year
    if period == "quarter":
        f = reports.filters_from_params({"year": year, "quarter": (today.month - 1) // 3 + 1})
    elif period == "month":
        f = reports.filters_from_params({"year": year, "month": today.month})
    else:
        period = "year"
        f = reports.filters_from_params({"year": year})
    sales = reports.closed_sales_volume(f)
    leases = reports.executed_leases(f)
    data = {
        "today": today,
        "stages": stages,
        "progress": deal_progress(params.get("kind", "all") if params.get("kind") in dict(PROGRESS_KINDS) else "all"),
        "deadlines": deadlines,
        "feasibility": (feasibility.count(), f"{url('deadline_list')}?category=feasibility&bucket=next14"),
        "feasibility_list": list(feasibility.select_related("deal")[:6]),
        "overdue_items": (overdue_items.count(), f"{url('checklist_list')}?bucket=overdue"),
        "topics": topics,
        "deposits": (deposits.count(), url("deposit_list")),
        "closings": (closings.count(), f"{url('deal_list')}?closing=30"),
        "closing_list": list(closings.select_related("stage")[:6]),
        "review_runs": (review_runs.count(), url("review_queue")),
        "failed_runs": (len(failed_runs), f"{url('review_queue')}?failed=1"),
        "blocked": (blocked.count(), f"{url('deal_list')}?blocked=1"),
        "blocked_list": list(blocked[:6]),
        "upcoming": list(computed.filter(current_date__lte=week_end).select_related("deal").order_by("current_date")[:10]),
        "period": period,
        "filters": f,
        "sales": sales,
        "leases": leases,
        "reminder_failures": (Reminder.objects.filter(status="failed").count(), f"{url('reminder_log')}?status=failed"),
    }
    if has_perm(user, "commission.view"):
        expected = reports.pipeline_commissions()
        data["fin"] = {
            "expected": expected,
            "earned": reports.earned_commissions(f),
            "receipts": reports.cash_receipts(f),
            "designated": reports.designated_broker_receipts(f),
            "outstanding": reports.outstanding_balances(f),
            "qs": f.querystring(),
        }
    return data

