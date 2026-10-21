from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.audit import audit
from deals.catalog import term_label
from deals.models import DealTerm, log_activity
from deals.services import parse_date, parse_term_value, record_event, set_term

from .models import (
    AMENDING_DOC_TYPES,
    CONTRACT_DOC_TYPES,
    Amendment,
    Document,
    DocumentLink,
    DocumentVersion,
    ExtractedField,
    ExtractionRun,
)
from .storage import validate_upload


@transaction.atomic
def upload(uploaded, actor, *, title="", category="other", doc_type="unknown", access_level="standard", tags="",
           description="", deal=None, prop=None, organization=None, contact=None, issue=None, document=None,
           change_note="", document_date=None, delivered_on=None, delivery_evidence="", process=True):
    """Store an original file as a new document (or a new version of `document`).
    The original bytes are kept unchanged; derived text is stored separately."""
    content_type, sha = validate_upload(uploaded)
    if document is None:
        document = Document.objects.create(
            title=title or uploaded.name, category=category, doc_type=doc_type,
            doc_type_confirmed=doc_type != "unknown", access_level=access_level, tags=tags, description=description,
            created_by=actor,
        )
        for kwargs in ({"deal": deal}, {"property": prop}, {"organization": organization}, {"contact": contact},
                       {"issue": issue}):
            if next(iter(kwargs.values())) is not None:
                DocumentLink.objects.create(document=document, **kwargs)
    next_version = (document.versions.order_by("-version").values_list("version", flat=True).first() or 0) + 1
    version = DocumentVersion(
        document=document, version=next_version, original_filename=uploaded.name[:255], content_type=content_type,
        size_bytes=uploaded.size, sha256=sha, uploaded_by=actor, change_note=change_note,
        document_date=document_date, delivered_on=delivered_on, delivery_evidence=delivery_evidence,
        text_status="pending",
    )
    version.file.save(uploaded.name, uploaded, save=False)
    version.save()
    document.save(update_fields=["updated_at"])
    duplicate = DocumentVersion.objects.filter(sha256=sha).exclude(pk=version.pk).select_related("document").first()
    audit(actor, "document.uploaded", document, {"version": next_version, "file": uploaded.name, "sha256": sha[:16]})
    if deal is not None:
        log_activity(deal, f"Document uploaded: {document.title} (v{next_version})", actor=actor, document=document)
    if process:
        from .processing import queue_processing

        transaction.on_commit(lambda: queue_processing(version, actor))
    return version, duplicate


EXECUTION_USER_CHOICES = {"draft", "partially_signed", "confirmed_executed", "not_applicable", "unknown"}


@transaction.atomic
def set_execution_status(version, status, actor, evidence=""):
    if status not in EXECUTION_USER_CHOICES:
        raise ValidationError("Choose a valid execution status.")
    if status == "confirmed_executed" and not evidence.strip():
        raise ValidationError("Describe how execution was confirmed (e.g. 'fully signed copy received from title 3/4').")
    old = version.execution_status
    version.execution_status = status
    version.execution_evidence = evidence
    if status == "confirmed_executed":
        version.execution_confirmed_by = actor
        version.execution_confirmed_at = timezone.now()
    else:
        version.execution_confirmed_by = None
        version.execution_confirmed_at = None
    version.save()
    audit(actor, "document.execution_status", version.document, {"execution_status": (old, status)}, note=evidence)
    for link in version.document.links.filter(deal__isnull=False):
        log_activity(link.deal, f"Execution status of {version} set to {version.get_execution_status_display()}",
                     actor=actor, document=version.document)
    return version


