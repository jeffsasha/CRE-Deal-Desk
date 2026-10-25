from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy, gettext as _

from core.audit import audit, diff, snapshot
from core.choices import PROPERTY_TYPES
from core.listing import Column, Filter, Listing
from core.permissions import has_perm, require, require_edit_on_post, require_perm
from deals.models import Activity, Issue

from .forms import AskingPriceForm, ChargeForm, FactForm, ParcelForm, PropertyForm, RentRollForm, SpaceForm
from .models import AskingPrice, OperatingCharge, Parcel, Property, PropertyFact, RentRollEntry, Space

TRACKED = ["name", "street", "suite", "city", "property_type", "building_area_sf", "land_area_sf", "ownership_entity", "owner"]


@require_perm("view")
def property_list(request):
    qs = Property.objects.active().select_related("owner")
    listing = Listing(
        request, qs, area="properties",
        columns=[
            Column("name", gettext_lazy("Property"), lambda p: p.name, sort="name"),
            Column("address", gettext_lazy("Address"), lambda p: p.address, sort="street"),
            Column("type", gettext_lazy("Type"), lambda p: p.get_property_type_display(), sort="property_type"),
            Column("county", gettext_lazy("County"), lambda p: p.county or "—", sort="county", default=False),
            Column("building", gettext_lazy("Building SF"), lambda p: f"{p.building_area_sf:,.0f}" if p.building_area_sf else "—", sort="building_area_sf", cls="num"),
            Column("land", gettext_lazy("Land SF"), lambda p: f"{p.land_area_sf:,.0f}" if p.land_area_sf else "—", sort="land_area_sf", cls="num", default=False),
            Column("owner", gettext_lazy("Owner"), lambda p: p.ownership_entity or p.owner or "—", default=False),
            Column("deals", gettext_lazy("Deals"), lambda p: p.deal_links.count(), cls="num"),
            Column("updated", gettext_lazy("Updated"), lambda p: timezone.localtime(p.updated_at).strftime("%b %d, %Y"), sort="updated_at"),
        ],
        search_fields=["name", "street", "city", "county", "parcels__parcel_id", "ownership_entity", "notes"],
        filters=[
            Filter("type", gettext_lazy("Type"), PROPERTY_TYPES, lambda qs, v: qs.filter(property_type=v)),
            Filter("city", gettext_lazy("City"), [(c, c) for c in Property.objects.values_list("city", flat=True).distinct().order_by("city")],
                   lambda qs, v: qs.filter(city=v)),
        ],
        default_sort="name",
    )
    if request.GET.get("export") == "csv":
        return listing.export_csv("properties")
    actions = [("New property", reverse("property_create"))] if has_perm(request.user, "edit") else []
    return render(request, "core/list_page.html", {"listing": listing, "title": gettext_lazy("Properties"), "actions": actions,
                                                   "subtitle": gettext_lazy("Every property evaluated, marketed, negotiated, leased, purchased, sold or closed. History is kept when deals end.")})


@require_edit_on_post
def property_form(request, pk=None):
    prop = get_object_or_404(Property, pk=pk) if pk else None
    if prop is None:
        require(request.user, "edit")
    before = snapshot(prop, TRACKED) if prop else {}
    form = PropertyForm(request.POST or None, instance=prop)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        audit(request.user, "property.updated" if prop else "property.created", obj, diff(obj, before, TRACKED) if prop else None)
        messages.success(request, gettext_lazy("Property saved."))
        return redirect(obj)
    return render(request, "form.html", {"form": form, "title": _("Edit %(object)s") % {"object": prop} if prop else gettext_lazy("New property"),
                                         "back_url": prop.get_absolute_url() if prop else reverse("property_list")})


