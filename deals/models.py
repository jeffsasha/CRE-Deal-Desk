import builtins

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.choices import RATE_UNITS, REPRESENTED_SIDES, TIME_ZONES
from core.money import format_cents
from core.models import Archivable, Imported, TimeStamped

from .catalog import event_label, term_label

User = settings.AUTH_USER_MODEL


class Stage(models.Model):
    CATEGORY_ACTIVE = "active"
    CATEGORY_CLOSED = "closed"
    CATEGORY_ON_HOLD = "on_hold"
    CATEGORY_TERMINATED = "terminated"
    CATEGORY_LOST = "lost"
    CATEGORY_ARCHIVED = "archived"
    CATEGORIES = [
        (CATEGORY_ACTIVE, "Active"),
        (CATEGORY_CLOSED, "Closed"),
        (CATEGORY_ON_HOLD, "On hold"),
        (CATEGORY_TERMINATED, "Terminated"),
        (CATEGORY_LOST, "Lost"),
        (CATEGORY_ARCHIVED, "Archived"),
    ]

    key = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    order = models.PositiveIntegerField(default=0)
    category = models.CharField(max_length=20, choices=CATEGORIES, default=CATEGORY_ACTIVE)
    is_contract_stage = models.BooleanField(
        default=False, help_text="Deal is under an executed contract or lease at this stage."
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.name


DEFAULT_STAGES = [
    ("lead", "Lead", "active", False),
    ("evaluating", "Evaluating", "active", False),
    ("listed", "Listed", "active", False),
    ("touring", "Touring", "active", False),
    ("loi", "LOI", "active", False),
    ("negotiating", "Negotiating", "active", False),
    ("under_contract", "Under Contract", "active", True),
    ("due_diligence", "Due Diligence", "active", True),
    ("preparing_to_close", "Preparing to Close", "active", True),
    ("closed", "Closed", "closed", True),
    ("on_hold", "On Hold", "on_hold", False),
    ("terminated", "Terminated", "terminated", False),
    ("lost", "Lost", "lost", False),
    ("archived", "Archived", "archived", False),
]


def ensure_default_stages():
    for order, (key, name, category, contract) in enumerate(DEFAULT_STAGES):
        Stage.objects.get_or_create(
            key=key, defaults={"name": name, "order": order * 10, "category": category, "is_contract_stage": contract}
        )


TRANSACTION_TYPES = [
    ("purchase", _("Purchase")),
    ("sale", _("Sale")),
    ("land_purchase", _("Land purchase")),
    ("land_sale", _("Land sale")),
    ("lease", _("Lease")),
    ("lease_renewal", _("Lease renewal")),
    ("lease_expansion", _("Lease expansion")),
    ("lease_assignment", _("Lease assignment")),
    ("business_asset", _("Business sale")),
]
SALE_TYPES = {"purchase", "sale", "land_purchase", "land_sale"}
LEASE_TYPES = {"lease", "lease_renewal", "lease_expansion", "lease_assignment"}
BUSINESS_TYPES = {"business_asset"}

PRIORITIES = [("low", _("Low")), ("normal", _("Normal")), ("high", _("High")), ("critical", _("Critical"))]


class Deal(TimeStamped, Archivable, Imported):
    internal_id = models.CharField("Internal ID", max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=255)
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    stage = models.ForeignKey(Stage, on_delete=models.PROTECT, related_name="deals")
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="normal")
    responsible_broker = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="responsible_deals"
    )
    team = models.ManyToManyField(User, blank=True, related_name="team_deals")
    client = models.ForeignKey(
        "crm.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="client_deals"
    )
    description = models.TextField(blank=True)
    time_zone = models.CharField(max_length=64, choices=TIME_ZONES, default="America/Chicago")

    # Dates. Contractual values are synchronized from approved terms/events; the
    # target closing date is an internal goal and never drives contract deadlines.
    effective_date = models.DateField(null=True, blank=True, editable=False)
    contractual_closing_date = models.DateField(null=True, blank=True, editable=False)
    target_closing_date = models.DateField("Internal target closing date", null=True, blank=True)
    actual_closing_date = models.DateField(null=True, blank=True)

    # Price fields that are distinct values. Negotiation history lives in PriceEvent.
    executed_contract_price_cents = models.BigIntegerField(null=True, blank=True, editable=False)
    actual_closing_price_cents = models.BigIntegerField(
        "Actual total consideration at closing", null=True, blank=True,
        help_text="Deal-level total consideration, counted once regardless of how many properties are attached.",
    )

    # Lease metrics (reported separately from sales volume).
    lease_area_sf = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    lease_term_months = models.PositiveIntegerField(null=True, blank=True)
    lease_starting_rent = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    lease_rent_unit = models.CharField(max_length=20, choices=RATE_UNITS, blank=True)
    lease_total_consideration_cents = models.BigIntegerField(null=True, blank=True)
    # Lease economics entered with the deal (all optional). The NNN charge uses the
    # rent's unit; utilities and TI have their own.
    LEASE_BASES = [("nnn", "NNN"), ("gross", "Gross")]
    TI_UNITS = [("usd_total", _("Lump sum ($)")), ("usd_sf", _("$/SF"))]
    lease_rent_basis = models.CharField(max_length=10, choices=LEASE_BASES, blank=True)
    lease_nnn_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    lease_utility_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    lease_utility_unit = models.CharField(max_length=20, choices=RATE_UNITS, default="usd_month", blank=True)
    lease_free_rent_months = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    lease_ti_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    lease_ti_unit = models.CharField(max_length=20, choices=TI_UNITS, default="usd_total", blank=True)
    lease_escalation_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    financing_terms = models.TextField(blank=True)
    FINANCING_STATUS = [
        ("not_applicable", _("Not applicable / cash")),
        ("unknown", _("Unknown")),
        ("pending", _("Contingency pending")),
        ("satisfied", _("Satisfied")),
        ("waived", _("Waived")),
        ("failed", _("Failed")),
    ]
    financing_status = models.CharField(max_length=20, choices=FINANCING_STATUS, default="unknown")

    next_action = models.CharField(max_length=255, blank=True)
    next_action_owner = models.CharField(max_length=120, blank=True)
    next_action_due = models.DateField(null=True, blank=True)
    is_blocked = models.BooleanField(default=False)
    blocked_by = models.CharField("Blocked by (party)", max_length=255, blank=True)
    blocker_description = models.TextField(blank=True)
    termination_reason = models.TextField("Termination / lost reason", blank=True)

    # Listing (SKW represents the seller / landlord and the property is on the market).
    listing_date = models.DateField("Listed on", null=True, blank=True)
    listing_expires_on = models.DateField("Listing agreement expires", null=True, blank=True)
    asking_price_cents = models.BigIntegerField("Asking price / rent", null=True, blank=True)
    asking_price_unit = models.CharField(max_length=20, choices=RATE_UNITS, default="usd_total", blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.internal_id} {self.name}"

    def save(self, *args, **kwargs):
        if not self.internal_id:
            year = timezone.localdate().year
            prefix = f"D-{year}-"
            last = Deal.objects.filter(internal_id__startswith=prefix).order_by("-internal_id").first()
            seq = int(last.internal_id.rsplit("-", 1)[1]) + 1 if last else 1
            self.internal_id = f"{prefix}{seq:04d}"
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("deal_detail", args=[self.pk])

    @property
    def is_sale(self):
        return self.transaction_type in SALE_TYPES

    @property
    def is_lease(self):
        return self.transaction_type in LEASE_TYPES

    @property
    def is_business_asset(self):
        return self.transaction_type in BUSINESS_TYPES

    @property
    def is_closed(self):
        return self.stage.category == Stage.CATEGORY_CLOSED

    @property
    def is_active(self):
        return self.stage.category == Stage.CATEGORY_ACTIVE and self.archived_at is None

    @property
    def status_key(self):
        """The only statuses shown: active (incl. on hold), closed, terminated (incl. lost)."""
        cat = self.stage.category
        if cat == Stage.CATEGORY_CLOSED:
            return "closed"
        if cat in (Stage.CATEGORY_TERMINATED, Stage.CATEGORY_LOST):
            return "terminated"
        return "active"

    @property
    def primary_property(self):
        link = self.deal_properties.select_related("property").order_by("-is_primary", "id").first()
        return link.property if link else None

    def active_terms(self):
        return {t.key: t for t in self.terms.filter(status=DealTerm.STATUS_ACTIVE)}


