from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.decorators.vary import vary_on_headers

from core.permissions import require_perm
from .forms import PaycheckForm
from .models import Paycheck


@never_cache
@vary_on_headers("X-Workspace-Navigation")
@require_perm("salary.manage")
def salary_list(request):
    owned = Paycheck.objects.filter(owner=request.user)
    active = owned.filter(archived_at__isnull=True)
    years = sorted({d.year for d in owned.dates("pay_month", "year")} | {timezone.localdate().year}, reverse=True)
    try:
        year = int(request.GET.get("year", years[0]))
    except (TypeError, ValueError):
        year = years[0]
    if year not in years:
        year = years[0]
    annual = active.filter(pay_month__year=year)
    totals = {row["pay_month__month"]: row["total"] for row in annual.values("pay_month__month").annotate(total=Sum("net_pay_cents"))}
    scale = max(totals.values(), default=0) or 1
    months = [{"date": date(year, month, 1), "total": totals.get(month),
               "height": totals.get(month, 0) * 10000 // scale} for month in range(1, 13)]
    archived = request.GET.get("archived") == "1"
    records = owned.filter(pay_month__year=year, archived_at__isnull=not archived)
    context = {"year": year, "years": years, "months": months, "year_total": sum(totals.values()),
               "all_total": active.aggregate(total=Sum("net_pay_cents"))["total"] or 0,
               "recorded_months": len(totals), "records": records, "show_archived": archived}
    return render(request, "payroll/list.html", context)


@never_cache
@require_perm("salary.manage")
def salary_form(request, pk=None):
    row = get_object_or_404(Paycheck, pk=pk, owner=request.user) if pk else None
    form = PaycheckForm(request.POST, owner=request.user, instance=row) if request.method == "POST" else PaycheckForm(owner=request.user, instance=row)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                row = form.save()
        except (IntegrityError, ValidationError):
            form.add_error("check_number", _("This check is already recorded, including archived records."))
        else:
            messages.success(request, _("Salary record saved."))
            return redirect(row)
    return render(request, "form.html", {"form": form, "title": _("Edit salary") if pk else _("Add monthly salary"),
                                         "back_url": row.get_absolute_url() if row else reverse("salary_list"), "max_width": "720px"})


@never_cache
@require_perm("salary.manage")
@require_POST
def salary_archive(request, pk):
    row = get_object_or_404(Paycheck, pk=pk, owner=request.user)
    action = request.POST.get("action")
    if action not in ("archive", "restore"):
        return HttpResponseBadRequest()
    row.archived_at = timezone.now() if action == "archive" else None
    row.archived_by = request.user if action == "archive" else None
    row.save(update_fields=["archived_at", "archived_by", "updated_at"])
    messages.success(request, _("Salary record archived.") if action == "archive" else _("Salary record restored."))
    return redirect(row)
