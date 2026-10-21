from django.conf import settings
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL

STATUSES = [
    ("not_started", "Not Started"),
    ("requested", "Requested"),
    ("in_progress", "In Progress"),
    ("received", "Received"),
    ("under_review", "Under Review"),
    ("approved", "Approved"),
    ("waived", "Waived"),
    ("not_applicable", "Not Applicable"),
    ("blocked", "Blocked"),
]
OPEN_STATUSES = {"not_started", "requested", "in_progress", "received", "under_review", "blocked"}
DONE_STATUSES = {"approved", "waived", "not_applicable"}


class ChecklistTemplate(models.Model):
    key = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    transaction_types = models.JSONField(default=list)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


CONDITIONS = [
    ("financing", "Buyer / tenant is using financing"),
    ("income_property", "Property has tenants / income"),
    ("new_survey", "A new survey is being ordered"),
    ("environmental", "Phase I or other environmental work is in scope"),
    ("restaurant", "Restaurant or food-service use"),
    ("construction", "Tenant improvements or construction"),
    ("lender_title", "Lender's title policy required"),
    ("license_dependency", "Operating license / permit dependency"),
]


class TemplateItem(models.Model):
    template = models.ForeignKey(ChecklistTemplate, on_delete=models.CASCADE, related_name="items")
    category = models.CharField(max_length=80)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    condition = models.CharField(max_length=40, choices=CONDITIONS, blank=True)
    responsible_party_hint = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class ChecklistItem(models.Model):
    deal = models.ForeignKey("deals.Deal", on_delete=models.CASCADE, related_name="checklist_items")
    template_item = models.ForeignKey(TemplateItem, null=True, blank=True, on_delete=models.SET_NULL)
    category = models.CharField(max_length=80)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUSES, default="not_started", db_index=True)

    owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="checklist_items")
    outside_party = models.ForeignKey("crm.Contact", null=True, blank=True, on_delete=models.SET_NULL)
    outside_party_note = models.CharField(max_length=160, blank=True)
    due_date = models.DateField(null=True, blank=True)
    deadline = models.ForeignKey("deadlines.Deadline", null=True, blank=True, on_delete=models.SET_NULL)
    depends_on = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="dependents")
    requested_on = models.DateField(null=True, blank=True)
    received_on = models.DateField(null=True, blank=True)
    reviewed_on = models.DateField(null=True, blank=True)
    approved_on = models.DateField(null=True, blank=True)
    follow_up_on = models.DateField(null=True, blank=True)
    not_applicable_reason = models.CharField(max_length=255, blank=True)
    blocked_reason = models.CharField(max_length=255, blank=True)
    unresolved_issues = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    evidence = models.ManyToManyField("documents.Document", blank=True, related_name="checklist_items")
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def is_follow_up_due(self):
        return self.is_open and self.follow_up_on is not None and self.follow_up_on <= timezone.localdate()

    @property
    def is_overdue(self):
        return self.is_open and self.due_date is not None and self.due_date < timezone.localdate()


class ChecklistItemHistory(models.Model):
    item = models.ForeignKey(ChecklistItem, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-changed_at"]