def review_field(field, actor, action, value="", note=""):
    if field.published_at:
        raise ValidationError("This value is already published. Changes go through an amendment or a new term.")
    if action == "reject":
        field.review_status = "rejected"
    elif action in {"accept", "edit"}:
        candidate = value if action == "edit" else field.proposed_value
        if not (candidate or "").strip():
            raise ValidationError("A value is required. Enter the value from the document or reject the proposal.")
        try:
            if field.key == "effective_date":
                parse_date(candidate)
            else:
                parse_term_value(field.key, candidate)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if action == "edit" and candidate != field.proposed_value:
            field.review_status = "edited"
            field.reviewed_value = candidate
        else:
            field.review_status = "accepted"
            field.reviewed_value = ""
    elif action == "needs_review":
        field.review_status = "needs_review"
    else:
        raise ValidationError("Unknown review action.")
    field.review_note = note
    field.reviewer = actor
    field.reviewed_at = timezone.now()
    field.save()
    audit(actor, f"extraction.{field.review_status}", field.run.version.document,
          {field.label: (field.proposed_value, field.final_value if field.review_status != "rejected" else None)},
          note=note)
    return field


def add_manual_field(version, actor, key, value, page=None, section="", quote=""):
    run = version.extraction_runs.filter(engine="manual").first()
    if run is None:
        run = ExtractionRun.objects.create(version=version, engine="manual", status="succeeded", created_by=actor,
                                           started_at=timezone.now(), finished_at=timezone.now(),
                                           summary="Values entered manually by a reviewer.")
    field = ExtractedField.objects.create(
        run=run, key=key, label="Effective date" if key == "effective_date" else term_label(key), proposed_value=value,
        page=page, section=section, supporting_text=quote, confidence="high", basis="explicit",
        review_status="pending", quote_verified=False,
    )
    return review_field(field, actor, "accept", note="Entered manually")


def _deal_linked(version, deal):
    return version.document.links.filter(deal=deal).exists()


@transaction.atomic
def publish(run, deal, actor, replace_conflicts=False):
    """Publish approved values from an executed base contract into the deal record."""
    version = run.version
    doc = version.document
    if not _deal_linked(version, deal):
        raise ValidationError("Link this document to the deal before publishing.")
    if doc.doc_type in AMENDING_DOC_TYPES:
        raise ValidationError("This is an amendment or extension. Use 'Prepare amendment' to compare and apply it.")
    if doc.doc_type not in CONTRACT_DOC_TYPES:
        raise ValidationError(
            f"{doc.get_doc_type_display()} values are not contract terms. Confirm the document type if it is a contract."
        )
    if not version.is_executed:
        raise ValidationError(
            "Execution of this document has not been confirmed. Its terms remain proposals and are not published."
        )
    fields = list(run.fields.filter(review_status__in=["accepted", "edited"], published_at__isnull=True))
    pending = run.fields.filter(review_status__in=["pending", "needs_review"]).count()
    active = deal.active_terms()
    published, conflicts = [], []
    for f in fields:
        if f.key == "effective_date":
            continue
        value = parse_term_value(f.key, f.final_value)
        current = active.get(f.key)
        if current and current.value != value and current.source_version_id != version.pk and not replace_conflicts:
            conflicts.append(f"{f.label}: current {current.display_value()} vs. {f.final_value}")
            continue
        term = set_term(deal, f.key, value, actor, source_version=version, source_field=f, page=f.page,
                        section=f.section, quote=f.supporting_text, recompute=False,
                        note=f"Published from {doc.title} v{version.version}")
        f.published_term = term
        f.published_at = timezone.now()
        f.save(update_fields=["published_term", "published_at"])
        published.append(f)
    eff = next((f for f in fields if f.key == "effective_date"), None)
    if eff:
        record_event(deal, "effective_date", parse_date(eff.final_value), actor, evidence_document=doc,
                     evidence_note=f"{doc.title} v{version.version}, p. {eff.page or '?'}: {eff.supporting_text[:300]}")
        eff.published_at = timezone.now()
        eff.save(update_fields=["published_at"])
        published.append(eff)
    from deadlines.services import recompute_deal

    recompute_deal(deal, actor=actor, reason=f"Terms published from {doc.title}")
    audit(actor, "extraction.published", doc, {"published": len(published), "conflicts": len(conflicts)})
    return {"published": published, "conflicts": conflicts, "pending": pending}


def _typed_override(key, text):
    return parse_term_value(key, text)


