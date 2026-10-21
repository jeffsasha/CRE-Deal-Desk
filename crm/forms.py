from core.forms import StyledModelForm

from .models import Contact, Organization


class OrganizationForm(StyledModelForm):
    class Meta:
        model = Organization
        fields = ["name", "org_type", "is_client", "parent", "branch_name", "phone", "email", "website", "street", "city",
                  "state", "postal_code", "tags", "notes"]


class ContactForm(StyledModelForm):
    class Meta:
        model = Contact
        fields = ["first_name", "last_name", "organization", "title", "roles", "email", "phone", "mobile", "street",
                  "city", "state", "postal_code", "is_client", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.active()
