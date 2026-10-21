import csv

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.permissions import require_perm

from . import services
from .models import ImportBatch, ImportRow


class NewImportForm(forms.Form):
    kind = forms.ChoiceField(choices=ImportBatch.KINDS)
    file = forms.FileField(help_text="CSV or Excel (.xlsx). The first row must contain column headers.")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith((".csv", ".xlsx")):
            raise forms.ValidationError("Upload a .csv or .xlsx file.")
        if f.size > 20 * 1024 * 1024:
            raise forms.ValidationError("File is larger than 20 MB.")
        return f


@require_perm("import")
def import_list(request):
    form = NewImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            batch = services.create_batch(form.cleaned_data["file"], form.cleaned_data["kind"], request.user)
        except Exception as exc:  # noqa: BLE001 - malformed spreadsheets
            form.add_error("file", f"Could not read the file: {exc}")
        else:
            return redirect("import_detail", batch.pk)
    return render(request, "imports/list.html", {"form": form, "batches": ImportBatch.objects.select_related("created_by")[:100]})


@require_perm("import")
def import_detail(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    fields = services.FIELDS[batch.kind]
    if request.method == "POST" and batch.status in {"uploaded", "validated"}:
        mapping = {key: request.POST.get(f"map_{key}", "") for key, *_ in fields}
        counts = services.validate_batch(batch, mapping)
        messages.info(request, f"Validated: {counts['valid']} valid, {counts['invalid']} with errors, {counts['duplicates']} possible duplicates.")
        return redirect("import_detail", batch.pk)
    status = request.GET.get("status", "")
    rows = batch.rows.all()
    if status:
        rows = rows.filter(status=status)
    return render(request, "imports/detail.html", {
        "batch": batch, "fields": fields, "rows": rows[:500], "status": status,
        "sample": batch.rows.first().raw if batch.rows.exists() else {},
        "counts": {s: batch.rows.filter(status=s).count() for s, _ in ImportRow.STATUSES},
    })


@require_POST
@require_perm("import")
def import_row_action(request, pk, row_pk):
    row = get_object_or_404(ImportRow, pk=row_pk, batch_id=pk)
    if row.batch.status == "validated" and row.status == "valid":
        row.action = request.POST.get("action", "create") if request.POST.get("action") in {"create", "skip"} else "create"
        row.save(update_fields=["action"])
    return redirect(reverse("import_detail", args=[pk]) + f"#row{row.row_number}")


@require_POST
@require_perm("import")
def import_commit(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    try:
        committed, skipped = services.commit_batch(batch, request.user)
        messages.success(request, f"Committed {committed} row(s); {skipped} skipped. Every record created carries this batch as its source.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("import_detail", batch.pk)


@require_POST
@require_perm("import.revert")
def import_revert(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    try:
        reverted, blocked = services.revert_batch(batch, request.user)
        if blocked:
            messages.warning(request, f"Reverted {reverted} row(s). {blocked} row(s) were kept because their records were edited or used after the import.")
        else:
            messages.success(request, f"Reverted {reverted} row(s).")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("import_detail", batch.pk)


@require_perm("import")
def import_errors(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="import-{batch.pk}-report.csv"'
    w = csv.writer(response)
    w.writerow(["Row", "Status", "Action", "Errors", "Warnings", "Duplicate", "Revert note"] + batch.headers)
    for r in batch.rows.all():
        w.writerow([r.row_number, r.get_status_display(), r.action, " | ".join(r.errors), " | ".join(r.warnings),
                    r.duplicate_note, r.revert_note] + [r.raw.get(h, "") for h in batch.headers])
    return response


@require_perm("import")
def import_template(request, kind):
    if kind not in services.FIELDS:
        kind = "deals"
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="dealdesk-{kind}-template.csv"'
    csv.writer(response).writerow([label for _k, label, _r, _a in services.FIELDS[kind]])
    return response
