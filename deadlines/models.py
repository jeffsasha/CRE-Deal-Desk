from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.choices import TIME_ZONES

User = settings.AUTH_USER_MODEL

CATEGORIES = [
    ("contract", "Contract / effective date"),
    ("earnest_money", "Earnest money & deposits"),
    ("feasibility", "Feasibility / due diligence"),
    ("title", "Title"),
    ("survey", "Survey"),
    ("financing", "Financing"),
    ("closing", "Closing"),
    ("lease", "Lease"),
    ("notice", "Notice"),
    ("commission", "Commission"),
    ("internal", "Internal target"),
    ("other", "Other"),
]

RULE_TYPES = [
    ("fixed", "Fixed date"),
    ("fixed_term", "Fixed date from approved contract term"),
    ("offset", "Days after a trigger event"),
    ("later_of", "Days after the later of several events"),
    ("earlier_of", "Days after the earlier of several events"),
]

DAY_BASIS = [("calendar", "Calendar days"), ("business", "Business days")]

WEEKEND_RULES = [
    ("none", "No adjustment (none established)"),
    ("next_business_day", "Move to next business day (per contract)"),
    ("previous_business_day", "Move to previous business day (per contract)"),
]

COMPUTATION = [
    ("computed", "Computed"),
    ("awaiting_trigger", "Awaiting Trigger"),
    ("needs_review", "Needs Review"),
]

STATES = [
    ("open", "Open"),
    ("satisfied", "Satisfied / performed"),
    ("waived", "Waived"),
    ("expired", "Passed without action"),
    ("superseded", "Superseded"),
    ("cancelled", "Cancelled"),
]

CONFIRMATION = [
    ("unconfirmed", "Rule not yet confirmed"),
    ("confirmed", "Rule confirmed against contract"),
    ("needs_review", "Needs review"),
]


class Deadline(models.Model):
    deal = models.ForeignKey("deals.Deal", on_delete=models.CASCADE, related_name="deadlines")
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORIES, default="other")
    is_contractual = models.BooleanField(
        default=True, help_text="Contractual deadlines come from the agreement; internal targets do not."
    )

    rule_type = models.CharField(max_length=20, choices=RULE_TYPES, default="offset")
    fixed_date = models.DateField(null=True, blank=True)
    fixed_date_term_key = models.CharField(max_length=60, blank=True)
    trigger_keys = models.JSONField(
        default=list, blank=True, help_text="Event keys, or 'deadline:<id>' to chain from another deadline."
    )
    offset_days = models.IntegerField(null=True, blank=True)
    offset_term_key = models.CharField(
        max_length=60, blank=True, help_text="Take the number of days from this approved contract term."
    )
    day_basis = models.CharField(max_length=10, choices=DAY_BASIS, default="calendar")
    include_trigger_day = models.BooleanField(
        default=False, help_text="Count the trigger day itself as day 1."
    )
    holiday_calendar = models.ForeignKey("core.HolidayCalendar", null=True, blank=True, on_delete=models.SET_NULL)
    weekend_rule = models.CharField(max_length=30, choices=WEEKEND_RULES, default="none")
    weekend_rule_source = models.CharField(
        max_length=255, blank=True, help_text="Contract clause establishing the adjustment, if any."
    )
    due_time = models.TimeField(null=True, blank=True)
    time_zone = models.CharField(max_length=64, choices=TIME_ZONES, default="America/Chicago")

    source_version = models.ForeignKey(
        "documents.DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source_page = models.PositiveIntegerField(null=True, blank=True)
    source_section = models.CharField(max_length=120, blank=True)
    source_clause = models.TextField(blank=True)

    responsible_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    responsible_party = models.CharField(max_length=160, blank=True, help_text="Outside party responsible, if any.")
    confirmation = models.CharField(max_length=20, choices=CONFIRMATION, default="unconfirmed")
    reminder_days = models.JSONField(default=list, blank=True, help_text="Days before due date, e.g. [7, 3, 1, 0].")

    computation = models.CharField(max_length=20, choices=COMPUTATION, default="awaiting_trigger")
    computation_note = models.TextField(blank=True)
    original_date = models.DateField(null=True, blank=True)
    current_date = models.DateField(null=True, blank=True, db_index=True)
    due_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=0)

    state = models.CharField(max_length=20, choices=STATES, default="open")
    state_changed_at = models.DateTimeField(null=True, blank=True)
    state_changed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state_note = models.TextField(blank=True)
    template_key = models.CharField(max_length=60, blank=True)

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["current_date", "name"]

    def __str__(self):
        return f"{self.name} ({self.deal.internal_id})"

    def get_absolute_url(self):
        return reverse("deadline_detail", args=[self.pk])

    @property
    def is_open(self):
        return self.state == "open"

    @property
    def days_until(self):
        if not self.current_date:
            return None
        return (self.current_date - timezone.localdate()).days

    @property
    def is_overdue(self):
        return self.is_open and self.current_date is not None and self.current_date < timezone.localdate()

    def rule_snapshot(self):
        return {
            "rule_type": self.rule_type,
            "fixed_date": self.fixed_date.isoformat() if self.fixed_date else None,
            "fixed_date_term_key": self.fixed_date_term_key,
            "trigger_keys": self.trigger_keys,
            "offset_days": self.offset_days,
            "offset_term_key": self.offset_term_key,
            "day_basis": self.day_basis,
            "include_trigger_day": self.include_trigger_day,
            "holiday_calendar": self.holiday_calendar.code if self.holiday_calendar_id else None,
            "weekend_rule": self.weekend_rule,
            "due_time": self.due_time.isoformat() if self.due_time else None,
            "time_zone": self.time_zone,
        }


class DeadlineRevision(models.Model):
    deadline = models.ForeignKey(Deadline, on_delete=models.CASCADE, related_name="revisions")
    revision = models.PositiveIntegerField()
    previous_date = models.DateField(null=True, blank=True)
    new_date = models.DateField(null=True, blank=True)
    previous_computation = models.CharField(max_length=20, blank=True)
    new_computation = models.CharField(max_length=20, blank=True)
    reason = models.CharField(max_length=255)
    explanation = models.TextField(blank=True)
    rule_snapshot = models.JSONField(default=dict)
    amendment = models.ForeignKey("documents.Amendment", null=True, blank=True, on_delete=models.SET_NULL)
    changed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-revision"]


class Reminder(models.Model):
    STATUSES = [
        ("scheduled", "Scheduled"),
        ("delivered", "Delivered"),
        ("failed", "Delivery failed"),
        ("cancelled", "Cancelled"),
    ]
    CHANNELS = [("in_app", "In-app"), ("email", "Email")]

    deadline = models.ForeignKey(Deadline, null=True, blank=True, on_delete=models.CASCADE, related_name="reminders")
    checklist_item = models.ForeignKey(
        "checklists.ChecklistItem", null=True, blank=True, on_delete=models.CASCADE, related_name="reminders"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reminders")
    channel = models.CharField(max_length=10, choices=CHANNELS, default="in_app")
    lead_days = models.IntegerField()
    target_revision = models.PositiveIntegerField(default=0)
    remind_at = models.DateTimeField(db_index=True)
    dedupe_key = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="scheduled", db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.CharField(max_length=255, blank=True)
    acknowledged_at = models.DateTimeField(
        null=True, blank=True, help_text="Acknowledging a reminder does not complete the deadline."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["remind_at"]
