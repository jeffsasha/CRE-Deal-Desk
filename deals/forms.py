from django import forms
from django.utils.translation import gettext_lazy

from core.fields import MoneyField, MoneyModelFormMixin
from core.forms import LocalizedForm, StyledModelForm
from core.models import User
from crm.models import Contact, Organization
from properties.models import Property

from .catalog import EVENT_CATALOG, TERM_CATALOG, TERM_CATEGORY_ORDER
from .models import (
    Activity,
    CommunicationDraft,
    Deal,
    DealEvent,
    DealLink,
    DealParty,
    Deposit,
    Issue,
    IssueStatement,
    PriceEvent,
    Representation,
    Stage,
)


def staff_users():
    return User.objects.filter(is_active=True).exclude(role="read_only")


class DealForm(MoneyModelFormMixin, StyledModelForm):
    lease_total_consideration = MoneyField(label="Total lease consideration")
    money_fields = {"lease_total_consideration": "lease_total_consideration_cents"}
    full_width = ("description", "financing_terms", "blocker_description")

    class Meta:
        model = Deal
        fields = ["name", "transaction_type", "priority", "responsible_broker", "team", "client", "time_zone",
                  "target_closing_date", "description", "financing_status", "financing_terms",
                  "next_action", "next_action_owner", "next_action_due",
                  "is_blocked", "blocked_by", "blocker_description",
                  "lease_area_sf", "lease_term_months", "lease_starting_rent", "lease_rent_unit"]
        help_texts = {
            "target_closing_date": "Internal goal only. Contractual dates come from approved contract terms.",
            "lease_starting_rent": "With the unit below; never a bare number.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible_broker"].queryset = staff_users()
        self.fields["team"].queryset = staff_users()
        self.fields["client"].queryset = Organization.objects.active()
        self.fields["team"].widget.attrs["size"] = 4

    def clean(self):
        data = super().clean()
        if data.get("lease_starting_rent") is not None and not data.get("lease_rent_unit"):
            self.add_error("lease_rent_unit", gettext_lazy("State the unit for the starting rent."))
        if data.get("is_blocked") and not data.get("blocked_by"):
            self.add_error("blocked_by", gettext_lazy("Name the party blocking the deal."))
        return data


class StageChangeForm(LocalizedForm):
    stage = forms.ModelChoiceField(queryset=Stage.objects.filter(enabled=True).exclude(category="closed"))
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False,
                             help_text="Required for Terminated or Lost.")


