from django import forms
from django.utils.translation import gettext_lazy

from core.forms import StyledModelForm

from .models import FACT_CATALOG, AskingPrice, OperatingCharge, Parcel, Property, PropertyFact, RentRollEntry, Space


class PropertyForm(StyledModelForm):
    full_width = ("legal_description", "notes")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Street address may already contain the complete address.
        for name in ("city", "state"):
            self.fields[name].required = False

    class Meta:
        model = Property
        fields = ["name", "property_type", "street", "suite", "city", "state", "postal_code", "county",
                  "building_area_sf", "land_area_sf", "land_area_acres", "available_area_sf", "units",
                  "size_source", "size_verified_on", "owner", "ownership_entity", "occupancy_percent",
                  "legal_description", "notes"]


class ParcelForm(StyledModelForm):
    class Meta:
        model = Parcel
        fields = ["parcel_id", "county", "land_area_sf", "legal_description", "notes"]


class SpaceForm(StyledModelForm):
    class Meta:
        model = Space
        fields = ["suite", "area_sf", "floor", "status", "condition", "notes"]


class RentRollForm(StyledModelForm):
    class Meta:
        model = RentRollEntry
        fields = ["tenant_name", "space", "lease_start", "lease_end", "rent_amount", "rent_unit", "as_of", "source", "notes"]

    def __init__(self, *args, property=None, **kwargs):
        super().__init__(*args, **kwargs)
        if property is not None:
            self.fields["space"].queryset = property.spaces.all()


class AskingPriceForm(StyledModelForm):
    class Meta:
        model = AskingPrice
        fields = ["kind", "amount", "unit", "effective_date", "space", "source", "notes"]

    def __init__(self, *args, property=None, **kwargs):
        super().__init__(*args, **kwargs)
        if property is not None:
            self.fields["space"].queryset = property.spaces.all()


class ChargeForm(StyledModelForm):
    class Meta:
        model = OperatingCharge
        fields = ["charge_type", "amount", "unit", "is_estimate", "as_of", "space", "source", "verification", "notes"]

    def __init__(self, *args, property=None, **kwargs):
        super().__init__(*args, **kwargs)
        if property is not None:
            self.fields["space"].queryset = property.spaces.all()


def fact_key_choices():
    out = [("", "— Choose a fact or enter a custom one below —")]
    for cat, items in FACT_CATALOG.items():
        out += [(f"{cat}:{key}", f"{cat.replace('_', ' ').title()} · {label}") for key, label in items]
    return out


class FactForm(StyledModelForm):
    catalog_key = forms.ChoiceField(label="Fact", choices=fact_key_choices, required=False)

    class Meta:
        model = PropertyFact
        fields = ["catalog_key", "category", "label", "value", "unit", "space", "source",
                  "verification", "verified_on", "notes"]
        help_texts = {
            "verification": "Marketing statements and broker flyers are recorded as such and are never shown as verified.",
            "label": gettext_lazy("Used when no catalog fact is chosen."),
        }

    def __init__(self, *args, property=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["label"].required = False
        self.fields["category"].required = False
        if property is not None:
            self.fields["space"].queryset = property.spaces.all()
        if self.instance.pk:
            self.fields["catalog_key"].initial = f"{self.instance.category}:{self.instance.key}"

    def clean(self):
        data = super().clean()
        ck = data.get("catalog_key")
        if ck:
            cat, key = ck.split(":", 1)
            label = dict(FACT_CATALOG[cat])[key]
            data["category"], data["label"], data["_key"] = cat, label, key
        else:
            if not data.get("label"):
                self.add_error("label", gettext_lazy("Enter a label or choose a catalog fact."))
            data["category"] = data.get("category") or "other"
            data["_key"] = (data.get("label") or "").lower().replace(" ", "_")[:60]
        if data.get("verification") == "verified" and not data.get("source"):
            self.add_error("source", gettext_lazy("A verified fact needs its source."))
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.category = self.cleaned_data["category"]
        obj.label = self.cleaned_data["label"]
        obj.key = self.cleaned_data["_key"]
        if commit:
            obj.save()
        return obj
