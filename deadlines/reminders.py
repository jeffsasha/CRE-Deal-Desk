"""Reminder scheduling and delivery.

- Each reminder has a unique dedupe key (deadline, revision, lead time, channel,
  recipient), so re-running scheduling never creates duplicates.
- When a deadline's date changes, pending reminders for the superseded revision are
  cancelled (kept for history) and new ones are scheduled.
- Delivery failures are recorded on the reminder and shown in the UI.
- Acknowledging a reminder never completes the deadline.
"""
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from core.models import Notification, WorkspaceSetting

from .models import Reminder

log = logging.getLogger(__name__)


def default_reminder_days():
    return WorkspaceSetting.get("reminder_days", settings.DEALDESK_DEFAULT_REMINDER_DAYS)


def recipients_for(deadline):
    if deadline.responsible_user_id:
        return [deadline.responsible_user]
    deal = deadline.deal
    if deal.responsible_broker_id:
        return [deal.responsible_broker]
    return list(deal.team.all())


def _cancel(qs, reason):
    return qs.filter(status="scheduled").update(status="cancelled", cancelled_reason=reason[:255])


@transaction.atomic
def sync_reminders(deadline, now=None):
    now = now or timezone.now()
    pending = Reminder.objects.filter(deadline=deadline, status="scheduled")
    if deadline.state != "open" or deadline.computation != "computed" or deadline.current_date is None:
        if deadline.state != "open":
            reason = f"Deadline {deadline.get_state_display().lower()}"
        else:
            reason = f"Deadline date no longer computed ({deadline.get_computation_display()})"
        _cancel(pending, reason)
        return []
    _cancel(
        pending.exclude(target_revision=deadline.revision),
        f"Superseded: deadline revised to {deadline.current_date:%b %d, %Y} (revision {deadline.revision})",
    )
    tz = ZoneInfo(deadline.time_zone)
    created = []
    lead_days = deadline.reminder_days or default_reminder_days()
    for user in recipients_for(deadline):
        channels = ["in_app"]
        if user.email_reminders and user.email:
            channels.append("email")
        for lead in sorted(set(int(x) for x in lead_days), reverse=True):
            remind_at = datetime.combine(
                deadline.current_date - timedelta(days=lead), time(settings.DEALDESK_REMINDER_HOUR), tzinfo=tz
            )
            if remind_at < now and lead > 0:
                continue  # lead time already passed when scheduled; the day-of reminder still fires
            for channel in channels:
                key = f"dl{deadline.pk}-r{deadline.revision}-d{lead}-{channel}-u{user.pk}"
                reminder, was_created = Reminder.objects.get_or_create(
                    dedupe_key=key,
                    defaults={
                        "deadline": deadline,
                        "user": user,
                        "channel": channel,
                        "lead_days": lead,
                        "target_revision": deadline.revision,
                        "remind_at": remind_at,
                    },
                )
                if was_created:
                    created.append(reminder)
    return created


def sync_follow_up_reminder(item):
    """One in-app reminder on a checklist item's follow-up date."""
    pending = Reminder.objects.filter(checklist_item=item, status="scheduled")
    if not item.is_open or not item.follow_up_on or not item.owner_id:
        _cancel(pending, "Follow-up cleared or item closed")
        return None
    key = f"ci{item.pk}-f{item.follow_up_on:%Y%m%d}-u{item.owner_id}"
    _cancel(pending.exclude(dedupe_key=key), "Follow-up date changed")
    tz = ZoneInfo(settings.DEALDESK_DEFAULT_TIME_ZONE)
    reminder, _ = Reminder.objects.get_or_create(
        dedupe_key=key,
        defaults={
            "checklist_item": item,
            "user_id": item.owner_id,
            "channel": "in_app",
            "lead_days": 0,
            "remind_at": datetime.combine(item.follow_up_on, time(settings.DEALDESK_REMINDER_HOUR), tzinfo=tz),
        },
    )
    return reminder


def _message(reminder):
    if reminder.deadline_id:
        d = reminder.deadline
        when = "today" if reminder.lead_days == 0 else f"in {reminder.lead_days} day{'s' if reminder.lead_days != 1 else ''}"
        title = f"{d.name} — due {when} ({d.current_date:%a %b %d})"
        body = f"{d.deal}\n{d.computation_note}"
        url = d.get_absolute_url()
    else:
        item = reminder.checklist_item
        title = f"Follow up: {item.title}"
        body = f"{item.deal} — checklist status: {item.get_status_display()}"
        url = f"/deals/{item.deal_id}/?tab=checklist"
    return title, body, url


def deliver(reminder):
    """Deliver one reminder. Returns the reminder with its final status."""
    title, body, url = _message(reminder)
    reminder.attempts += 1
    try:
        if reminder.channel == "in_app":
            Notification.objects.create(user=reminder.user, title=title, body=body, url=url, reminder=reminder)
        elif reminder.channel == "email":
            if not settings.EMAIL_CONFIGURED:
                raise RuntimeError("Email delivery is not configured (EMAIL_HOST is not set). The in-app reminder was still delivered.")
            send_mail(f"[DealDesk] {title}", f"{body}\n\nOpen: {url}", settings.DEFAULT_FROM_EMAIL, [reminder.user.email])
        reminder.status = "delivered"
        reminder.delivered_at = timezone.now()
        reminder.last_error = ""
    except Exception as exc:  # noqa: BLE001 - surfaced in the delivery log
        log.warning("Reminder %s failed: %s", reminder.pk, exc)
        reminder.status = "failed"
        reminder.last_error = str(exc)[:2000]
    reminder.save()
    return reminder


def deliver_due(now=None, limit=500):
    now = now or timezone.now()
    out = []
    due = Reminder.objects.filter(status="scheduled", remind_at__lte=now).select_related("deadline", "user")[:limit]
    for reminder in due:
        # Claim the reminder so concurrent workers cannot deliver it twice.
        claimed = Reminder.objects.filter(pk=reminder.pk, status="scheduled").update(status="delivered")
        if not claimed:
            continue
        reminder.status = "scheduled"
        if reminder.deadline_id and reminder.deadline.state != "open":
            reminder.status = "cancelled"
            reminder.cancelled_reason = f"Deadline {reminder.deadline.get_state_display().lower()} before delivery"
            reminder.save()
            continue
        out.append(deliver(reminder))
    return out


def acknowledge(reminder, user):
    reminder.acknowledged_at = timezone.now()
    reminder.save(update_fields=["acknowledged_at"])
    Notification.objects.filter(reminder=reminder, user=user, read_at__isnull=True).update(read_at=timezone.now())
