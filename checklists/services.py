from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy

from core.audit import audit
from deals.models import log_activity

from .models import CONDITIONS, ChecklistItem, ChecklistItemHistory, ChecklistTemplate

CONDITION_LABELS = dict(CONDITIONS)


def template_for(deal):
    for tpl in ChecklistTemplate.objects.filter(enabled=True):
        if deal.transaction_type in (tpl.transaction_types or []):
            return tpl
    return None


@transaction.atomic
def apply_template(deal, template, conditions, actor):
    """Instantiate a template. Items whose condition is not met are created as Not
    Applicable with a stated reason, so they remain visible and can be reopened."""
    existing = set(deal.checklist_items.values_list("template_item_id", flat=True))
    created = 0
    for item in template.items.all():
        if item.pk in existing:
            continue
        status, reason = "not_started", ""
        if item.condition and not conditions.get(item.condition):
            status = "not_applicable"
            reason = f"Not applicable at setup: condition not met — {CONDITION_LABELS.get(item.condition, item.condition)}."
        ChecklistItem.objects.create(
            deal=deal, template_item=item, category=item.category, title=item.title, description=item.description,
            order=item.order, status=status, not_applicable_reason=reason, updated_by=actor,
        )
        created += 1
    log_activity(deal, f"Checklist created from template '{template.name}' ({created} items)", actor=actor)
    return created


def validate_item(item):
    if item.status == "not_applicable" and not item.not_applicable_reason.strip():
        raise ValidationError(gettext_lazy("Not Applicable requires a reason."))
    if item.status == "blocked" and not item.blocked_reason.strip():
        raise ValidationError(gettext_lazy("Blocked requires a reason (who or what is blocking it)."))
    if item.status == "approved" and not item.approved_on:
        raise ValidationError(gettext_lazy("Approved requires the approval date."))
    if item.status == "under_review" and not item.received_on:
        raise ValidationError(gettext_lazy("An item under review must have a received date."))


@transaction.atomic
def update_item(item, actor, old_status, note=""):
    """Persist an edited item. Receiving does not imply review or approval: each
    status records its own date and no status is advanced automatically."""
    today = timezone.localdate()
    if item.status in {"requested"} and not item.requested_on:
        item.requested_on = today
    if item.status == "received" and not item.received_on:
        item.received_on = today
    if item.status == "approved" and not item.approved_on:
        item.approved_on = today
    if item.status == "approved" and not item.reviewed_on:
        item.reviewed_on = item.approved_on
    validate_item(item)
    item.updated_by = actor
    item.save()
    if old_status != item.status:
        ChecklistItemHistory.objects.create(item=item, from_status=old_status, to_status=item.status, note=note[:255],
                                            changed_by=actor)
        summary = "Checklist updated" if item.workflow_financial else f"Checklist: {item.title} — {item.get_status_display()}"
        log_activity(item.deal, summary, actor=actor)
        audit(actor, "checklist.status", item.deal, {item.title: (old_status, item.status)}, note=note)
    from deadlines.reminders import sync_follow_up_reminder

    sync_follow_up_reminder(item)
    return item
