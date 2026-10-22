from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = settings.AUTH_USER_MODEL


class ImportBatch(models.Model):
    KINDS = [
        ("deals", _("Historical deals (with properties, commissions)")),
        ("properties", _("Properties")),
        ("contacts", _("Contacts & companies")),
    ]
    STATUSES = [
        ("uploaded", _("Uploaded — map fields")),
        ("validated", _("Validated — review before committing")),
        ("committed", _("Committed")),
        ("reverted", _("Reverted")),
        ("partially_reverted", _("Partially reverted")),
    ]

    kind = models.CharField(max_length=20, choices=KINDS)
    file = models.FileField(upload_to="imports/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    headers = models.JSONField(default=list)
    mapping = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="uploaded")
    notes = models.TextField(blank=True)
    summary = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    committed_at = models.DateTimeField(null=True, blank=True)
    reverted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "import batches"

    def __str__(self):
        return f"Import #{self.pk} ({self.get_kind_display()}) — {self.original_filename}"

    def get_absolute_url(self):
        return reverse("import_detail", args=[self.pk])


class ImportRow(models.Model):
    STATUSES = [
        ("pending", _("Pending")),
        ("valid", _("Valid")),
        ("invalid", _("Has errors")),
        ("committed", _("Committed")),
        ("skipped", _("Skipped")),
        ("reverted", _("Reverted")),
        ("revert_blocked", _("Revert blocked")),
    ]
    ACTIONS = [("create", _("Create")), ("skip", _("Skip"))]

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    raw = models.JSONField(default=dict)
    mapped = models.JSONField(default=dict)
    errors = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    duplicate_note = models.CharField(max_length=255, blank=True)
    matches = models.JSONField(default=dict, blank=True, help_text="Existing records this row links to.")
    action = models.CharField(max_length=10, choices=ACTIONS, default="create")
    status = models.CharField(max_length=20, choices=STATUSES, default="pending")
    created_objects = models.JSONField(default=list, blank=True, help_text="[[model_label, pk], ...]")
    revert_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["row_number"]
        unique_together = [("batch", "row_number")]
