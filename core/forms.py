from django import forms
from django.contrib.auth.password_validation import validate_password

from deals.models import Stage

from .models import Holiday, User


class DateInput(forms.DateInput):
    """Browser date picker. The value must be ISO (YYYY-MM-DD) whatever the interface
    language, or the browser shows an empty field and the date is lost on save."""

    input_type = "date"

    def __init__(self, attrs=None, format="%Y-%m-%d"):
        super().__init__(attrs=attrs, format=format)


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, attrs=None, format="%H:%M"):
        super().__init__(attrs=attrs, format=format)


def localize_fields(form):
    """Translate labels, help text and static choices of a bound form into the
    active language. The English strings are collected for translators by
    `manage.py collect_strings`."""
    from django.forms.utils import pretty_name
    from django.utils.translation import gettext, pgettext

    def tr(value):
        return gettext(str(value)) if value else value

    for name, field in form.fields.items():
        field.label = pgettext("record heading", "Title") if name == "title" else tr(field.label if field.label is not None else pretty_name(name))
        field.help_text = tr(field.help_text)
        if isinstance(field, forms.ChoiceField) and not isinstance(field, forms.ModelChoiceField):
            translated = []
            for value, label in field.choices:
                if isinstance(label, (list, tuple)):
                    translated.append((tr(value), [(v, tr(lab)) for v, lab in label]))
                else:
                    translated.append((value, tr(label)))
            field.choices = translated


class LocalizedFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        localize_fields(self)


class LocalizedForm(LocalizedFormMixin, forms.Form):
    pass


class StyledModelForm(LocalizedFormMixin, forms.ModelForm):
    """ModelForm with HTML5 date/time widgets and compact textareas."""

    full_width = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, forms.DateField):
                field.widget = DateInput(format="%Y-%m-%d")
            elif isinstance(field, forms.TimeField):
                field.widget = TimeInput(format="%H:%M")
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("rows", 3)


class UserCreateForm(StyledModelForm):
    password = forms.CharField(widget=forms.PasswordInput, help_text="At least 12 characters.")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "job_title", "role", "is_designated_broker",
                  "time_zone", "email_reminders"]

    def clean_password(self):
        pw = self.cleaned_data["password"]
        validate_password(pw)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class UserEditForm(StyledModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "job_title", "role", "is_designated_broker", "is_active",
                  "time_zone", "email_reminders"]


class StageForm(StyledModelForm):
    class Meta:
        model = Stage
        fields = ["name", "order", "category", "is_contract_stage", "enabled"]


class HolidayForm(StyledModelForm):
    class Meta:
        model = Holiday
        fields = ["date", "name"]


class ReminderDefaultsForm(LocalizedForm):
    reminder_days = forms.CharField(
        label="Default reminder lead times (days before due date)",
        help_text="Comma-separated, e.g. 7, 3, 1, 0. Each deadline can override this.",
    )

    def clean_reminder_days(self):
        try:
            values = sorted({int(x.strip()) for x in self.cleaned_data["reminder_days"].split(",") if x.strip()},
                            reverse=True)
        except ValueError as exc:
            raise forms.ValidationError("Enter whole numbers separated by commas.") from exc
        if not values or any(v < 0 or v > 365 for v in values):
            raise forms.ValidationError("Use values between 0 and 365.")
        return values