class DealProperty(models.Model):
    """Links a deal to one of possibly many properties (and optionally a suite).
    Allocated prices are informational; they are never added to deal-level
    consideration in reports."""

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="deal_properties")
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="deal_links")
    space = models.ForeignKey("properties.Space", null=True, blank=True, on_delete=models.SET_NULL)
    is_primary = models.BooleanField(default=False)
    allocated_price_cents = models.BigIntegerField(null=True, blank=True)
    allocation_basis = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("deal", "property", "space")]
        ordering = ["-is_primary", "id"]


PARTY_ROLES = [
    ("buyer", _("Buyer")),
    ("seller", _("Seller")),
    ("landlord", _("Landlord")),
    ("tenant", _("Tenant")),
    ("assignor", _("Assignor")),
    ("assignee", _("Assignee")),
    ("guarantor", _("Guarantor")),
    ("title_company", _("Title company")),
    ("escrow_officer", _("Escrow officer")),
    ("surveyor", _("Surveyor")),
    ("inspector", _("Inspector")),
    ("environmental", _("Environmental consultant")),
    ("lender", _("Lender")),
    ("appraiser", _("Appraiser")),
    ("attorney", _("Attorney")),
    ("insurance_agent", _("Insurance agent")),
    ("cooperating_broker", _("Cooperating broker")),
    ("referral_broker", _("Referral broker")),
    ("property_manager", _("Property manager")),
    ("other", _("Other")),
]


