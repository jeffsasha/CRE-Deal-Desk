from django import forms

from .money import MoneyParseError, format_cents, parse_cents


class MoneyField(forms.CharField):
    """Dollar input stored as integer cents. Blank means unknown (None), not zero."""

    def __init__(self, *args, allow_negative=False, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("help_text", "Leave blank if unknown.")
        self.allow_negative = allow_negative
        super().__init__(*args, **kwargs)
        self.widget.attrs.setdefault("inputmode", "decimal")
        self.widget.attrs.setdefault("placeholder", "$0.00")

    def prepare_value(self, value):
        if isinstance(value, int):
            return format_cents(value)
        return value

    def to_python(self, value):
        value = super().to_python(value)
        try:
            cents = parse_cents(value)
        except MoneyParseError as exc:
            raise forms.ValidationError("Enter a dollar amount like 1,250,000.00.") from exc
        if cents is not None and cents < 0 and not self.allow_negative:
            raise forms.ValidationError("Amount cannot be negative.")
        return cents


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