@require_perm("view")
def property_detail(request, pk):
    prop = get_object_or_404(Property, pk=pk)
    tab = request.GET.get("tab", "overview")
    links = prop.deal_links.select_related("deal__stage", "space").order_by("-deal__created_at")
    facts = prop.facts.select_related("verified_by", "space")
    ctx = {
        "p": prop, "tab": tab, "deal_links": links, "facts": facts,
        "fact_groups": _group(facts),
        "parcels": prop.parcels.all(), "spaces": prop.spaces.all(), "rent_roll": prop.rent_roll.select_related("space"),
        "asking": prop.asking_history.select_related("space"), "charges": prop.charges.select_related("space"),
        "issues": Issue.objects.filter(property=prop) | Issue.objects.filter(deal__deal_properties__property=prop),
        "activities": Activity.objects.filter(property=prop) | Activity.objects.filter(deal__deal_properties__property=prop, kind__in=["showing", "decision", "negotiation", "note"]),
        "unverified_count": facts.exclude(verification="verified").count(),
    }
    ctx["issues"] = ctx["issues"].distinct().select_related("deal")
    ctx["activities"] = ctx["activities"].distinct().select_related("deal")[:100]
    return render(request, "properties/detail.html", ctx)


def _group(facts):
    groups = {}
    for f in facts:
        groups.setdefault(f.get_category_display(), []).append(f)
    return groups


SUBFORMS = {
    "fact": (PropertyFact, FactForm, "facts", "Fact"),
    "parcel": (Parcel, ParcelForm, "parcels", "Parcel"),
    "space": (Space, SpaceForm, "spaces", "Space / suite"),
    "rentroll": (RentRollEntry, RentRollForm, "rent", "Rent roll entry"),
    "asking": (AskingPrice, AskingPriceForm, "pricing", "Asking price / rent"),
    "charge": (OperatingCharge, ChargeForm, "pricing", "Charge"),
}
NEEDS_PROPERTY_KW = {"fact", "rentroll", "asking", "charge"}


@require_perm("edit")
def property_subrecord(request, pk, kind, item=None):
    prop = get_object_or_404(Property, pk=pk)
    model, form_cls, tab, label = SUBFORMS[kind]
    instance = get_object_or_404(model, pk=item, property=prop) if item else None
    kwargs = {"property": prop} if kind in NEEDS_PROPERTY_KW else {}
    form = form_cls(request.POST or None, instance=instance, **kwargs)
    if request.method == "POST":
        if request.POST.get("delete") and instance:
            audit(request.user, f"property.{kind}_deleted", prop, {label: str(instance)})
            instance.delete()
            return redirect(f"{prop.get_absolute_url()}?tab={tab}")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.property = prop
            if kind == "fact" and obj.verification == "verified":
                obj.verified_by = obj.verified_by or request.user
                obj.verified_on = obj.verified_on or timezone.localdate()
            obj.save()
            audit(request.user, f"property.{kind}_saved", prop, {label: str(obj)})
            return redirect(f"{prop.get_absolute_url()}?tab={tab}")
    return render(request, "properties/subform.html", {"form": form, "p": prop, "label": label, "instance": instance,
                                                       "back_url": f"{prop.get_absolute_url()}?tab={tab}"})


@require_perm("edit")
def property_archive(request, pk):
    prop = get_object_or_404(Property, pk=pk)
    if request.method == "POST":
        prop.archived_at = timezone.now()
        prop.archived_by = request.user
        prop.save()
        audit(request.user, "property.archived", prop, note=request.POST.get("reason", ""))
        messages.success(request, _("%(property)s archived. Its deals and history are unchanged and it can be restored from Settings.") % {"property": prop})
        return redirect("property_list")
    return render(request, "confirm.html", {"title": _("Archive %(object)s") % {"object": prop}, "back_url": prop.get_absolute_url(),
                                            "message": gettext_lazy("Archiving hides the property from active lists. Deal history, documents and facts are preserved and the property can be restored."),
                                            "reason_required": True, "submit_label": gettext_lazy("Archive")})


def property_link(p):
    return format_html('<a href="{}">{}</a>', p.get_absolute_url(), p.name)
