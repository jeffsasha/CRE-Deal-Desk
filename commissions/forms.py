import json

from django import forms
from django.utils.translation import gettext_lazy

from core.fields import MoneyField, MoneyModelFormMixin
from core.forms import DateInput, LocalizedForm, StyledModelForm
from core.models import User
from crm.models import Organization
from deals.models import Deal

from .models import CommissionAdjustment, CommissionAgreement, CommissionAllocation, CommissionInstallment, LedgerEntry


class AgreementForm(MoneyModelFormMixin, StyledModelForm):
    basis_amount = MoneyField(label="Basis amount", help_text="The consideration the rate applies to. Blank = unknown.")
    flat_amount = MoneyField(label="Flat fee")
    stated_gross = MoneyField(label="Stated gross commission", help_text="For the custom basis type.")
    tiers_text = forms.CharField(required=False, label="Tiers (JSON)", widget=forms.Textarea(attrs={"rows": 3}),
                                 help_text='e.g. [{"up_to_cents": 100000000, "rate_percent": "6"}, {"up_to_cents": null, "rate_percent": "4"}]')
    money_fields = {"basis_amount": "basis_amount_cents", "flat_amount": "flat_amount_cents", "stated_gross": "stated_gross_cents"}

    class Meta:
        model = CommissionAgreement
        fields = ["deal", "title", "document", "status", "payer", "payer_name", "legal_payee", "represented_side",
                  "basis_type", "basis_description", "basis_amount", "rate_percent", "flat_amount", "tiers_text",
                  "stated_gross", "earning_conditions", "notes"]
        help_texts = {"rate_percent": "e.g. 3.0 for 3%."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deal"].queryset = Deal.objects.active()
        self.fields["payer"].queryset = Organization.objects.active()
        deal = self.initial.get("deal") or (self.instance.deal if self.instance.pk else None)
        from documents.models import Document

        self.fields["document"].queryset = Document.objects.filter(links__deal=deal) if deal else Document.objects.filter(category="commission_agreement")
        if self.instance.pk and self.instance.tiers:
            self.initial["tiers_text"] = json.dumps(self.instance.tiers)

    def clean(self):
        data = super().clean()
        bt = data.get("basis_type")
        if bt == "percentage" and data.get("rate_percent") is None:
            self.add_error("rate_percent", gettext_lazy("Enter the percentage."))
        if bt == "flat" and data.get("flat_amount") is None:
            self.add_error("flat_amount", gettext_lazy("Enter the flat fee, or use 'custom' if the amount is unknown."))
        if bt == "tiered":
            try:
                tiers = json.loads(data.get("tiers_text") or "[]")
                assert isinstance(tiers, list) and tiers and all("rate_percent" in t for t in tiers)
                data["tiers"] = tiers
            except (ValueError, AssertionError):
                self.add_error("tiers_text", gettext_lazy("Enter tiers as a JSON list with rate_percent on each tier."))
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.tiers = self.cleaned_data.get("tiers", []) if obj.basis_type == "tiered" else []
        if commit:
            obj.save()
        return obj


class AllocationForm(MoneyModelFormMixin, StyledModelForm):
    amount = MoneyField(label="Fixed amount")
    money_fields = {"amount": "amount_cents"}

    class Meta:
        model = CommissionAllocation
        fields = ["level", "recipient_type", "recipient_name", "recipient_user", "recipient_org", "method", "percent",
                  "amount", "paid_through_skw", "notes"]
        help_texts = {
            "paid_through_skw": "Checked when the payer remits this share to SKW (which then distributes it).",
            "recipient_user": "Link the designated broker's user account so her receipts are reported separately.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipient_user"].queryset = User.objects.filter(is_active=True)
        self.fields["recipient_org"].queryset = Organization.objects.active()

    def clean(self):
        data = super().clean()
        m = data.get("method")
        if m in {"percent_of_gross", "percent_of_skw"} and data.get("percent") is None:
            self.add_error("percent", gettext_lazy("Enter the percentage."))
        if m == "flat" and data.get("amount") is None:
            self.add_error("amount", gettext_lazy("Enter the amount, or choose 'Unknown'."))
        if data.get("level") == "payer" and m == "percent_of_skw":
            self.add_error("method", gettext_lazy("Payer-level allocations divide the gross commission."))
        if data.get("level") == "internal" and data.get("recipient_type") == "skw":
            self.add_error("recipient_type", gettext_lazy("SKW's own share is a payer-level allocation."))
        return data


class InstallmentForm(MoneyModelFormMixin, StyledModelForm):
    amount = MoneyField(label="Amount expected by SKW")
    money_fields = {"amount": "amount_cents"}

    class Meta:
        model = CommissionInstallment
        fields = ["sequence", "label", "amount", "trigger_description", "earned_status", "earned_on", "invoice_number",
                  "invoice_date", "due_date", "expected_payment_date", "notes"]

    def clean(self):
        data = super().clean()
        if data.get("earned_status") == "earned" and not data.get("earned_on"):
            self.add_error("earned_on", gettext_lazy("An earned installment needs the date it was earned."))
        return data


class AdjustmentForm(MoneyModelFormMixin, StyledModelForm):
    amount = MoneyField(required=True, allow_negative=True, help_text="Negative to reduce.")
    money_fields = {"amount": "amount_cents"}

    class Meta:
        model = CommissionAdjustment
        fields = ["amount", "reason", "document"]


class EntryForm(LocalizedForm):
    entry_type = forms.ChoiceField(choices=[c for c in LedgerEntry.TYPES if c[0] != "reversal"])
    amount = MoneyField(required=True, help_text="Positive amount; the type determines direction.")
    entry_date = forms.DateField(widget=DateInput(), label="Date (receipt or payment date)")
    installment = forms.ModelChoiceField(queryset=CommissionInstallment.objects.none(), required=False)
    allocation = forms.ModelChoiceField(queryset=CommissionAllocation.objects.none(), required=False,
                                        label="Recipient (for distributions / direct payments)")
    reference = forms.CharField(required=False)
    proof_document = forms.ModelChoiceField(queryset=None, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, agreement=None, **kwargs):
        super().__init__(*args, **kwargs)
        from documents.models import Document

        self.fields["installment"].queryset = agreement.installments.all()
        self.fields["allocation"].queryset = agreement.allocations.all()
        self.fields["proof_document"].queryset = Document.objects.filter(links__deal=agreement.deal)


class ReverseForm(LocalizedForm):
    entry_date = forms.DateField(widget=DateInput())
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))
