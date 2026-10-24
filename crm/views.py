from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core.audit import audit
from core.listing import Column, Filter, Listing
from core.permissions import has_perm, require, require_edit_on_post, require_perm
from deals.models import DealParty

from .forms import ContactForm, OrganizationForm
from .models import Contact, Organization

RESTRICTED = gettext_lazy("Restricted")


def masked(user, contact_or_org, value):
    """Client contact details are visible only to roles with client.details."""
    is_client = getattr(contact_or_org, "is_confidential_client", None)
    if is_client is None:
        is_client = contact_or_org.is_client
    if is_client and not has_perm(user, "client.details"):
        return RESTRICTED
    return value


@require_perm("view")
def contact_list(request):
    u = request.user
    tab = request.GET.get("tab", "people")
    if tab == "companies":
        listing = Listing(
            request, Organization.objects.active(), area="companies",
            columns=[
                Column("name", gettext_lazy("Company"), lambda o: str(o), sort="name"),
                Column("type", gettext_lazy("Type"), lambda o: o.get_org_type_display(), sort="org_type"),
                Column("client", gettext_lazy("Client"), lambda o: _("Client") if o.is_client else ""),
                Column("phone", gettext_lazy("Phone"), lambda o: masked(u, o, o.phone)),
                Column("email", gettext_lazy("Email"), lambda o: masked(u, o, o.email), default=False),
                Column("city", gettext_lazy("City"), lambda o: o.city, sort="city", default=False),
                Column("contacts", gettext_lazy("People"), lambda o: o.contacts.count(), cls="num"),
            ],
            search_fields=["name", "branch_name", "tags", "city"],
            filters=[Filter("type", gettext_lazy("Type"), Organization.TYPE_CHOICES, lambda qs, v: qs.filter(org_type=v)),
                     Filter("client", gettext_lazy("Clients"), [("1", gettext_lazy("Clients only"))], lambda qs, v: qs.filter(is_client=True))],
            default_sort="name",
        )
    else:
        listing = Listing(
            request, Contact.objects.active().select_related("organization"), area="people",
            columns=[
                Column("name", gettext_lazy("Name"), lambda c: c.full_name, sort="last_name"),
                Column("org", gettext_lazy("Company"), lambda c: c.organization or "—", sort="organization__name"),
                Column("title", gettext_lazy("Title / roles"), lambda c: ", ".join(x for x in [c.title, c.roles] if x)),
                Column("email", gettext_lazy("Email"), lambda c: masked(u, c, c.email)),
                Column("phone", gettext_lazy("Phone"), lambda c: masked(u, c, c.phone or c.mobile)),
                Column("client", gettext_lazy("Client"), lambda c: _("Client") if c.is_confidential_client else "", default=False),
            ],
            search_fields=["first_name", "last_name", "email", "organization__name", "roles", "title"],
            filters=[Filter("type", gettext_lazy("Company type"), Organization.TYPE_CHOICES, lambda qs, v: qs.filter(organization__org_type=v)),
                     Filter("role", gettext_lazy("Role"), [(r, gettext_lazy(r)) for r in ["Escrow officer", "Surveyor", "Attorney", "Lender", "Inspector", "Title"]],
                            lambda qs, v: qs.filter(roles__icontains=v))],
            default_sort="last_name",
        )
    if request.GET.get("export") == "csv":
        require(request.user, "client.details")
        return listing.export_csv(tab)
    return render(request, "crm/list.html", {"listing": listing, "tab": tab})


@require_perm("view")
def contact_detail(request, pk):
    c = get_object_or_404(Contact.objects.select_related("organization"), pk=pk)
    show = has_perm(request.user, "client.details") or not c.is_confidential_client
    parties = DealParty.objects.filter(contact=c).select_related("deal__stage")
    return render(request, "crm/contact.html", {"c": c, "show": show, "parties": parties})


@require_perm("view")
def organization_detail(request, pk):
    o = get_object_or_404(Organization, pk=pk)
    show = has_perm(request.user, "client.details") or not o.is_client
    parties = DealParty.objects.filter(organization=o).select_related("deal__stage")
    return render(request, "crm/organization.html", {
        "o": o, "show": show, "parties": parties, "contacts": o.contacts.active(),
        "client_deals": o.client_deals.select_related("stage"), "owned": o.owned_properties.all(),
    })


@require_edit_on_post
def contact_form(request, pk=None):
    require(request.user, "edit")
    obj = get_object_or_404(Contact, pk=pk) if pk else None
    form = ContactForm(request.POST or None, instance=obj, initial={"organization": request.GET.get("organization")})
    if request.method == "POST" and form.is_valid():
        c = form.save()
        audit(request.user, "contact.saved", c)
        return redirect(c)
    return render(request, "form.html", {"form": form, "title": gettext_lazy("Edit contact") if obj else gettext_lazy("New contact"),
                                         "back_url": obj.get_absolute_url() if obj else reverse("contact_list")})


@require_edit_on_post
def organization_form(request, pk=None):
    require(request.user, "edit")
    obj = get_object_or_404(Organization, pk=pk) if pk else None
    form = OrganizationForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        o = form.save()
        audit(request.user, "organization.saved", o)
        return redirect(o)
    return render(request, "form.html", {"form": form, "title": gettext_lazy("Edit company") if obj else gettext_lazy("New company"),
                                         "back_url": obj.get_absolute_url() if obj else reverse("contact_list") + "?tab=companies"})


@require_edit_on_post
def archive_party(request, kind, pk):
    require(request.user, "edit")
    model = Contact if kind == "contact" else Organization
    obj = get_object_or_404(model, pk=pk)
    if request.method == "POST":
        obj.archived_at = timezone.now()
        obj.archived_by = request.user
        obj.save()
        audit(request.user, f"{kind}.archived", obj, note=request.POST.get("reason", ""))
        messages.success(request, _("%(object)s archived; restore from Settings.") % {"object": obj})
        return redirect("contact_list")
    return render(request, "confirm.html", {"title": _("Archive %(object)s") % {"object": obj}, "back_url": obj.get_absolute_url(),
                                            "message": gettext_lazy("Archived contacts stay linked to past deals and can be restored."),
                                            "reason_required": True, "submit_label": gettext_lazy("Archive")})
