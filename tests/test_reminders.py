"""Reminders: no duplicates, superseded reminders cancelled but kept, failures
recorded, acknowledgment is not completion."""
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from core.models import Notification
from deadlines.models import Reminder
from deadlines.reminders import acknowledge, deliver_due, sync_reminders
from deadlines.services import create_deadline, recompute, set_state

from .base import DeskTestCase


class ReminderTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker", email="b@example.invalid", email_reminders=True)
        self.deal = self.deal(actor=self.broker, responsible_broker=self.broker)
        self.dl = create_deadline(actor=self.broker, deal=self.deal, name="Fixed", rule_type="fixed",
                                  fixed_date=timezone.localdate() + timedelta(days=10), reminder_days=[7, 1, 0])

    def test_no_duplicates(self):
        n = Reminder.objects.count()
        self.assertEqual(n, 6)  # 3 lead times x (in-app + email)
        sync_reminders(self.dl)
        sync_reminders(self.dl)
        self.assertEqual(Reminder.objects.count(), n)

    def test_date_change_supersedes(self):
        old = list(Reminder.objects.values_list("pk", flat=True))
        self.dl.fixed_date = timezone.localdate() + timedelta(days=20)
        self.dl.save()
        recompute(self.dl, reason="moved")
        self.assertTrue(all(r.status == "cancelled" for r in Reminder.objects.filter(pk__in=old)))
        self.assertEqual(Reminder.objects.filter(status="scheduled").count(), 6)

    def test_delivery_failure_recorded_and_in_app_still_delivered(self):
        Reminder.objects.update(remind_at=timezone.now() - timedelta(minutes=1))
        delivered = deliver_due()
        self.assertEqual(len(delivered), 6)
        email = [r for r in delivered if r.channel == "email"]
        self.assertTrue(all(r.status == "failed" and "not configured" in r.last_error for r in email))
        self.assertEqual(Notification.objects.filter(user=self.broker).count(), 3)
        self.assertEqual(deliver_due(), [])  # nothing delivered twice

    @override_settings(EMAIL_CONFIGURED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_delivery_when_configured(self):
        from django.core import mail

        Reminder.objects.update(remind_at=timezone.now() - timedelta(minutes=1))
        deliver_due()
        self.assertEqual(len(mail.outbox), 3)

    def test_acknowledgment_is_not_completion(self):
        Reminder.objects.update(remind_at=timezone.now() - timedelta(minutes=1))
        r = [x for x in deliver_due() if x.channel == "in_app"][0]
        acknowledge(r, self.broker)
        self.dl.refresh_from_db()
        self.assertEqual(self.dl.state, "open")

    def test_satisfied_deadline_cancels_pending(self):
        set_state(self.dl, "satisfied", self.broker, "Done")
        self.assertFalse(Reminder.objects.filter(status="scheduled").exists())
        self.assertTrue(Reminder.objects.filter(status="cancelled").exists())