class PartyForm(StyledModelForm):
    class Meta:
        model = DealParty
        fields = ["role", "organization", "contact", "file_number", "is_notice_recipient", "notice_address", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.active()
        self.fields["contact"].queryset = Contact.objects.active().select_related("organization")

    def clean(self):
        data = super().clean()
        if not data.get("organization") and not data.get("contact"):
            raise forms.ValidationError("Choose a company, a contact, or both.")
        return data


class RepresentationForm(StyledModelForm):
    class Meta:
        model = Representation
        fields = ["side", "is_skw", "broker_user", "brokerage", "broker_name", "agreement_document", "notes"]

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["broker_user"].queryset = staff_users()
        self.fields["brokerage"].queryset = Organization.objects.filter(org_type="brokerage")
        if deal is not None:
            from documents.models import Document

            self.fields["agreement_document"].queryset = Document.objects.filter(links__deal=deal)


class PriceEventForm(MoneyModelFormMixin, StyledModelForm):
    amount = MoneyField(required=True, help_text="")
    money_fields = {"amount": "amount_cents"}
    MANUAL_KINDS = ["asking", "offer", "counteroffer", "requested_credit", "agreed_credit_unexecuted"]

    class Meta:
        model = PriceEvent
        fields = ["kind", "amount", "event_date", "party", "issue", "document", "notes"]
        help_texts = {"kind": "Executed contract and closing prices come from approved terms and the Closing tab."}

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [c for c in PriceEvent.KINDS if c[0] in self.MANUAL_KINDS]
        if deal is not None:
            from documents.models import Document

            self.fields["document"].queryset = Document.objects.filter(links__deal=deal)
            self.fields["issue"].queryset = deal.issues.all()


class DepositForm(MoneyModelFormMixin, StyledModelForm):
    amount = MoneyField()
    money_fields = {"amount": "amount_cents"}

    class Meta:
        model = Deposit
        fields = ["kind", "amount", "holder", "holder_contact", "due_deadline", "sent_on", "receipt_confirmed_on",
                  "receipt_evidence", "refundability", "refundability_note", "released_on", "notes"]

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["holder"].queryset = Organization.objects.active()
        self.fields["holder_contact"].queryset = Contact.objects.active()
        if deal is not None:
            from documents.models import Document

            self.fields["due_deadline"].queryset = deal.deadlines.exclude(state__in=["superseded", "cancelled"])
            self.fields["receipt_evidence"].queryset = Document.objects.filter(links__deal=deal)

    def clean(self):
        data = super().clean()
        if data.get("refundability") in {"per_contract_refundable", "per_contract_nonrefundable"} and not data.get("refundability_note"):
            self.add_error("refundability_note", gettext_lazy("Quote the contract language supporting this refundability position."))
        if data.get("receipt_confirmed_on") and not (data.get("receipt_evidence") or data.get("notes")):
            self.add_error("notes", gettext_lazy("Note how receipt was confirmed, or attach the receipt evidence."))
        return data


def event_choices(deal=None):
    choices = list(EVENT_CATALOG.items())
    if deal is not None:
        for key in deal.events.values_list("key", flat=True):
            if key not in EVENT_CATALOG:
                choices.append((key, key.replace("_", " ").capitalize()))
    return choices


class EventForm(StyledModelForm):
    key = forms.ChoiceField(label="Event")

    class Meta:
        model = DealEvent
        fields = ["key", "occurred_on", "occurred_time", "status", "evidence_document", "evidence_note"]
        labels = {"occurred_on": "Actual date the event occurred"}
        help_texts = {
            "occurred_on": "Enter the actual date (e.g. the date the title commitment was received) — not the date a file was uploaded.",
            "status": "Use 'Needs review' when the date is uncertain; dependent deadlines will not be computed from it.",
        }

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["key"].choices = event_choices(deal)
        if deal is not None:
            from documents.models import Document

            self.fields["evidence_document"].queryset = Document.objects.filter(links__deal=deal)

    def clean(self):
        data = super().clean()
        if data.get("status") == DealEvent.STATUS_CONFIRMED and not data.get("occurred_on"):
            self.add_error("occurred_on", gettext_lazy("A confirmed event needs its actual date."))
        if data.get("status") == DealEvent.STATUS_CONFIRMED and not (data.get("evidence_document") or data.get("evidence_note")):
            self.add_error("evidence_note", gettext_lazy("Record how the date is known (document or note)."))
        return data


def term_choices():
    by_cat = {}
    for key, (label, _t, cat, _a) in TERM_CATALOG.items():
        by_cat.setdefault(cat, []).append((key, label))
    return [(cat, by_cat[cat]) for cat in TERM_CATEGORY_ORDER if cat in by_cat]


class ManualTermForm(LocalizedForm):
    key = forms.ChoiceField(label="Contract term", choices=term_choices)
    value = forms.CharField(help_text="Dates as 'March 4, 2026' or 2026-03-04; money as $; periods as a number of days.")
    source_document = forms.ModelChoiceField(queryset=None, required=False,
                                             help_text="The executed document this value comes from.")
    page = forms.IntegerField(required=False, min_value=1)
    section = forms.CharField(required=False)
    quote = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False, label="Supporting text")
    note = forms.CharField(required=False, label="Reason / note",
                           help_text="Required when replacing an existing approved value.")

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        from documents.models import DocumentVersion

        self.deal = deal
        self.fields["source_document"].queryset = DocumentVersion.objects.filter(document__links__deal=deal)
        self.fields["source_document"].label_from_instance = lambda v: f"{v} — {v.get_execution_status_display()}"

    def clean(self):
        from .services import parse_term_value

        data = super().clean()
        key, value = data.get("key"), data.get("value")
        if key and value:
            try:
                data["typed"] = parse_term_value(key, value)
            except ValueError as exc:
                self.add_error("value", str(exc))
        src = data.get("source_document")
        if src is not None and not src.is_executed:
            self.add_error("source_document", gettext_lazy("This document's execution is not confirmed; its terms cannot be approved yet."))
        if key and self.deal.terms.filter(key=key, status="active").exists() and not data.get("note"):
            self.add_error("note", gettext_lazy("Explain why the approved value is being replaced (e.g. correction, or cite the amendment)."))
        return data


