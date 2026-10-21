from django.conf import settings
from django.db import models
from django.urls import reverse

from core.choices import PROPERTY_TYPES, RATE_UNITS, VERIFICATION_CHOICES
from core.models import Archivable, Imported, TimeStamped


class Property(TimeStamped, Archivable, Imported):
    """The enduring real estate asset. Deals come and go; the property and its
    history remain."""

    name = models.CharField(max_length=255)
    street = models.CharField("Street address", max_length=255)
    suite = models.CharField(max_length=60, blank=True)
    city = models.CharField(max_length=120, default="Houston")
    state = models.CharField(max_length=2, default="TX")
    postal_code = models.CharField("ZIP", max_length=10, blank=True)
    county = models.CharField(max_length=120, blank=True)
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPES, default="other")
    legal_description = models.TextField(blank=True)
    building_area_sf = models.DecimalField("Building area (SF)", max_digits=12, decimal_places=2, null=True, blank=True)
    land_area_sf = models.DecimalField("Land area (SF)", max_digits=14, decimal_places=2, null=True, blank=True)
    land_area_acres = models.DecimalField("Land area (acres)", max_digits=10, decimal_places=4, null=True, blank=True)
    available_area_sf = models.DecimalField("Available area (SF)", max_digits=12, decimal_places=2, null=True, blank=True)
    units = models.PositiveIntegerField(null=True, blank=True)
    owner = models.ForeignKey(
        "crm.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_properties"
    )
    ownership_entity = models.CharField(max_length=255, blank=True, help_text="Vesting entity as shown on the deed.")
    occupancy_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    size_source = models.CharField(
        max_length=255, blank=True, help_text="Where the area figures came from (appraisal district, survey, flyer…)."
    )
    size_verified_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "properties"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("property_detail", args=[self.pk])

    @property
    def address(self):
        line = self.street + (f", Suite {self.suite}" if self.suite else "")
        return f"{line}, {self.city}, {self.state} {self.postal_code}".strip()


class Parcel(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="parcels")
    parcel_id = models.CharField("Parcel / account number", max_length=80)
    county = models.CharField(max_length=120, blank=True)
    legal_description = models.TextField(blank=True)
    land_area_sf = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["parcel_id"]

    def __str__(self):
        return self.parcel_id


class Space(models.Model):
    STATUS = [("vacant", "Vacant"), ("leased", "Leased"), ("owner_occupied", "Owner-occupied"), ("unknown", "Unknown")]
    CONDITION = [
        ("unknown", "Unknown"),
        ("shell", "Shell"),
        ("second_generation", "Second-generation"),
        ("built_out", "Built out"),
    ]

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="spaces")
    suite = models.CharField(max_length=60)
    area_sf = models.DecimalField("Area (SF)", max_digits=12, decimal_places=2, null=True, blank=True)
    floor = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="unknown")
    condition = models.CharField(max_length=20, choices=CONDITION, default="unknown")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["suite"]

    def __str__(self):
        return f"{self.property.name} — Suite {self.suite}"


class RentRollEntry(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rent_roll")
    space = models.ForeignKey(Space, null=True, blank=True, on_delete=models.SET_NULL)
    tenant_name = models.CharField(max_length=255)
    lease_start = models.DateField(null=True, blank=True)
    lease_end = models.DateField("Lease expiration", null=True, blank=True)
    rent_amount = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    rent_unit = models.CharField(max_length=20, choices=RATE_UNITS, default="usd_month")
    as_of = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["lease_end", "tenant_name"]


class AskingPrice(models.Model):
    """Historical asking price or asking rent. Every change is a new row."""

    KIND = [("asking_price", "Asking price"), ("asking_rent", "Asking rent")]

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="asking_history")
    space = models.ForeignKey(Space, null=True, blank=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=20, choices=KIND)
    amount = models.DecimalField(max_digits=16, decimal_places=4)
    unit = models.CharField(max_length=20, choices=RATE_UNITS, default="usd_total")
    effective_date = models.DateField()
    source = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-effective_date", "-id"]


class OperatingCharge(models.Model):
    TYPES = [
        ("base_rent", "Base rent"),
        ("nnn", "NNN (combined)"),
        ("cam", "CAM"),
        ("taxes", "Taxes"),
        ("insurance", "Insurance"),
        ("utilities", "Utilities"),
        ("other", "Other"),
    ]

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="charges")
    space = models.ForeignKey(Space, null=True, blank=True, on_delete=models.SET_NULL)
    charge_type = models.CharField(max_length=20, choices=TYPES)
    amount = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=20, choices=RATE_UNITS)
    as_of = models.DateField(null=True, blank=True)
    is_estimate = models.BooleanField(default=True)
    source = models.CharField(max_length=255, blank=True)
    verification = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default="unverified")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["charge_type"]


FACT_CATEGORIES = [
    ("physical", "Physical"),
    ("industrial", "Industrial"),
    ("restaurant_retail", "Restaurant & retail"),
    ("zoning_use", "Zoning, use & restrictions"),
    ("flood", "Flood"),
    ("utilities", "Utilities & access"),
    ("other", "Other"),
]

# Suggested facts. Users may record any other key as well.
FACT_CATALOG = {
    "physical": [
        ("year_built", "Year built"),
        ("construction", "Construction type"),
        ("roof", "Roof type / age"),
        ("parking_spaces", "Parking spaces"),
    ],
    "industrial": [
        ("clear_height", "Clear height"),
        ("loading_doors", "Loading doors (total)"),
        ("dock_high_doors", "Dock-high doors"),
        ("grade_level_doors", "Grade-level doors"),
        ("power", "Power"),
        ("sprinklers", "Sprinklers"),
        ("yard_space", "Yard space"),
        ("truck_access", "Truck access / turning radius"),
    ],
    "restaurant_retail": [
        ("space_condition", "Shell vs. second-generation"),
        ("hood", "Hood"),
        ("grease_trap", "Grease trap / interceptor"),
        ("hvac", "HVAC"),
        ("utilities", "Utilities (gas, water, electric)"),
        ("parking", "Parking"),
        ("signage", "Signage"),
        ("delivery_condition", "Delivery condition"),
        ("ti_needs", "Tenant improvement needs"),
    ],
    "zoning_use": [
        ("zoning", "Zoning (Houston has no conventional zoning; record the applicable regime)"),
        ("permitted_use", "Permitted use"),
        ("deed_restrictions", "Deed restrictions"),
        ("certificate_of_occupancy", "Certificate of occupancy"),
    ],
    "flood": [
        ("flood_zone", "FEMA flood zone"),
        ("flood_map_panel", "FIRM panel"),
        ("flood_map_date", "Map effective date"),
        ("flood_history", "Known flood history"),
    ],
    "utilities": [
        ("water_sewer", "Water / sewer provider"),
        ("access", "Access / curb cuts"),
    ],
}


class PropertyFact(models.Model):
    """An important fact with its source and verification status. Marketing
    statements are recorded as such and never displayed as confirmed."""

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="facts")
    space = models.ForeignKey(Space, null=True, blank=True, on_delete=models.SET_NULL)
    category = models.CharField(max_length=30, choices=FACT_CATEGORIES)
    key = models.CharField(max_length=60)
    label = models.CharField(max_length=160)
    value = models.TextField()
    unit = models.CharField(max_length=40, blank=True)
    source = models.CharField(max_length=255, blank=True)
    source_document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL)
    verification = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default="unverified")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verified_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "label"]

    def __str__(self):
        return f"{self.label}: {self.value}"