class DealParty(models.Model):
    name = models.CharField(max_length=255, blank=True)
    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="parties")
    role = models.CharField(max_length=30, choices=PARTY_ROLES)
    organization = models.ForeignKey("crm.Organization", null=True, blank=True, on_delete=models.PROTECT)
    contact = models.ForeignKey("crm.Contact", null=True, blank=True, on_delete=models.PROTECT)
    file_number = models.CharField(max_length=80, blank=True, help_text="e.g. title GF / file number")
    is_notice_recipient = models.BooleanField(default=False)
    notice_address = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["role", "id"]

    @property
    def display_name(self):
        if self.name:
            return self.name
        if self.contact_id:
            return self.contact.full_name
        return str(self.organization) if self.organization_id else "—"

    def __str__(self):
        return f"{self.get_role_display()}: {self.display_name}"


class Representation(models.Model):
    """Who represents which side. Recorded per deal; never assumed."""

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="representations")
    side = models.CharField(max_length=20, choices=REPRESENTED_SIDES)
    is_skw = models.BooleanField("Represented by our firm", default=True)
    brokerage = models.ForeignKey("crm.Organization", null=True, blank=True, on_delete=models.SET_NULL)
    broker_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    broker_name = models.CharField(max_length=160, blank=True)
    agreement_document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["side"]

    def __str__(self):
        who = "SKW" if self.is_skw else (self.brokerage or self.broker_name or "Unrepresented / unknown")
        return f"{self.get_side_display()} — {who}"


