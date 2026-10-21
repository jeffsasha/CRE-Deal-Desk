"""Commission ledger.

Separate records for: the agreement (what is payable and how it is calculated),
allocations (who is entitled to which share), installments (when amounts are earned
and invoiced), and immutable ledger entries (cash actually received, distributed,
refunded or reversed). Status is always derived from these records.
"""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.choices import REPRESENTED_SIDES
from core.models import Archivable, Imported, TimeStamped

User = settings.AUTH_USER_MODEL


class CommissionAgreement(TimeStamped, Archivable, Imported):
    BASIS_TYPES = [
        ("percentage", "Percentage of a stated basis"),
        ("flat", "Flat fee"),
        ("tiered", "Tiered percentage"),
        ("custom", "Custom (gross amount stated directly)"),
    ]
    STATUSES = [
        ("draft", "Draft / unsigned"),
        ("active", "Executed / in effect"),
        ("disputed", "Disputed"),
        ("void", "Void / terminated"),
    ]

    deal = models.ForeignKey("deals.Deal", on_delete=models.PROTECT, related_name="commission_agreements")
    title = models.CharField(max_length=255)
    document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=STATUSES, default="active")
    payer = models.ForeignKey("crm.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    payer_name = models.CharField(max_length=255, blank=True)
    legal_payee = models.CharField(max_length=255, default="SKW Realty LLC")
    represented_side = models.CharField(max_length=20, choices=REPRESENTED_SIDES)

    basis_type = models.CharField(max_length=20, choices=BASIS_TYPES)
    basis_description = models.CharField(
        max_length=255, blank=True, help_text="e.g. 'Gross sales price' or 'Aggregate base rent, initial term'."
    )
    basis_amount_cents = models.BigIntegerField(null=True, blank=True)
    rate_percent = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    flat_amount_cents = models.BigIntegerField(null=True, blank=True)
    tiers = models.JSONField(
        default=list, blank=True, help_text='[{"up_to_cents": 100000000, "rate_percent": "6"}, {"up_to_cents": null, "rate_percent": "4"}]'
    )
    stated_gross_cents = models.BigIntegerField(null=True, blank=True, help_text="Used for the custom basis type.")
    earning_conditions = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("commission_detail", args=[self.pk])


class CommissionAdjustment(models.Model):
    agreement = models.ForeignKey(CommissionAgreement, on_delete=models.CASCADE, related_name="adjustments")
    amount_cents = models.BigIntegerField(help_text="Positive increases, negative decreases the gross commission.")
    reason = models.CharField(max_length=255)
    document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)


class CommissionAllocation(models.Model):
    """Who is entitled to what.

    level='payer': division of the gross commission among brokerages / referral
    parties (including SKW's own share). `paid_through_skw` means the payer remits
    this share to SKW, which then distributes it.

    level='internal': distribution of SKW's share to individuals (e.g. the designated
    broker) or the house. No fixed split is ever assumed.
    """

    LEVELS = [("payer", "Division of gross commission"), ("internal", "Distribution of SKW share")]
    RECIPIENT_TYPES = [
        ("skw", "SKW Realty LLC (brokerage share)"),
        ("cooperating_broker", "Cooperating broker"),
        ("referral", "Referral"),
        ("agent", "Agent"),
        ("designated_broker", "Designated broker"),
        ("house", "House / retained by SKW"),
        ("other", "Other"),
    ]
    METHODS = [
        ("percent_of_gross", "Percent of gross commission"),
        ("percent_of_skw", "Percent of SKW share"),
        ("flat", "Fixed amount"),
        ("unknown", "Unknown / to be determined"),
    ]

    agreement = models.ForeignKey(CommissionAgreement, on_delete=models.CASCADE, related_name="allocations")
    level = models.CharField(max_length=10, choices=LEVELS)
    recipient_type = models.CharField(max_length=30, choices=RECIPIENT_TYPES)
    recipient_name = models.CharField(max_length=255)
    recipient_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recipient_org = models.ForeignKey("crm.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    method = models.CharField(max_length=20, choices=METHODS)
    percent = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    amount_cents = models.BigIntegerField(null=True, blank=True)
    paid_through_skw = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["level", "id"]

    def __str__(self):
        return f"{self.recipient_name} ({self.get_level_display()})"

    @property
    def is_designated_broker(self):
        return bool(self.recipient_user_id and self.recipient_user.is_designated_broker)


class CommissionInstallment(models.Model):
    """An amount expected to be received by SKW, earned on a condition (closing, lease
    execution, occupancy, ...)."""

    EARNED = [
        ("not_earned", "Not yet earned"),
        ("earned", "Earned"),
        ("waived", "Waived"),
        ("cancelled", "Cancelled"),
    ]

    agreement = models.ForeignKey(CommissionAgreement, on_delete=models.CASCADE, related_name="installments")
    sequence = models.PositiveIntegerField(default=1)
    label = models.CharField(max_length=160)
    amount_cents = models.BigIntegerField(null=True, blank=True, help_text="Blank means unknown, not zero.")
    trigger_description = models.CharField(max_length=255, blank=True)
    earned_status = models.CharField(max_length=20, choices=EARNED, default="not_earned")
    earned_on = models.DateField(null=True, blank=True)
    invoice_number = models.CharField(max_length=60, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    expected_payment_date = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["sequence", "id"]

    def __str__(self):
        return self.label


class LedgerEntry(models.Model):
    """Immutable cash record. Corrections are made with a reversal entry."""

    TYPES = [
        ("receipt", "Receipt — cash received by SKW"),
        ("distribution", "Distribution — paid by SKW to a recipient"),
        ("direct_payment", "Direct payment — paid by payer directly to a recipient"),
        ("refund", "Refund — returned by SKW to payer"),
        ("reversal", "Reversal of an earlier entry"),
    ]

    agreement = models.ForeignKey(CommissionAgreement, on_delete=models.PROTECT, related_name="ledger_entries")
    installment = models.ForeignKey(CommissionInstallment, null=True, blank=True, on_delete=models.PROTECT)
    allocation = models.ForeignKey(CommissionAllocation, null=True, blank=True, on_delete=models.PROTECT)
    entry_type = models.CharField(max_length=20, choices=TYPES)
    amount_cents = models.BigIntegerField(help_text="Always positive; the entry type determines direction.")
    entry_date = models.DateField()
    reference = models.CharField(max_length=120, blank=True, help_text="Check, wire or ACH reference.")
    proof_document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )
    notes = models.TextField(blank=True)
    import_batch = models.ForeignKey("imports.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["entry_date", "id"]
        verbose_name_plural = "ledger entries"
        constraints = [models.CheckConstraint(condition=models.Q(amount_cents__gt=0), name="ledger_amount_positive")]

    def __str__(self):
        return f"{self.get_entry_type_display()} {self.amount_cents / 100:,.2f} on {self.entry_date}"

    @property
    def is_reversed(self):
        return hasattr(self, "reversed_by")
