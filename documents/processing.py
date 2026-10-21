"""Background processing for uploaded document versions: text/OCR, classification,
extraction proposals. Failures are recorded and never touch the stored original."""
import logging

from django.conf import settings
from django.utils import timezone

from core.jobs import enqueue, handler

from .classify import detect_doc_type, detect_execution
from .extraction import claude as claude_extractor
from .extraction import pattern as pattern_extractor
from .extraction import safeguards
from .models import ExtractedField, ExtractionRun
from .text import extract_text, page_count

log = logging.getLogger(__name__)

EXTRACTABLE_TYPES = {
    "purchase_contract", "lease", "loi", "amendment", "extension", "commission_agreement", "unknown", "other",
}


def extraction_engine():
    choice = settings.EXTRACTION_ENGINE
    if choice == "pattern":
        return "pattern"
    if claude_extractor.is_configured() and choice in {"auto", "claude"}:
        return "claude"
    return "pattern"


def extraction_engine_label():
    if extraction_engine() == "claude":
        return f"Claude ({settings.EXTRACTION_MODEL})"
    return "Offline pattern extractor (no AI credential configured)"


def queue_processing(version, actor=None, extract=True):
    return enqueue("process_document_version", version_id=version.pk, actor_id=actor.pk if actor else None,
                   extract=extract)


@handler("process_document_version")
def process_document_version(version_id, actor_id=None, extract=True):
    from .models import DocumentVersion

    version = DocumentVersion.objects.select_related("document").get(pk=version_id)
    read_text(version)
    if extract and _should_extract(version):
        run_extraction(version, actor_id=actor_id)


def _should_extract(version):
    doc = version.document
    if doc.category in {"photo", "floor_plan", "marketing", "historical_notes"}:
        return False
    return doc.doc_type in EXTRACTABLE_TYPES or doc.category in {
        "contract", "amendment", "loi", "lease", "commission_agreement"}


def read_text(version):
    try:
        path = version.file.path
        version.page_count = page_count(path, version.content_type)
        result = extract_text(path, version.content_type)
        version.pages_text = result.pages
        version.ocr_pages = result.ocr_pages
        version.text_status = result.status
        version.ocr_engine = result.engine
        version.full_text = "\n\n".join(result.pages)[:2_000_000]
        version.processing_error = result.error
    except Exception as exc:  # noqa: BLE001
        log.exception("Text extraction failed for version %s", version.pk)
        version.text_status = "failed"
        version.processing_error = f"Text extraction failed: {exc}"
    if version.pages_text:
        status, signals = detect_execution(version.pages_text)
        if version.execution_status in {"unknown", "draft", "partially_signed", "appears_executed"}:
            version.execution_status = status
        version.execution_signals = signals
        doc = version.document
        if not doc.doc_type_confirmed:
            detected = detect_doc_type(version.pages_text)
            if detected != "unknown":
                doc.doc_type = detected
                doc.save(update_fields=["doc_type", "updated_at"])
    version.save()
    return version


def run_extraction(version, actor_id=None, engine=None):
    engine = engine or extraction_engine()
    run = ExtractionRun.objects.create(
        version=version, engine=engine, status="running", started_at=timezone.now(), created_by_id=actor_id,
        model_name=settings.EXTRACTION_MODEL if engine == "claude" else "",
    )
    try:
        doc_type = version.document.doc_type
        if engine == "claude":
            output = claude_extractor.extract(version.file.path, version.content_type, version.pages_text)
        else:
            if not any((t or "").strip() for t in version.pages_text):
                raise RuntimeError(
                    "No readable text is available (scanned document and OCR unavailable or failed). "
                    "Add terms manually from the document viewer."
                )
            output = pattern_extractor.extract(version.pages_text, doc_type)
        detected_type = output.doc_type if output.doc_type != "unknown" else doc_type
        checked = safeguards.apply(output.proposals, version.pages_text, detected_type)
        for proposal, verified, status in checked:
            ExtractedField.objects.create(
                run=run, key=proposal.key, label=proposal.label, proposed_value=proposal.value,
                value_type="date" if proposal.key == "effective_date" else _type(proposal.key),
                page=proposal.page, section=proposal.section[:120], supporting_text=proposal.supporting_text,
                confidence=proposal.confidence, basis=proposal.basis, calculation_note=proposal.calculation_note,
                flags=proposal.flags, quote_verified=verified, review_status=status,
            )
        run.detected_doc_type = detected_type
        run.detected_execution_status = output.execution_status if engine == "claude" else version.execution_status
        run.summary = output.summary + (f"\nExecution evidence: {output.execution_evidence}" if output.execution_evidence else "")
        run.raw_output = output.raw
        run.model_name = output.model_name or run.model_name
        run.status = "succeeded"
    except Exception as exc:  # noqa: BLE001 - shown to the reviewer; manual entry stays available
        if isinstance(exc, RuntimeError):
            log.warning("Extraction failed for version %s: %s", version.pk, exc)
        else:
            log.exception("Extraction failed for version %s", version.pk)
        run.status = "failed"
        run.error = str(exc)[:4000]
    run.finished_at = timezone.now()
    run.save()
    return run


def _type(key):
    from deals.catalog import term_type

    return term_type(key)
