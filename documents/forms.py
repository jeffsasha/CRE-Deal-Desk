from django import forms

from core.forms import DateInput
from crm.models import Contact, Organization
from deals.catalog import TERM_CATALOG
from deals.models import Deal, Issue
from properties.models import Property

from .models import CATEGORIES, DOC_TYPES, Document


class UploadForm(forms.Form):
    file = forms.FileField(help_text="PDF (including scans), images, DOCX, TXT, CSV or XLSX. The original is preserved unchanged.")
    title = forms.CharField(required=False, help_text="Defaults to the file name.")
    category = forms.ChoiceField(choices=CATEGORIES)
    doc_type = forms.ChoiceField(choices=DOC_TYPES, initial="unknown", label="Document type",
                                 help_text="Leave Unknown to let DealDesk suggest a type for you to confirm.")
    access_level = forms.ChoiceField(choices=Document.ACCESS, initial="standard")
    tags = forms.CharField(required=False)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    deal = forms.ModelChoiceField(queryset=Deal.objects.active(), required=False)
    property = forms.ModelChoiceField(queryset=Property.objects.active(), required=False)
    organization = forms.ModelChoiceField(queryset=Organization.objects.active(), required=False, label="Company")
    contact = forms.ModelChoiceField(queryset=Contact.objects.active(), required=False)
    issue = forms.ModelChoiceField(queryset=Issue.objects.all(), required=False)
    document_date = forms.DateField(required=False, widget=DateInput(), label="Date shown on document")
    delivered_on = forms.DateField(required=False, widget=DateInput(), label="Date delivered / received",
                                   help_text="The actual delivery date, if known. Not the upload date.")
    delivery_evidence = forms.CharField(required=False, help_text="e.g. 'Email from escrow officer 3/4/2026'")
    extract = forms.BooleanField(required=False, initial=True, label="Propose contract terms for review (contracts, leases, LOIs, amendments)")


class NewVersionForm(forms.Form):
    file = forms.FileField()
    change_note = forms.CharField(required=False)
    document_date = forms.DateField(required=False, widget=DateInput(), label="Date shown on document")
    delivered_on = forms.DateField(required=False, widget=DateInput(), label="Date delivered / received")
    delivery_evidence = forms.CharField(required=False)
    extract = forms.BooleanField(required=False, initial=True, label="Propose terms for review")


class DocumentMetaForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "category", "doc_type", "doc_type_confirmed", "access_level", "tags", "description"]


class ExecutionForm(forms.Form):
    status = forms.ChoiceField(choices=[
        ("unknown", "Unknown"),
        ("draft", "Draft / unsigned"),
        ("partially_signed", "Partially signed"),
        ("confirmed_executed", "Fully executed — I confirm"),
        ("not_applicable", "Not applicable (not an agreement)"),
    ])
    evidence = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}),
                               help_text="Required to confirm execution: how do you know it is fully signed by all parties?")


class LinkForm(forms.Form):
    deal = forms.ModelChoiceField(queryset=Deal.objects.active(), required=False)
    property = forms.ModelChoiceField(queryset=Property.objects.active(), required=False)
    organization = forms.ModelChoiceField(queryset=Organization.objects.active(), required=False, label="Company")
    contact = forms.ModelChoiceField(queryset=Contact.objects.active(), required=False)
    issue = forms.ModelChoiceField(queryset=Issue.objects.all(), required=False)


def manual_key_choices():
    return [("effective_date", "Effective date (explicit date)")] + [(k, v[0]) for k, v in TERM_CATALOG.items()]


class ManualFieldForm(forms.Form):
    key = forms.ChoiceField(choices=manual_key_choices, label="Field")
    value = forms.CharField()
    page = forms.IntegerField(required=False, min_value=1)
    section = forms.CharField(required=False)
    quote = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Supporting text")


class NotesForm(forms.Form):
    title = forms.CharField(initial="Historical transaction notes")
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": 14}), label="Pasted notes",
                           help_text="Stored as an original document (plain text). Nothing in it is interpreted as instructions or applied automatically.")
    document_date = forms.DateField(required=False, widget=DateInput(), label="Date of the notes")