class PriceEvent(models.Model):
    """Asking, offers, counteroffers, executed price, amendments and closing price are
    distinct records. A requested credit is not a price change."""

    KINDS = [
        ("asking", _("Asking price")),
        ("offer", _("Offer")),
        ("counteroffer", _("Counteroffer")),
        ("executed_contract", _("Executed contract price")),
        ("amendment", _("Price per executed amendment")),
        ("requested_credit", _("Requested credit / reduction (not approved)")),
        ("agreed_credit_unexecuted", _("Credit agreed in principle (not executed)")),
        ("actual_closing", _("Actual closing price")),
    ]

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="price_events")
    kind = models.CharField(max_length=30, choices=KINDS)
    amount_cents = models.BigIntegerField()
    event_date = models.DateField()
    party = models.CharField(max_length=160, blank=True, help_text="Who made the offer or request.")
    document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    issue = models.ForeignKey("deals.Issue", null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["event_date", "id"]

    def __str__(self):
        return f"{self.get_kind_display()} {format_cents(self.amount_cents)}"


class Deposit(models.Model):
    KINDS = [
        ("earnest_money", _("Earnest money")),
        ("additional_deposit", _("Additional deposit")),
        ("option_fee", _("Option / independent consideration")),
        ("security_deposit", _("Lease security deposit")),
    ]
    REFUNDABILITY = [
        ("unknown", _("Unknown — not determined")),
        ("needs_review", _("Needs review")),
        ("per_contract_refundable", _("Refundable under stated conditions (see note)")),
        ("per_contract_nonrefundable", _("Non-refundable under stated conditions (see note)")),
    ]

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="deposits")
    kind = models.CharField(max_length=30, choices=KINDS)
    amount_cents = models.BigIntegerField(null=True, blank=True)
    holder = models.ForeignKey("crm.Organization", null=True, blank=True, on_delete=models.SET_NULL)
    holder_contact = models.ForeignKey("crm.Contact", null=True, blank=True, on_delete=models.SET_NULL)
    due_deadline = models.ForeignKey("deadlines.Deadline", null=True, blank=True, on_delete=models.SET_NULL)
    sent_on = models.DateField("Sent / wired on", null=True, blank=True)
    receipt_confirmed_on = models.DateField(null=True, blank=True)
    receipt_evidence = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    refundability = models.CharField(max_length=30, choices=REFUNDABILITY, default="unknown")
    refundability_note = models.TextField(
        blank=True, help_text="Quote the controlling contract language. Never inferred from a feasibility date alone."
    )
    released_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]

    @property
    def status(self):
        if self.released_on:
            return "Released / applied"
        if self.receipt_confirmed_on:
            return "Receipt confirmed"
        if self.sent_on:
            return "Sent — awaiting receipt confirmation"
        return "Not yet deposited"

    @property
    def awaiting(self):
        return not self.receipt_confirmed_on and not self.released_on


class DealEvent(models.Model):
    """An event that actually occurred (or is recorded as needing review). Deadlines
    triggered by it remain 'Awaiting Trigger' until it is confirmed."""

    STATUS_CONFIRMED = "confirmed"
    STATUS_NEEDS_REVIEW = "needs_review"
    STATUSES = [(STATUS_CONFIRMED, "Confirmed"), (STATUS_NEEDS_REVIEW, "Needs review")]

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="events")
    key = models.CharField(max_length=60)
    occurred_on = models.DateField(null=True, blank=True)
    occurred_time = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=STATUS_CONFIRMED)
    evidence_document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    evidence_note = models.TextField(
        blank=True, help_text="How receipt or occurrence is known (e.g. escrow officer email of 3/4)."
    )
    recorded_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recorded_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("deal", "key")]
        ordering = ["occurred_on", "key"]

    @property
    def label(self):
        return event_label(self.key)

    def __str__(self):
        return f"{self.label}: {self.occurred_on or 'not recorded'}"


