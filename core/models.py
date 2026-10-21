import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    ROLE_ADMIN = "admin"
    ROLE_BROKER = "broker"
    ROLE_COORDINATOR = "coordinator"
    ROLE_READ_ONLY = "read_only"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Administrator"),
        (ROLE_BROKER, "Broker"),
        (ROLE_COORDINATOR, "Coordinator"),
        (ROLE_READ_ONLY, "Read-only"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_READ_ONLY)
    job_title = models.CharField(max_length=120, blank=True)
    is_designated_broker = models.BooleanField(
        default=False,
        help_text="Marks the designated broker whose personal receipts are reported separately.",
    )
    time_zone = models.CharField(max_length=64, default="America/Chicago")
    email_reminders = models.BooleanField(default=False)
    calendar_token = models.CharField(max_length=64, unique=True, blank=True, null=True)

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def save(self, *args, **kwargs):
        if not self.calendar_token:
            self.calendar_token = secrets.token_urlsafe(32)
        if self.is_superuser and self.role != self.ROLE_ADMIN:
            self.role = self.ROLE_ADMIN
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    def __str__(self):
        return self.display_name


class ArchivableQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived_at__isnull=True)

    def archived(self):
        return self.filter(archived_at__isnull=False)


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Archivable(models.Model):
    """Recoverable archiving. Nothing in the workspace is hard-deleted from the UI."""

    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = ArchivableQuerySet.as_manager()

    class Meta:
        abstract = True

    @property
    def is_archived(self):
        return self.archived_at is not None


class Imported(models.Model):
    """Source reference for records created by a historical import batch."""

    import_batch = models.ForeignKey(
        "imports.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source_reference = models.CharField(max_length=255, blank=True)

    class Meta:
        abstract = True


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    model_label = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["model_label", "object_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.object_repr}"


class Job(models.Model):
    """Database-backed background job queue (document processing and similar work)."""

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    ]

    kind = models.CharField(max_length=60)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    last_error = models.TextField(blank=True)
    run_after = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=500, blank=True)
    reminder = models.ForeignKey("deadlines.Reminder", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class HolidayCalendar(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def dates(self):
        return set(self.holidays.values_list("date", flat=True))


class Holiday(models.Model):
    calendar = models.ForeignKey(HolidayCalendar, on_delete=models.CASCADE, related_name="holidays")
    date = models.DateField()
    name = models.CharField(max_length=120)

    class Meta:
        ordering = ["date"]
        unique_together = [("calendar", "date")]

    def __str__(self):
        return f"{self.date} {self.name}"


class SavedView(models.Model):
    """A saved filter / sort / column selection for a list screen."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_views")
    area = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    query_string = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["area", "name"]
        unique_together = [("user", "area", "name")]


class WorkspaceSetting(models.Model):
    key = models.CharField(max_length=80, unique=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls, key, default=None):
        row = cls.objects.filter(key=key).first()
        return row.value if row else default

    @classmethod
    def put(cls, key, value):
        cls.objects.update_or_create(key=key, defaults={"value": value})