class DealLinkForm(StyledModelForm):
    class Meta:
        model = DealLink
        fields = ["link_type", "to_deal", "notes"]
        labels = {"to_deal": "Other deal"}

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        if deal is not None:
            self.fields["to_deal"].queryset = Deal.objects.exclude(pk=deal.pk)


class ActivityForm(StyledModelForm):
    occurred_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))

    class Meta:
        model = Activity
        fields = ["kind", "direction", "occurred_at", "summary", "counterparties", "body", "document"]

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [c for c in Activity.KINDS if c[0] != "system"]
        if deal is not None:
            from documents.models import Document

            self.fields["document"].queryset = Document.objects.filter(links__deal=deal)


class IssueForm(MoneyModelFormMixin, StyledModelForm):
    requested_credit = MoneyField(help_text="A request only — it does not change the executed contract price.")
    estimated_cost = MoneyField(label="Estimated financial impact")
    money_fields = {"requested_credit": "requested_credit_cents", "estimated_cost": "estimated_cost_cents"}
    full_width = ("description", "requested_remedy", "counterparty_response", "resolution_notes", "disclosure_note")

    class Meta:
        model = Issue
        fields = ["title", "category", "severity", "status", "discovered_on", "responsible", "description",
                  "requested_remedy", "requested_credit", "estimated_cost", "counterparty_response",
                  "resolution_status", "resolution_document", "resolution_notes", "disclosure_finding", "disclosure_note"]
        help_texts = {
            "disclosure_finding": "'Not found in reviewed materials' is different from 'confirmed not disclosed'.",
            "resolution_status": "Only an executed amendment or written agreement changes contract terms.",
        }

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = staff_users()
        from documents.models import Document

        self.fields["resolution_document"].queryset = Document.objects.filter(links__deal=deal) if deal else Document.objects.all()

    def clean(self):
        data = super().clean()
        if data.get("resolution_status") == "executed" and not data.get("resolution_document"):
            self.add_error("resolution_document", gettext_lazy("An executed resolution needs the executed document."))
        return data


class IssueStatementForm(StyledModelForm):
    class Meta:
        model = IssueStatement
        fields = ["party", "statement", "statement_date", "document", "page", "document_date", "delivered_on",
                  "receipt_evidence"]
        help_texts = {
            "document_date": "The date printed on the document. It does not show when the document was delivered.",
            "delivered_on": "When it was actually delivered to us; leave blank if unknown.",
        }


class DraftForm(StyledModelForm):
    class Meta:
        model = CommunicationDraft
        fields = ["to", "subject", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 14})}


class CloseDealForm(LocalizedForm):
    actual_closing_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    total = MoneyField(label="Actual total consideration (deal level)",
                       help_text="Counted once in volume reports, regardless of how many properties or sides. Blank = unknown.")
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}),
                           help_text="E.g. funding and recording confirmation.")

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.deal = deal
        if deal.is_lease:
            self.fields["actual_closing_date"].label = "Lease execution date"
            self.fields["total"].label = "Total lease consideration"
            self.fields["total"].help_text = "Reported as lease consideration, never as sales volume."
        links = list(deal.deal_properties.select_related("property"))
        self.allocation_fields = []
        if len(links) > 1:
            for link in links:
                name = f"alloc_{link.pk}"
                self.fields[name] = MoneyField(label=f"Allocation — {link.property.name}",
                                               help_text="Optional. If any are given, all must add up to the total.",
                                               initial=link.allocated_price_cents)
                self.allocation_fields.append((name, link))

    def allocations(self):
        return {link.pk: self.cleaned_data.get(name) for name, link in self.allocation_fields
                if self.cleaned_data.get(name) is not None}


