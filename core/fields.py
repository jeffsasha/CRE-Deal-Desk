import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.validators import DecimalValidator

from .money import MoneyParseError, format_cents, parse_cents


class MoneyField(forms.CharField):
    """Dollar input stored as integer cents. Blank means unknown (None), not zero."""

    def __init__(self, *args, allow_negative=False, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("help_text", "Leave blank if unknown.")
        self.allow_negative = allow_negative
        super().__init__(*args, **kwargs)
        self.widget.attrs.setdefault("maxlength", 30)
        self.widget.attrs.setdefault("inputmode", "decimal")
        self.widget.attrs.setdefault("placeholder", "0.00")
        self.widget.attrs["data-money"] = "1"  # app.js keeps it to digits with 1,000,000.00 grouping
        if allow_negative:
            self.widget.attrs["data-money-negative"] = "1"

    def prepare_value(self, value):
        if isinstance(value, int):
            return format_cents(value).replace("$", "")
        return value

    def to_python(self, value):
        value = super().to_python(value)
        if len(value) > 30:
            raise forms.ValidationError(_("Enter a smaller dollar amount."))
        try:
            cents = parse_cents(value)
        except MoneyParseError as exc:
            raise forms.ValidationError(_("Enter a dollar amount like 1,250,000.00.")) from exc
        if cents is not None and abs(cents) > 9223372036854775807:
            raise forms.ValidationError(_("Enter a smaller dollar amount."))
        if cents is not None and cents < 0 and not self.allow_negative:
            raise forms.ValidationError(_("Amount cannot be negative."))
        return cents


class AmountField(MoneyField):
    """Same input as MoneyField (digits, grouped, two decimals) for a Decimal value
    such as a rent rate. Blank means not entered (None)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("help_text", "")
        max_digits = kwargs.pop("max_digits", 14)
        self.decimal_places = kwargs.pop("decimal_places", 2)
        super().__init__(*args, **kwargs)
        self.validators.append(DecimalValidator(max_digits, self.decimal_places))
        self.widget.attrs["data-money-decimals"] = str(self.decimal_places)

    def prepare_value(self, value):
        if isinstance(value, (Decimal, int)):
            whole, fraction = f"{value:,.{self.decimal_places}f}".split(".")
            return whole + "." + fraction.rstrip("0").ljust(2, "0")
        return super().prepare_value(value)

    def to_python(self, value):
        cents = super().to_python(value)  # Shared syntax, range and empty-value checks.
        if cents is None:
            return None
        raw = str(value).strip()
        try:
            amount = Decimal(re.sub(r"[\s$,()]", "", raw))
        except InvalidOperation as exc:
            raise forms.ValidationError(_("Enter a dollar amount like 1,250,000.00.")) from exc
        if raw.startswith("(") and raw.endswith(")"):
            amount = -abs(amount)
        if amount < 0 and not self.allow_negative:
            raise forms.ValidationError(_("Amount cannot be negative."))
        return amount


class MoneyModelFormMixin:
    """Maps MoneyField form fields onto *_cents model fields."""

    money_fields = {}  # form field name -> model attribute

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None and self.instance.pk:
            for form_name, attr in self.money_fields.items():
                self.initial.setdefault(form_name, getattr(self.instance, attr))

    def save(self, commit=True):
        obj = super().save(commit=False)
        for form_name, attr in self.money_fields.items():
            if form_name in self.cleaned_data:
                setattr(obj, attr, self.cleaned_data[form_name])
        if commit:
            obj.save()
            self.save_m2m()
        return obj
