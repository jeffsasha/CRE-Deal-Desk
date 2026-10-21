import html
import re

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from core.audit import audit
from core.jobs import run_job
from core.listing import Column, Filter, Listing
from core.permissions import has_perm, require, require_edit_on_post, require_perm
from deals.models import Deal, log_activity

from . import services
from .forms import DocumentMetaForm, ExecutionForm, LinkForm, ManualFieldForm, NewVersionForm, NotesForm, UploadForm
from .models import (
    AMENDING_DOC_TYPES,
    CATEGORIES,
    CONTRACT_DOC_TYPES,
    DOC_TYPES,
    EXECUTION_STATUSES,
    Amendment,
    Document,
    DocumentLink,
    DocumentVersion,
    ExtractedField,
    ExtractionRun,
)
from .processing import extraction_engine_label, queue_processing
from .storage import read_token, signed_url


def _check_access(user, document):
    require(user, "view")
    if document.access_level == "confidential":
        require(user, "document.confidential")


def _visible(qs, user):
    if not has_perm(user, "document.confidential"):
        qs = qs.exclude(access_level="confidential")
    return qs


@require_perm("view")
def document_list(request):
    qs = _visible(Document.objects.active(), request.user).prefetch_related("versions", "links__deal", "links__property")
    listing = Listing(
        request, qs, area="documents",
        columns=[
            Column("title", "Document", lambda d: d.title, sort="title"),
            Column("category", "Category", lambda d: d.get_category_display(), sort="category"),
            Column("type", "Type", lambda d: d.get_doc_type_display() + ("" if d.doc_type_confirmed else " (suggested)"), sort="doc_type"),
            Column("linked", "Linked to", lambda d: ", ".join(str(l.target) for l in d.links.all()[:3]) or "—"),
            Column("exec", "Execution", lambda d: d.current_version.get_execution_status_display() if d.current_version else "—"),
            Column("ocr", "Text / OCR", lambda d: d.current_version.get_text_status_display() if d.current_version else "—", default=False),
            Column("versions", "Versions", lambda d: d.versions.count(), cls="num", default=False),
            Column("tags", "Tags", lambda d: d.tags or "", default=False),
            Column("access", "Access", lambda d: "Confidential" if d.access_level == "confidential" else "", default=False),
            Column("updated", "Updated", lambda d: timezone.localtime(d.updated_at).strftime("%b %-d, %Y"), sort="updated_at"),
        ],
        search_fields=["title", "tags", "description", "versions__full_text", "versions__original_filename"],
        filters=[
            Filter("category", "Category", CATEGORIES, lambda qs, v: qs.filter(category=v)),
            Filter("type", "Type", DOC_TYPES, lambda qs, v: qs.filter(doc_type=v)),
            Filter("execution", "Execution", EXECUTION_STATUSES, lambda qs, v: qs.filter(versions__execution_status=v)),
            Filter("summary", "Origin", [("original", "Originals"), ("generated", "Generated summaries")],
                   lambda qs, v: qs.filter(is_generated_summary=(v == "generated"))),
        ],
        default_sort="-updated_at",
    )
    if request.GET.get("export") == "csv":
        return listing.export_csv("documents")
    actions = [("Review queue", reverse("review_queue"))]
    if has_perm(request.user, "edit"):
        actions.append(("Upload", reverse("document_upload")))
    return render(request, "core/list_page.html", {"listing": listing, "title": "Documents", "actions": actions,
                                                   "subtitle": "Search covers titles, tags and the full text of uploaded documents (including OCR)."})


def _process(request, version, extract):
    job = queue_processing(version, request.user, extract=extract)
    if settings.DEBUG or getattr(settings, "INLINE_PROCESSING", True):
        run_job(job)
        job.refresh_from_db()
    return job


@require_edit_on_post
def document_upload(request):
    require(request.user, "edit")
    initial = {k: request.GET.get(k) for k in ["deal", "property", "organization", "contact", "issue"] if request.GET.get(k)}
    form = UploadForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if d["access_level"] == "confidential":
            require(request.user, "document.confidential")
        try:
            version, duplicate = services.upload(
                d["file"], request.user, title=d["title"], category=d["category"], doc_type=d["doc_type"],
                access_level=d["access_level"], tags=d["tags"], description=d["description"], deal=d["deal"],
                prop=d["property"], organization=d["organization"], contact=d["contact"], issue=d["issue"],
                document_date=d["document_date"], delivered_on=d["delivered_on"],
                delivery_evidence=d["delivery_evidence"], process=False,
            )
        except ValidationError as exc:
            form.add_error("file", " ".join(exc.messages))
        else:
            if duplicate:
                messages.warning(request, format_html('An identical file was already uploaded as <a href="{}">{}</a>.',
                                                      duplicate.document.get_absolute_url(), duplicate))
            job = _process(request, version, d["extract"])
            version.refresh_from_db()
            run = version.extraction_runs.first()
            if run and run.status == "succeeded" and run.fields.exists():
                messages.success(request, "Uploaded. Proposed terms are ready for your review.")
                return redirect("extraction_review", run.pk)
            if run and run.status == "failed":
                messages.error(request, f"Extraction failed: {run.error}. The file is stored; enter terms manually.")
            elif job.status == "failed":
                messages.error(request, "Processing failed; the original file is stored safely. You can retry or work manually.")
            else:
                messages.success(request, "Uploaded.")
            return redirect(version.document)
    return render(request, "form.html", {"form": form, "title": "Upload document", "back_url": reverse("document_list"),
                                         "subtitle": f"Extraction engine: {extraction_engine_label()}. Uploaded files are never treated as executed until you confirm execution."})