class DateExtension(models.Model):
    """A Feasibility Period or Closing Date extension. The contract term is changed so
    the deadline lands on new_date; this row keeps the date it replaced."""

    MILESTONES = [("feasibility", "Feasibility Period ends"), ("closing", "Closing Date")]

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="extensions")
    milestone = models.CharField(max_length=20, choices=MILESTONES)
    previous_date = models.DateField()
    new_date = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["milestone", "created_at", "pk"]

    @property
    def days(self):
        return (self.new_date - self.previous_date).days

    def __str__(self):
        return f"{self.get_milestone_display()}: {self.previous_date} -> {self.new_date}"


class DealTerm(models.Model):
    """An approved contract term. Superseded versions are kept, never overwritten."""

    STATUS_ACTIVE = "active"
    STATUS_SUPERSEDED = "superseded"
    STATUSES = [(STATUS_ACTIVE, "Active"), (STATUS_SUPERSEDED, "Superseded")]

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="terms")
    key = models.CharField(max_length=60)
    value_type = models.CharField(max_length=10)
    value_text = models.TextField(blank=True)
    value_date = models.DateField(null=True, blank=True)
    value_int = models.IntegerField(null=True, blank=True)
    value_cents = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=STATUS_ACTIVE)
    version = models.PositiveIntegerField(default=1)
    source_version = models.ForeignKey(
        "documents.DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source_field = models.ForeignKey(
        "documents.ExtractedField", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source_page = models.PositiveIntegerField(null=True, blank=True)
    source_section = models.CharField(max_length=120, blank=True)
    source_quote = models.TextField(blank=True)
    amendment = models.ForeignKey("documents.Amendment", null=True, blank=True, on_delete=models.SET_NULL)
    superseded_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    superseded_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["key", "-version"]
        indexes = [models.Index(fields=["deal", "key", "status"])]

    @property
    def label(self):
        return term_label(self.key)

    @property
    def value(self):
        return {
            "date": self.value_date,
            "days": self.value_int,
            "int": self.value_int,
            "cents": self.value_cents,
        }.get(self.value_type, self.value_text)

    def display_value(self):
        if self.value_type == "cents":
            return format_cents(self.value_cents)
        if self.value_type == "date":
            return self.value_date.strftime("%b %-d, %Y") if self.value_date else "—"
        if self.value_type == "days":
            return f"{self.value_int} days" if self.value_int is not None else "—"
        if self.value_type == "int":
            return str(self.value_int) if self.value_int is not None else "—"
        return self.value_text

    def __str__(self):
        return f"{self.label}: {self.display_value()}"


class DealLink(models.Model):
    TYPES = [
        ("depends_on", _("Depends on")),
        ("related", _("Related")),
        ("linked_business_asset", _("Business asset sale linked to")),
        ("replaces", _("Replaces / successor of")),
    ]

    from_deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="links_out")
    to_deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="links_in")
    link_type = models.CharField(max_length=30, choices=TYPES)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("from_deal", "to_deal", "link_type")]


class Activity(models.Model):
    KINDS = [
        ("note", _("Note")),
        ("email", _("Email")),
        ("call", _("Call")),
        ("meeting", _("Meeting")),
        ("showing", _("Showing / tour")),
        ("document_delivery", _("Document delivery")),
        ("decision", _("Decision")),
        ("negotiation", _("Negotiation")),
        ("follow_up", _("Follow-up")),
        ("system", _("System change")),
    ]
    DIRECTIONS = [("internal", _("Internal")), ("inbound", _("Inbound")), ("outbound", _("Outbound"))]

    deal = models.ForeignKey(Deal, null=True, blank=True, on_delete=models.CASCADE, related_name="activities")
    property = models.ForeignKey(
        "properties.Property", null=True, blank=True, on_delete=models.CASCADE, related_name="activities"
    )
    kind = models.CharField(max_length=30, choices=KINDS, default="note")
    direction = models.CharField(max_length=10, choices=DIRECTIONS, default="internal")
    occurred_at = models.DateTimeField(default=timezone.now)
    summary = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    counterparties = models.CharField(max_length=255, blank=True)
    document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        verbose_name_plural = "activities"


