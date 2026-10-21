from django import forms
from django.contrib.auth.password_validation import validate_password

from deals.models import Stage

from .models import Holiday, User


class DateInput(forms.DateInput):
    input_type = "date"


class TimeInput(forms.TimeInput):
    input_type = "time"


class StyledModelForm(forms.ModelForm):
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


class ReminderDefaultsForm(forms.Form):
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