@require_perm("view")
def document_detail(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    _check_access(request.user, doc)
    versions = doc.versions.select_related("uploaded_by", "execution_confirmed_by").prefetch_related("extraction_runs")
    current = versions.first()
    return render(request, "documents/detail.html", {
        "doc": doc, "versions": versions, "current": current,
        "links": doc.links.select_related("deal", "property", "organization", "contact", "issue"),
        "execution_form": ExecutionForm(initial={"status": current.execution_status if current else "unknown"}),
        "version_form": NewVersionForm(), "link_form": LinkForm(), "meta_form": DocumentMetaForm(instance=doc),
        "view_url": signed_url(current, request.user, inline=True) if current else "",
        "download_url": signed_url(current, request.user) if current else "",
        "is_contract": doc.doc_type in CONTRACT_DOC_TYPES, "is_amending": doc.doc_type in AMENDING_DOC_TYPES,
    })


@xframe_options_sameorigin
def document_file(request, token):
    try:
        data = read_token(token)
    except signing.SignatureExpired:
        raise PermissionDenied("This download link has expired. Open the document again for a new link.")
    except signing.BadSignature:
        raise Http404
    if not request.user.is_authenticated or request.user.pk != data["u"]:
        raise PermissionDenied("This link was issued to a different user.")
    version = get_object_or_404(DocumentVersion.objects.select_related("document"), pk=data["v"])
    _check_access(request.user, version.document)
    if version.document.archived_at and not has_perm(request.user, "document.archive"):
        raise Http404
    response = FileResponse(version.file.open("rb"), content_type=version.content_type,
                            as_attachment=not data.get("i"), filename=version.original_filename)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    if not data.get("i"):
        audit(request.user, "document.downloaded", version.document, {"version": version.version})
    return response


@require_POST
@require_perm("edit")
def document_new_version(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    _check_access(request.user, doc)
    form = NewVersionForm(request.POST, request.FILES)
    if form.is_valid():
        d = form.cleaned_data
        try:
            version, _dup = services.upload(d["file"], request.user, document=doc, change_note=d["change_note"],
                                            document_date=d["document_date"], delivered_on=d["delivered_on"],
                                            delivery_evidence=d["delivery_evidence"], process=False)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect(doc)
        _process(request, version, d["extract"])
        messages.success(request, f"Version {version.version} uploaded. Earlier versions are preserved.")
    else:
        messages.error(request, "Choose a file to upload.")
    return redirect(doc)


@require_POST
@require_perm("edit")
def document_meta(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    _check_access(request.user, doc)
    old = {"doc_type": doc.doc_type, "access_level": doc.access_level, "category": doc.category}
    form = DocumentMetaForm(request.POST, instance=doc)
    if form.is_valid():
        if form.cleaned_data["access_level"] == "confidential":
            require(request.user, "document.confidential")
        doc = form.save()
        changes = {k: (v, getattr(doc, k)) for k, v in old.items() if getattr(doc, k) != v}
        if changes:
            audit(request.user, "document.metadata_changed", doc, changes)
    return redirect(doc)


@require_POST
@require_perm("edit")
def document_execution(request, version_pk):
    version = get_object_or_404(DocumentVersion, pk=version_pk)
    _check_access(request.user, version.document)
    form = ExecutionForm(request.POST)
    if form.is_valid():
        try:
            services.set_execution_status(version, form.cleaned_data["status"], request.user, form.cleaned_data["evidence"])
            messages.success(request, f"Execution status set to {version.get_execution_status_display()}.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    return redirect(request.POST.get("next") or version.document.get_absolute_url())


@require_POST
@require_perm("edit")
def document_link(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    _check_access(request.user, doc)
    form = LinkForm(request.POST)
    if form.is_valid():
        for field in ["deal", "property", "organization", "contact", "issue"]:
            target = form.cleaned_data.get(field)
            if target is not None:
                DocumentLink.objects.get_or_create(document=doc, **{field: target})
                if field == "deal":
                    log_activity(target, f"Document linked: {doc.title}", actor=request.user, document=doc)
    return redirect(doc)


@require_POST
@require_perm("edit")
def document_unlink(request, pk, link_pk):
    link = get_object_or_404(DocumentLink, pk=link_pk, document_id=pk)
    audit(request.user, "document.unlinked", link.document, {"from": str(link.target)})
    link.delete()
    return redirect("document_detail", pk=pk)


@require_POST
@require_perm("edit")
def document_reprocess(request, version_pk):
    version = get_object_or_404(DocumentVersion, pk=version_pk)
    _check_access(request.user, version.document)
    _process(request, version, True)
    run = version.extraction_runs.first()
    if run and run.status == "succeeded":
        return redirect("extraction_review", run.pk)
    messages.error(request, f"Extraction did not succeed{': ' + run.error if run else ''}. Manual entry remains available.")
    return redirect(version.document)


@require_edit_on_post
def document_archive(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    require(request.user, "document.archive")
    if request.method == "POST":
        if doc.archived_at:
            services.restore_document(doc, request.user)
            messages.success(request, "Document restored.")
        else:
            services.archive_document(doc, request.user, request.POST.get("reason", ""))
            messages.success(request, "Document archived. The file and its history are retained and can be restored.")
        return redirect(doc)
    return render(request, "confirm.html", {"title": f"Archive {doc}", "back_url": doc.get_absolute_url(),
                                            "message": "Archiving hides the document. The original file, versions and extraction history are kept; nothing is deleted.",
                                            "reason_required": True, "submit_label": "Archive document", "danger": True})


# --- Review ---------------------------------------------------------------------

@require_perm("view")
def review_queue(request):
    runs = ExtractionRun.objects.filter(version__document__archived_at__isnull=True).select_related(
        "version__document").order_by("-created_at")
    if not has_perm(request.user, "document.confidential"):
        runs = runs.exclude(version__document__access_level="confidential")
    if request.GET.get("failed"):
        runs = runs.filter(status="failed")
    pending = [r for r in runs[:300] if r.status == "failed" or r.pending_count]
    return render(request, "documents/review_queue.html", {"runs": pending, "failed_only": bool(request.GET.get("failed"))})


def _deals_for(version):
    return Deal.objects.filter(document_links__document=version.document).distinct()


@require_perm("view")
def extraction_review(request, pk):
    run = get_object_or_404(ExtractionRun.objects.select_related("version__document"), pk=pk)
    version = run.version
    doc = version.document
    _check_access(request.user, doc)
    fields = list(run.fields.select_related("reviewer", "published_term"))
    deals = _deals_for(version)
    other_runs = version.extraction_runs.exclude(pk=run.pk)
    first_page = next((f.page for f in fields if f.page), 1)
    return render(request, "documents/review.html", {
        "run": run, "version": version, "doc": doc, "fields": fields, "deals": deals,
        "view_url": signed_url(version, request.user, inline=True),
        "manual_form": ManualFieldForm(), "other_runs": other_runs,
        "is_amending": doc.doc_type in AMENDING_DOC_TYPES, "is_contract": doc.doc_type in CONTRACT_DOC_TYPES,
        "approved": sum(1 for f in fields if f.is_approved and not f.published_at),
        "open_count": sum(1 for f in fields if f.review_status in {"pending", "needs_review"}),
        "first_page": first_page, "execution_form": ExecutionForm(initial={"status": version.execution_status}),
    })


@require_perm("view")
def version_page_text(request, version_pk, page):
    version = get_object_or_404(DocumentVersion, pk=version_pk)
    _check_access(request.user, version.document)
    text = version.page_text(page)
    quote = request.GET.get("q", "")
    escaped = html.escape(text)
    if quote and text:
        marked = _highlight(text, quote)
        if marked:
            escaped = marked
    header = f'<div class="muted" style="margin-bottom:8px">Page {page}{" · OCR text" if page in (version.ocr_pages or []) else ""}</div>'
    return HttpResponse(header + (escaped or '<span class="muted">No text on this page.</span>'))


def _highlight(text, quote):
    """Find the quote in the page text (whitespace-tolerant) and wrap it in <mark>."""
    words = [re.escape(w) for w in quote.split()[:40]]
    if len(words) < 2:
        return None
    pattern = r"\s+".join(words)
    m = re.search(pattern, text, re.I)
    if not m:
        words = words[: max(4, len(words) // 2)]
        m = re.search(r"\s+".join(words), text, re.I)
    if not m:
        return None
    return html.escape(text[: m.start()]) + "<mark>" + html.escape(text[m.start(): m.end()]) + "</mark>" + html.escape(text[m.end():])


@require_POST
@require_perm("edit")
def field_action(request, pk):
    field = get_object_or_404(ExtractedField.objects.select_related("run__version__document"), pk=pk)
    _check_access(request.user, field.run.version.document)
    try:
        services.review_field(field, request.user, request.POST.get("action"), request.POST.get("value", ""),
                              request.POST.get("note", ""))
    except ValidationError as exc:
        messages.error(request, f"{field.label}: {' '.join(exc.messages)}")
    return redirect(f"{reverse('extraction_review', args=[field.run_id])}#f{field.pk}")


@require_POST
@require_perm("edit")
def manual_field(request, version_pk):
    version = get_object_or_404(DocumentVersion, pk=version_pk)
    _check_access(request.user, version.document)
    form = ManualFieldForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            f = services.add_manual_field(version, request.user, d["key"], d["value"], d["page"], d["section"], d["quote"])
            return redirect(f"{reverse('extraction_review', args=[f.run_id])}#f{f.pk}")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    else:
        messages.error(request, "Enter a field and a value.")
    run = version.extraction_runs.first()
    return redirect("extraction_review", run.pk) if run else redirect(version.document)


@require_POST
@require_perm("edit")
def manual_start(request, version_pk):
    """Open a manual review for a document with no (or failed) extraction."""
    version = get_object_or_404(DocumentVersion, pk=version_pk)
    _check_access(request.user, version.document)
    run = version.extraction_runs.filter(engine="manual").first() or ExtractionRun.objects.create(
        version=version, engine="manual", status="succeeded", created_by=request.user, started_at=timezone.now(),
        finished_at=timezone.now(), summary="Values entered manually by a reviewer.")
    return redirect("extraction_review", run.pk)


@require_POST
@require_perm("edit")
def publish(request, pk):
    run = get_object_or_404(ExtractionRun, pk=pk)
    _check_access(request.user, run.version.document)
    deal = get_object_or_404(Deal, pk=request.POST.get("deal"))
    try:
        result = services.publish(run, deal, request.user, replace_conflicts=bool(request.POST.get("replace")))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("extraction_review", run.pk)
    messages.success(request, f"Published {len(result['published'])} value(s) to {deal}. Deadlines were recomputed from the approved rules.")
    if result["pending"]:
        messages.warning(request, f"{result['pending']} proposal(s) still need review and were not published.")
    for c in result["conflicts"]:
        messages.warning(request, f"Not published (conflicts with an approved value): {c}. Use an amendment or confirm replacement.")
    return redirect(f"{deal.get_absolute_url()}?tab=contract")


@require_POST
@require_perm("edit")
def prepare_amendment(request, pk):
    run = get_object_or_404(ExtractionRun, pk=pk)
    _check_access(request.user, run.version.document)
    deal = get_object_or_404(Deal, pk=request.POST.get("deal"))
    try:
        amendment = services.prepare_amendment(run, deal, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("extraction_review", run.pk)
    return redirect(amendment)


@require_perm("view")
def amendment_detail(request, pk):
    amendment = get_object_or_404(Amendment.objects.select_related("deal", "version__document"), pk=pk)
    _check_access(request.user, amendment.version.document)
    if amendment.status == "proposed" and request.GET.get("refresh"):
        services.refresh_preview(amendment)
    return render(request, "documents/amendment.html", {
        "a": amendment, "version": amendment.version, "execution_form": ExecutionForm(initial={"status": amendment.version.execution_status}),
        "revisions": amendment.deadlinerevision_set.select_related("deadline") if amendment.status == "applied" else [],
    })


@require_POST
@require_perm("edit")
def amendment_apply(request, pk):
    amendment = get_object_or_404(Amendment, pk=pk)
    try:
        changed = services.apply_amendment(amendment, request.user)
        messages.success(request, f"Amendment applied. {len(changed)} deadline(s) changed; superseded dates and reminders are kept in history.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect(amendment)


@require_POST
@require_perm("edit")
def amendment_reject(request, pk):
    amendment = get_object_or_404(Amendment, pk=pk)
    services.reject_amendment(amendment, request.user, request.POST.get("reason", "Withdrawn"))
    return redirect(amendment)


@require_edit_on_post
def deal_notes(request, pk):
    require(request.user, "edit")
    deal = get_object_or_404(Deal, pk=pk)
    form = NotesForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        content = ContentFile(d["text"].encode("utf-8"), name=f"notes-{deal.internal_id}.txt")
        content.size = len(d["text"].encode("utf-8"))
        version, _ = services.upload(content, request.user, title=d["title"], category="historical_notes",
                                     doc_type="other", deal=deal, document_date=d["document_date"], process=False)
        from .processing import read_text

        read_text(version)
        messages.success(request, "Notes stored as an original text document and linked to the deal.")
        return redirect(f"{deal.get_absolute_url()}?tab=documents")
    return render(request, "form.html", {"form": form, "title": f"Paste historical notes — {deal.name}",
                                         "back_url": f"{deal.get_absolute_url()}?tab=documents"})
