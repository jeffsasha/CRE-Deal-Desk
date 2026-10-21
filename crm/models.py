from django.db import models
from django.urls import reverse

from core.models import Archivable, Imported, TimeStamped


class Organization(TimeStamped, Archivable, Imported):
    TYPE_CHOICES = [
        ("client_entity", "Client entity"),
        ("ownership_entity", "Ownership entity"),
        ("brokerage", "Brokerage"),
        ("title_company", "Title company"),
        ("lender", "Lender"),
        ("law_firm", "Law firm"),
        ("surveyor", "Surveying firm"),
        ("inspection", "Inspection firm"),
        ("environmental", "Environmental consultant"),
        ("insurance", "Insurance agency"),
        ("appraisal", "Appraisal firm"),
        ("property_manager", "Property manager"),
        ("government", "Government / utility"),
        ("business", "Operating business"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=255)
    org_type = models.CharField("Type", max_length=30, choices=TYPE_CHOICES, default="other")
    is_client = models.BooleanField(default=False)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="branches")
    branch_name = models.CharField(max_length=120, blank=True, help_text="Branch or office, e.g. for title companies.")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website = models.CharField(max_length=255, blank=True)
    street = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=2, blank=True, default="TX")
    postal_code = models.CharField(max_length=10, blank=True)
    tags = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.branch_name}" if self.branch_name else self.name

    def get_absolute_url(self):
        return reverse("organization_detail", args=[self.pk])


class Contact(TimeStamped, Archivable, Imported):
    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="contacts"
    )
    title = models.CharField(max_length=120, blank=True)
    roles = models.CharField(
        max_length=255, blank=True, help_text="Comma-separated, e.g. Escrow officer, Surveyor, Attorney."
    )
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    mobile = models.CharField(max_length=40, blank=True)
    street = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=2, blank=True, default="TX")
    postal_code = models.CharField(max_length=10, blank=True)
    is_client = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    @property
    def full_name(self):
        return " ".join(p for p in [self.first_name, self.last_name] if p) or "(unnamed contact)"

    def __str__(self):
        if self.organization_id:
            return f"{self.full_name} ({self.organization.name})"
        return self.full_name

    def get_absolute_url(self):
        return reverse("contact_detail", args=[self.pk])

    @property
    def is_confidential_client(self):
        return self.is_client or bool(self.organization_id and self.organization.is_client)
