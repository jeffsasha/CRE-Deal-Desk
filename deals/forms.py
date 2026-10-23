from django import forms
from django.utils.translation import gettext, gettext_lazy

from core.choices import RATE_UNITS
from core.fields import MoneyField, MoneyModelFormMixin
from core.forms import DateInput, LocalizedForm, StyledModelForm
from core.models import User
from crm.models import Contact, Organization

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
    """Only what is edited day to day; the deal is its address."""

    lease_total_consideration = MoneyField(label="Total lease consideration")
    money_fields = {"lease_total_consideration": "lease_total_consideration_cents"}
    full_width = ("name", "description")

    class Meta:
        model = Deal
        fields = ["name", "transaction_type", "client", "lease_total_consideration", "lease_area_sf", "description"]
        labels = {"name": "Address", "description": "Notes", "lease_area_sf": "Leased area (SF)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Organization.objects.active()
        if not self.instance.is_lease:
            del self.fields["lease_total_consideration"]
            del self.fields["lease_area_sf"]


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
        fields = ["side", "is_skw", "broker_user", "brokerage", "broker_name", "notes"]

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["broker_user"].queryset = staff_users()
        self.fields["brokerage"].queryset = Organization.objects.filter(org_type="brokerage")


class PriceEventForm(MoneyModelFormMixin, StyledModelForm):
    amount = MoneyField(required=True, help_text="")
    money_fields = {"amount": "amount_cents"}
    MANUAL_KINDS = ["asking", "offer", "counteroffer", "requested_credit", "agreed_credit_unexecuted"]

    class Meta:
        model = PriceEvent
        fields = ["kind", "amount", "event_date", "party", "issue", "notes"]
        help_texts = {"kind": "Executed contract and closing prices come from approved terms and the Closing tab."}

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [c for c in PriceEvent.KINDS if c[0] in self.MANUAL_KINDS]
        if deal is not None:
            self.fields["issue"].queryset = deal.issues.all()


class DepositForm(MoneyModelFormMixin, StyledModelForm):
    amount = MoneyField()
    money_fields = {"amount": "amount_cents"}

    class Meta:
        model = Deposit
        fields = ["kind", "amount", "holder", "holder_contact", "due_deadline", "sent_on", "receipt_confirmed_on",
                  "refundability", "refundability_note", "released_on", "notes"]

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["holder"].queryset = Organization.objects.active()
        self.fields["holder_contact"].queryset = Contact.objects.active()
        if deal is not None:
            self.fields["due_deadline"].queryset = deal.deadlines.exclude(state__in=["superseded", "cancelled"])

    def clean(self):
        data = super().clean()
        if data.get("refundability") in {"per_contract_refundable", "per_contract_nonrefundable"} and not data.get("refundability_note"):
            self.add_error("refundability_note", gettext_lazy("Quote the contract language supporting this refundability position."))
        if data.get("receipt_confirmed_on") and not data.get("notes"):
            self.add_error("notes", gettext_lazy("Note how receipt was confirmed."))
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
        fields = ["key", "occurred_on", "occurred_time", "status", "evidence_note"]
        labels = {"occurred_on": "Actual date the event occurred"}
        help_texts = {
            "occurred_on": "Enter the actual date (e.g. the date the title commitment was received) — not the date a file was uploaded.",
            "status": "Use 'Needs review' when the date is uncertain; dependent deadlines will not be computed from it.",
        }

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["key"].choices = event_choices(deal)

    def clean(self):
        data = super().clean()
        if data.get("status") == DealEvent.STATUS_CONFIRMED and not data.get("occurred_on"):
            self.add_error("occurred_on", gettext_lazy("A confirmed event needs its actual date."))
        if data.get("status") == DealEvent.STATUS_CONFIRMED and not data.get("evidence_note"):
            self.add_error("evidence_note", gettext_lazy("Record how the date is known."))
        return data


def term_choices():
    by_cat = {}
    for key, (label, _t, cat, _a) in TERM_CATALOG.items():
        by_cat.setdefault(cat, []).append((key, label))
    return [(cat, by_cat[cat]) for cat in TERM_CATEGORY_ORDER if cat in by_cat]


class ManualTermForm(LocalizedForm):
    key = forms.ChoiceField(label="Contract term", choices=term_choices)
    value = forms.CharField(help_text="Dates as 'March 4, 2026' or 2026-03-04; money as $; periods as a number of days.")
    note = forms.CharField(required=False, label="Reason / note",
                           help_text="Required when replacing an existing approved value.")

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.deal = deal

    def clean(self):
        from .services import parse_term_value

        data = super().clean()
        key, value = data.get("key"), data.get("value")
        if key and value:
            try:
                data["typed"] = parse_term_value(key, value)
            except ValueError as exc:
                self.add_error("value", str(exc))
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
        fields = ["kind", "direction", "occurred_at", "summary", "counterparties", "body"]

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [c for c in Activity.KINDS if c[0] != "system"]


class IssueForm(MoneyModelFormMixin, StyledModelForm):
    requested_credit = MoneyField(help_text="A request only — it does not change the executed contract price.")
    estimated_cost = MoneyField(label="Estimated financial impact")
    money_fields = {"requested_credit": "requested_credit_cents", "estimated_cost": "estimated_cost_cents"}
    full_width = ("description", "requested_remedy", "counterparty_response", "resolution_notes", "disclosure_note")

    class Meta:
        model = Issue
        fields = ["title", "category", "severity", "status", "discovered_on", "responsible", "description",
                  "requested_remedy", "requested_credit", "estimated_cost", "counterparty_response",
                  "resolution_status", "resolution_notes", "disclosure_finding", "disclosure_note"]
        help_texts = {
            "disclosure_finding": "'Not found in reviewed materials' is different from 'confirmed not disclosed'.",
            "resolution_status": "Only an executed amendment or written agreement changes contract terms.",
        }

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = staff_users()

    def clean(self):
        data = super().clean()
        if data.get("resolution_status") == "executed" and not data.get("resolution_notes"):
            self.add_error("resolution_notes", gettext_lazy("Identify the executed amendment or written agreement."))
        return data


class IssueStatementForm(StyledModelForm):
    class Meta:
        model = IssueStatement
        fields = ["party", "statement", "statement_date", "document_date", "delivered_on"]
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
    actual_closing_date = forms.DateField(widget=DateInput())
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
    # A deal is its address: the property record behind it is found or created from it.
    street = forms.CharField(label=_("Street address"))
    suite = forms.CharField(required=False, label=_("Suite"))
    city = forms.CharField(initial="Houston", label=_("City"))
    zip_code = forms.CharField(required=False, label=_("ZIP"))
    client_a = forms.CharField(required=False)
    client_b = forms.CharField(required=False)
    stage = forms.ModelChoiceField(queryset=Stage.objects.none(), label=_("Stage"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].queryset = Stage.objects.filter(enabled=True, category="active")
        self.fields["stage"].initial = Stage.objects.filter(key="lead").first()
        self.fields["stage"].label_from_instance = lambda st: gettext(st.name)

    def clean(self):
        d = super().clean()
        kind, side = d.get("kind"), d.get("side")
        if kind and side and side not in dict(SIDE_CHOICES[kind]):
            self.add_error("side", _("Choose who we represent for this kind of deal."))
        return d


class KeyDatesForm(LocalizedForm):
    """Effective Date plus contract periods; deadlines are computed from these."""

    effective_date = forms.DateField(label="Effective Date", required=False, widget=DateInput(),
                                     help_text="As defined in the executed contract.")
    feasibility_days = forms.IntegerField(label="Feasibility Period (days)", required=False, min_value=0,
                                          help_text="Calendar days after the Effective Date.")
    closing_mode = forms.ChoiceField(label="Closing Date is", initial="days", widget=forms.RadioSelect,
                                     choices=[("days", "Days after the Effective Date"), ("date", "A fixed date")])
    closing_days = forms.IntegerField(label="Closing (days after Effective Date)", required=False, min_value=0)
    closing_date = forms.DateField(label="Closing Date", required=False, widget=DateInput())
    commencement_date = forms.DateField(label="Commencement Date", required=False,
                                        widget=DateInput())
    next_business_day = forms.BooleanField(
        label="Contract moves a deadline on a weekend or holiday to the next business day", required=False)

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        drop = ["feasibility_days", "closing_mode", "closing_days", "closing_date"] if deal.is_lease else ["commencement_date"]
        for name in drop:
            del self.fields[name]

    def clean(self):
        data = super().clean()
        mode = data.get("closing_mode")
        if mode == "date" and data.get("closing_date") and data.get("effective_date") \
                and data["closing_date"] < data["effective_date"]:
            self.add_error("closing_date", gettext_lazy("The Closing Date is before the Effective Date."))
        return data


class ExtensionForm(LocalizedForm):
    """Extend the Feasibility Period or the Closing Date: a new date, or a number of days."""

    milestone = forms.ChoiceField(label="Extend", widget=forms.RadioSelect,
                                  choices=[("feasibility", "Feasibility Period ends"), ("closing", "Closing Date")])
    new_date = forms.DateField(label="New date", required=False, widget=DateInput())
    days = forms.IntegerField(label="Or extend by (days)", required=False, min_value=1,
                              help_text="Counted from the current date.")
    shift_closing = forms.BooleanField(label="Move the Closing Date by the same number of days", required=False)
    note = forms.CharField(label="Note", required=False, max_length=255,
                           help_text="e.g. First extension, extension fee paid.")

    def clean(self):
        data = super().clean()
        if bool(data.get("new_date")) == bool(data.get("days")):
            raise forms.ValidationError(gettext_lazy("Enter either the new date or the number of days."))
        if data.get("milestone") != "feasibility":
            data["shift_closing"] = False
        return data


class SkwCommissionForm(LocalizedForm):
    expected = MoneyField(label="SKW commission (expected)", help_text="What SKW Realty expects to receive. Blank = unknown.")


class ReceiptForm(LocalizedForm):
    amount = MoneyField(label="Amount received", required=True)
    entry_date = forms.DateField(label="Date received", widget=DateInput())
    reference = forms.CharField(label="Check / wire reference", required=False, max_length=120)


class ListingForm(LocalizedForm):
    listing_date = forms.DateField(label="Listed on", required=False, widget=DateInput())
    listing_expires_on = forms.DateField(label="Listing agreement expires", required=False,
                                         widget=DateInput(),
                                         help_text="Added to the calendar with reminders.")
    asking_price = MoneyField(label="Asking price / rent", help_text="Blank = not set.")
    asking_price_unit = forms.ChoiceField(label="Unit", choices=RATE_UNITS, initial="usd_total")

    def clean(self):
        data = super().clean()
        if data.get("listing_date") and data.get("listing_expires_on") and data["listing_expires_on"] < data["listing_date"]:
            self.add_error("listing_expires_on", gettext_lazy("The listing cannot expire before it was listed."))
        data["asking_price_cents"] = data.get("asking_price")
        return data