def log_activity(deal, summary, actor=None, kind="system", body="", document=None, prop=None):
    return Activity.objects.create(
        deal=deal, property=prop, kind=kind, summary=summary[:255], body=body, document=document, created_by=actor
    )


class Issue(TimeStamped):
    CATEGORIES = [
        ("hvac", _("HVAC")),
        ("roof", _("Roof")),
        ("structural", _("Structural")),
        ("mechanical", _("Electrical / plumbing / mechanical")),
        ("environmental", _("Environmental")),
        ("title", _("Title exception")),
        ("survey", _("Survey / encroachment")),
        ("flood", _("Flood")),
        ("zoning_use", _("Use / zoning / restrictions")),
        ("financial", _("Financial / price")),
        ("legal", _("Legal / contract")),
        ("other", _("Other")),
    ]
    SEVERITIES = [("low", _("Low")), ("medium", _("Medium")), ("high", _("High")), ("critical", _("Critical"))]
    STATUSES = [
        ("open", _("Open")),
        ("monitoring", _("Monitoring")),
        ("resolved", _("Resolved")),
        ("closed", _("Closed — no action")),
        ("withdrawn", _("Withdrawn")),
    ]
    RESOLUTION = [
        ("none", _("No resolution yet")),
        ("proposed", _("Resolution proposed")),
        ("agreed_unexecuted", _("Agreed in principle — not executed")),
        ("executed", _("Executed (amendment or written agreement)")),
    ]
    DISCLOSURE = [
        ("not_assessed", _("Not assessed")),
        ("disclosed", _("Disclosed (see source)")),
        ("not_found", _("Not found in reviewed materials")),
        ("confirmed_not_disclosed", _("Confirmed not disclosed")),
    ]

    deal = models.ForeignKey(Deal, null=True, blank=True, on_delete=models.CASCADE, related_name="issues")
    property = models.ForeignKey(
        "properties.Property", null=True, blank=True, on_delete=models.CASCADE, related_name="issues"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORIES, default="other")
    severity = models.CharField(max_length=10, choices=SEVERITIES, default="medium")
    status = models.CharField(max_length=20, choices=STATUSES, default="open")
    discovered_on = models.DateField(null=True, blank=True)
    responsible = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    requested_remedy = models.TextField(blank=True)
    requested_credit_cents = models.BigIntegerField(
        null=True, blank=True, help_text="A request only. It does not change the executed contract price."
    )
    estimated_cost_cents = models.BigIntegerField("Estimated financial impact", null=True, blank=True)
    counterparty_response = models.TextField(blank=True)
    resolution_status = models.CharField(max_length=20, choices=RESOLUTION, default="none")
    resolution_document = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolution_notes = models.TextField(blank=True)
    disclosure_finding = models.CharField(max_length=30, choices=DISCLOSURE, default="not_assessed")
    disclosure_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("issue_detail", args=[self.pk])

    @builtins.property
    def is_open(self):
        return self.status in {"open", "monitoring"}


class IssueStatement(models.Model):
    """What a party said about an issue, with document date and delivery evidence kept
    separate: an older report does not prove it was delivered earlier."""

    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="statements")
    party = models.CharField(max_length=160)
    statement = models.TextField()
    statement_date = models.DateField(null=True, blank=True)
    document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    page = models.PositiveIntegerField(null=True, blank=True)
    document_date = models.DateField("Date shown on document", null=True, blank=True)
    delivered_on = models.DateField("Date delivered to us", null=True, blank=True)
    receipt_evidence = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["statement_date", "id"]


class CommunicationDraft(TimeStamped):
    STATUSES = [("draft", _("Draft")), ("marked_sent", _("Marked as sent by user")), ("discarded", _("Discarded"))]

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="drafts")
    to = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=STATUSES, default="draft")
    generated_from = models.CharField(max_length=80, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    marked_sent_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    marked_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