# --- Guided "New deal" ----------------------------------------------------------
from django.utils.translation import gettext_lazy as _  # noqa: E402

from core.choices import PROPERTY_TYPES  # noqa: E402

KIND_CHOICES = [("sale", _("Sale / purchase")), ("lease", _("Lease")), ("business", _("Business"))]
SIDE_CHOICES = {
    "sale": [("buyer", _("Buyer")), ("seller", _("Seller")), ("both", _("Both sides"))],
    "lease": [("tenant", _("Tenant")), ("landlord", _("Landlord")), ("both", _("Both sides"))],
    "business": [("buyer", _("Buying a business")), ("seller", _("Selling a business")), ("both", _("Both sides"))],
}
ALL_SIDES = ["buyer", "seller", "tenant", "landlord", "both"]
LEASE_TYPES_CHOICES = [("lease", _("New lease")), ("lease_renewal", _("Renewal")), ("lease_expansion", _("Expansion")),
                       ("lease_assignment", _("Assignment"))]
# Labels for the client fields, by (kind, side): (first client, second client)
CLIENT_LABELS = {
    ("sale", "buyer"): (_("Buyer (our client)"), None),
    ("sale", "seller"): (_("Seller (our client)"), None),
    ("sale", "both"): (_("Buyer"), _("Seller")),
    ("lease", "tenant"): (_("Tenant (our client)"), None),
    ("lease", "landlord"): (_("Landlord (our client)"), None),
    ("lease", "both"): (_("Tenant"), _("Landlord")),
    ("business", "buyer"): (_("Buyer (our client)"), None),
    ("business", "seller"): (_("Business owner / seller (our client)"), None),
    ("business", "both"): (_("Buyer"), _("Seller")),
}


class NewDealForm(LocalizedForm):
    kind = forms.ChoiceField(choices=KIND_CHOICES, widget=forms.RadioSelect)
    side = forms.ChoiceField(choices=[(s, s) for s in ALL_SIDES], widget=forms.RadioSelect)
    lease_type = forms.ChoiceField(choices=LEASE_TYPES_CHOICES, required=False, initial="lease")
    property_mode = forms.ChoiceField(choices=[("existing", _("Existing property")), ("new", _("New property")),
                                               ("none", _("No property yet"))], initial="new", widget=forms.RadioSelect)
    property = forms.ModelChoiceField(queryset=Property.objects.active(), required=False)
    new_address = forms.CharField(required=False, label=_("Street address"))
    new_city = forms.CharField(required=False, initial="Houston", label=_("City"))
    new_type = forms.ChoiceField(choices=PROPERTY_TYPES, required=False, initial="retail", label=_("Property type"))
    suite = forms.CharField(required=False, label=_("Suite"))
    client_a = forms.CharField(required=False)
    client_b = forms.CharField(required=False)
    responsible_broker = forms.ModelChoiceField(queryset=User.objects.none(), required=False, label=_("Responsible broker"))
    stage = forms.ModelChoiceField(queryset=Stage.objects.none(), label=_("Stage"))
    name = forms.CharField(required=False, label=_("Deal name"), help_text=_("Optional — generated from the property and deal type."))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible_broker"].queryset = staff_users()
        self.fields["stage"].queryset = Stage.objects.filter(enabled=True, category="active")
        self.fields["stage"].initial = Stage.objects.filter(key="lead").first()

    def clean(self):
        d = super().clean()
        kind, side = d.get("kind"), d.get("side")
        if kind and side and side not in dict(SIDE_CHOICES[kind]):
            self.add_error("side", _("Choose who we represent for this kind of deal."))
        mode = d.get("property_mode")
        if mode == "existing" and not d.get("property"):
            self.add_error("property", _("Choose the property."))
        if mode == "new" and not d.get("new_address"):
            self.add_error("new_address", _("Enter the street address."))
        if mode == "none" and kind != "business" and not d.get("name"):
            self.add_error("name", _("Without a property, give the deal a name."))
        return d