@transaction.atomic
def prepare_amendment(run, deal, actor):
    version = run.version
    doc = version.document
    if not _deal_linked(version, deal):
        raise ValidationError("Link this document to the deal first.")
    if doc.doc_type not in AMENDING_DOC_TYPES:
        raise ValidationError("Only amendment or extension documents can be prepared as amendments.")
    fields = list(run.fields.filter(review_status__in=["accepted", "edited"]))
    if not fields:
        raise ValidationError("Accept or edit at least one proposed change before preparing the amendment.")
    active = deal.active_terms()
    changes, overrides = [], {}
    for f in fields:
        if f.key == "effective_date":
            continue
        new_value = _typed_override(f.key, f.final_value)
        current = active.get(f.key)
        probe = DealTerm(key=f.key)
        from deals.services import _assign

        _assign(probe, new_value)
        changes.append({
            "key": f.key, "label": f.label, "field_id": f.pk,
            "old": current.display_value() if current else None,
            "new": probe.display_value(), "new_raw": f.final_value,
            "unchanged": bool(current and current.value == new_value),
            "page": f.page, "quote": f.supporting_text[:400],
        })
        overrides[f.key] = new_value
    from deadlines.services import preview_deal

    amendment = Amendment.objects.create(
        deal=deal, version=version, title=f"{doc.title} (v{version.version})", changes=changes,
        preview=preview_deal(deal, overrides),
    )
    audit(actor, "amendment.prepared", deal, {"amendment": amendment.title, "changes": [c["label"] for c in changes]})
    log_activity(deal, f"Amendment prepared for review (not effective): {amendment.title}", actor=actor, document=doc)
    return amendment


def refresh_preview(amendment):
    from deadlines.services import preview_deal

    overrides = {c["key"]: _typed_override(c["key"], c["new_raw"]) for c in amendment.changes}
    amendment.preview = preview_deal(amendment.deal, overrides)
    amendment.save(update_fields=["preview", "updated_at"])
    return amendment


@transaction.atomic
def apply_amendment(amendment, actor):
    if amendment.status != "proposed":
        raise ValidationError("This amendment is not pending.")
    version = DocumentVersion.objects.get(pk=amendment.version_id)
    if not version.is_executed:
        raise ValidationError(
            "Execution of this amendment has not been confirmed. Until it is fully executed it is a proposal and "
            "does not change any term or date."
        )
    deal = amendment.deal
    applied = []
    for change in amendment.changes:
        if change.get("unchanged"):
            continue
        value = _typed_override(change["key"], change["new_raw"])
        field = ExtractedField.objects.filter(pk=change.get("field_id")).first()
        term = set_term(deal, change["key"], value, actor, source_version=version, source_field=field,
                        page=change.get("page"), quote=change.get("quote", ""), amendment=amendment, recompute=False,
                        note=f"Amendment applied: {amendment.title}")
        if field:
            field.published_term = term
            field.published_at = timezone.now()
            field.save(update_fields=["published_term", "published_at"])
        applied.append(change["label"])
    from deadlines.services import recompute_deal

    results = recompute_deal(deal, actor=actor, reason=f"Amendment applied: {amendment.title}", amendment=amendment)
    amendment.status = "applied"
    amendment.applied_by = actor
    amendment.applied_at = timezone.now()
    amendment.save()
    audit(actor, "amendment.applied", deal, {"amendment": amendment.title, "terms": applied})
    log_activity(deal, f"Amendment applied: {amendment.title} ({', '.join(applied) or 'no term changes'})",
                 actor=actor, kind="decision", document=version.document)
    return [r for r in results if r[2]]


def reject_amendment(amendment, actor, reason):
    amendment.status = "rejected"
    amendment.notes = reason
    amendment.save()
    audit(actor, "amendment.rejected", amendment.deal, {"amendment": amendment.title}, note=reason)
    log_activity(amendment.deal, f"Amendment withdrawn/rejected: {amendment.title} — {reason}", actor=actor)


def archive_document(document, actor, reason):
    document.archived_at = timezone.now()
    document.archived_by = actor
    document.save()
    audit(actor, "document.archived", document, note=reason)


def restore_document(document, actor):
    document.archived_at = None
    document.archived_by = None
    document.save()
    audit(actor, "document.restored", document)
