"""Historical import: upload -> map fields -> validate & preview -> commit -> (revert).

Principles:
- Unknown stays unknown: a blank commission is recorded as unknown, never zero.
- Nothing is classified as a completed transaction unless the row says it closed and
  gives an actual closing date in the past. LOIs, counteroffers and proposals are not
  closings.
- Every created record carries the batch as its source reference, and reverting a
  batch deletes only records it created that have not since been used or edited.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta

from django.apps import apps
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.audit import audit
from core.money import MoneyParseError, parse_cents
from crm.models import Contact, Organization
from deals.models import Activity, Deal, DealEvent, DealParty, DealProperty, Representation, Stage
from deals.services import parse_date
from properties.models import Property

from .models import ImportBatch, ImportRow

# (key, label, required, aliases)
FIELDS = {
    "deals": [
        ("deal_name", "Deal name", True, ["deal", "name", "transaction", "deal name"]),
        ("transaction_type", "Transaction type", True, ["type", "deal type", "transaction type"]),
        ("status", "Status / stage", True, ["stage", "status", "deal status"]),
        ("property_name", "Property name", False, ["property", "property name", "building"]),
        ("street", "Street address", False, ["address", "street", "street address", "property address"]),
        ("suite", "Suite", False, ["suite", "unit"]),
        ("city", "City", False, ["city"]),
        ("state", "State", False, ["state", "st"]),
        ("postal_code", "ZIP", False, ["zip", "zip code", "postal code"]),
        ("county", "County", False, ["county"]),
        ("property_type", "Property type", False, ["property type", "asset type", "use"]),
        ("client", "Client", False, ["client", "customer", "client name"]),
        ("represented_side", "Represented side(s)", False, ["side", "represented", "representation", "represented side"]),
        ("broker", "Broker", False, ["broker", "agent", "listing agent"]),
        ("contract_price", "Executed contract price", False, ["contract price", "executed price"]),
        ("closing_price", "Actual closing price / consideration", False, ["closing price", "sale price", "sold price", "price", "consideration"]),
        ("actual_closing_date", "Actual closing date", False, ["closing date", "closed date", "close date", "date closed", "actual closing date"]),
        ("title_company", "Title company", False, ["title company", "title", "escrow"]),
        ("lease_area_sf", "Leased area (SF)", False, ["sf", "square feet", "leased sf", "rsf"]),
        ("lease_total_consideration", "Total lease consideration", False, ["lease value", "lease consideration", "aggregate rent"]),
        ("skw_commission", "Commission payable to SKW", False, ["commission", "skw commission", "gross commission", "fee"]),
        ("commission_received", "Commission cash received by SKW", False, ["commission received", "received", "paid"]),
        ("commission_received_date", "Commission receipt date", False, ["received date", "paid date", "commission paid date"]),
        ("designated_broker_received", "Amount received by designated broker", False, ["serene received", "broker received", "serene"]),
        ("designated_broker_received_date", "Designated broker payment date", False, ["serene paid date", "broker paid date"]),
        ("notes", "Notes", False, ["notes", "comments", "remarks"]),
        ("source_reference", "Source reference", False, ["source", "reference", "file", "id"]),
    ],
    "properties": [
        ("name", "Property name", True, ["name", "property", "property name"]),
        ("street", "Street address", True, ["address", "street", "street address"]),
        ("suite", "Suite", False, ["suite", "unit"]),
        ("city", "City", False, ["city"]),
        ("state", "State", False, ["state"]),
        ("postal_code", "ZIP", False, ["zip", "zip code", "postal code"]),
        ("county", "County", False, ["county"]),
        ("property_type", "Property type", False, ["type", "property type"]),
        ("building_area_sf", "Building area (SF)", False, ["building sf", "building area", "sf", "gla"]),
        ("land_area_sf", "Land area (SF)", False, ["land sf", "land area"]),
        ("notes", "Notes", False, ["notes"]),
        ("source_reference", "Source reference", False, ["source", "reference"]),
    ],
    "contacts": [
        ("first_name", "First name", False, ["first", "first name"]),
        ("last_name", "Last name", False, ["last", "last name"]),
        ("full_name", "Full name", False, ["name", "full name", "contact"]),
        ("company", "Company", False, ["company", "organization", "firm"]),
        ("company_type", "Company type", False, ["company type", "org type"]),
        ("title", "Title", False, ["title", "position"]),
        ("roles", "Roles", False, ["role", "roles"]),
        ("email", "Email", False, ["email", "e-mail"]),
        ("phone", "Phone", False, ["phone", "telephone", "mobile"]),
        ("notes", "Notes", False, ["notes"]),
        ("source_reference", "Source reference", False, ["source", "reference"]),
    ],
}

TYPE_MAP = [
    (r"business|asset", "business_asset"),
    (r"land.*(sale|sold|dispos)", "land_sale"),
    (r"land", "land_purchase"),
    (r"renew", "lease_renewal"),
    (r"expan", "lease_expansion"),
    (r"assign", "lease_assignment"),
    (r"lease", "lease"),
    (r"purchase|acqui|buy", "purchase"),
    (r"sale|sold|dispos|listing", "sale"),
]
STATUS_MAP = [
    (r"\b(loi|letter of intent)\b", "loi"),
    (r"counter|propos|negotiat|offer", "negotiating"),
    (r"terminat|cancel", "terminated"),
    (r"\b(lost|dead|declined)\b", "lost"),
    (r"hold", "on_hold"),
    (r"under contract|pending|escrow|contract", "under_contract"),
    (r"diligence", "due_diligence"),
    (r"preparing|clear to close", "preparing_to_close"),
    (r"\b(closed|sold|leased|complete|completed|funded|executed)\b", "closed"),
    (r"tour", "touring"),
    (r"evaluat", "evaluating"),
    (r"lead|prospect", "lead"),
]
NOT_CLOSED_WORDS = re.compile(r"\b(loi|letter of intent|counter\w*|propos\w*|negotiat\w*|pending|expected|anticipated)\b", re.I)
PROPERTY_TYPES = {"retail", "restaurant", "office", "industrial", "warehouse", "land", "multifamily", "mixed_use", "other"}


def _norm(text):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


ADDRESS_ABBR = {"street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "boulevard": "blvd", "parkway": "pkwy",
                "highway": "hwy", "freeway": "fwy", "lane": "ln", "court": "ct", "suite": "ste", "north": "n",
                "south": "s", "east": "e", "west": "w"}


def norm_address(street, city=""):
    words = [ADDRESS_ABBR.get(w, w) for w in _norm(f"{street} {city}").split()]
    return " ".join(words)


def read_table(fileobj, filename):
    name = filename.lower()
    if name.endswith(".xlsx"):
        import openpyxl

        wb = openpyxl.load_workbook(fileobj, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return [], []
        headers = [str(h).strip() if h is not None else f"Column {i + 1}" for i, h in enumerate(rows[0])]
        data = []
        for r in rows[1:]:
            if r is None or all(v in (None, "") for v in r):
                continue
            rec = {}
            for h, v in zip(headers, r):
                if isinstance(v, datetime):
                    v = v.date().isoformat()
                elif isinstance(v, date):
                    v = v.isoformat()
                rec[h] = "" if v is None else str(v)
            data.append(rec)
        return headers, data
    raw = fileobj.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    data = []
    for r in reader:
        rec = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        if any(rec.values()):
            data.append(rec)
    return headers, data


def auto_map(kind, headers):
    mapping = {}
    norm_headers = {_norm(h): h for h in headers}
    for key, label, _req, aliases in FIELDS[kind]:
        for candidate in [key.replace("_", " "), _norm(label)] + aliases:
            h = norm_headers.get(_norm(candidate))
            if h and h not in mapping.values():
                mapping[key] = h
                break
    return mapping


@transaction.atomic
def create_batch(uploaded, kind, actor):
    headers, data = read_table(uploaded, uploaded.name)
    uploaded.seek(0)
    batch = ImportBatch(kind=kind, original_filename=uploaded.name, headers=headers, created_by=actor)
    batch.file.save(uploaded.name, uploaded, save=False)
    batch.mapping = auto_map(kind, headers)
    batch.summary = {"rows": len(data)}
    batch.save()
    for i, rec in enumerate(data, start=2):  # row 1 is the header
        ImportRow.objects.create(batch=batch, row_number=i, raw=rec)
    audit(actor, "import.uploaded", batch, {"rows": len(data), "kind": kind})
    return batch


def _map(batch, raw):
    return {key: (raw.get(col, "") or "").strip() for key, col in batch.mapping.items() if col}


def _money(row, key, errors, warnings, label):
    value = row.get(key, "")
    try:
        cents = parse_cents(value)
    except MoneyParseError:
        errors.append(f"{label}: '{value}' is not a valid amount.")
        return None
    if cents == 0 and value.strip():
        warnings.append(f"{label} is an explicit zero (kept as $0.00, not unknown).")
    return cents


def _date_val(row, key, errors, label):
    value = row.get(key, "")
    if not value:
        return None
    try:
        return parse_date(value).isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(value).date().isoformat()
        except ValueError:
            errors.append(f"{label}: '{value}' is not a recognizable date.")
            return None


def _first_match(text, table):
    for pattern, value in table:
        if re.search(pattern, text, re.I):
            return value
    return None


def validate_deal_row(row, today):
    errors, warnings, out = [], [], {}
    out["deal_name"] = row.get("deal_name", "")
    if not out["deal_name"]:
        errors.append("Deal name is required.")
    ttype = _first_match(row.get("transaction_type", ""), TYPE_MAP)
    if not ttype:
        errors.append(f"Transaction type '{row.get('transaction_type', '')}' is not recognized.")
    out["transaction_type"] = ttype
    status_raw = row.get("status", "")
    stage = _first_match(status_raw, STATUS_MAP)
    if not status_raw:
        errors.append("Status is required; a deal is never assumed to be closed.")
    elif not stage:
        errors.append(f"Status '{status_raw}' is not recognized.")
    if re.search(r"\b(closed|sold|leased|completed?|funded)\b", status_raw, re.I) and NOT_CLOSED_WORDS.search(status_raw):
        errors.append(f"Status '{status_raw}' is contradictory: it mentions a closing and a proposal or negotiation. "
                      "Correct the status; it is not treated as a completed transaction.")
    out["stage"] = stage
    closing = _date_val(row, "actual_closing_date", errors, "Actual closing date")
    if stage == "closed":
        if NOT_CLOSED_WORDS.search(status_raw):
            errors.append(f"Status '{status_raw}' describes a proposal or negotiation, not a completed transaction.")
        if not closing:
            errors.append("A closed deal requires an actual closing date. Import it with a non-closed status otherwise.")
        elif date.fromisoformat(closing) > today:
            errors.append("The actual closing date is in the future; a proposed closing is not a completed transaction.")
    elif closing:
        warnings.append("Closing date given but status is not closed; it is stored as the internal target date only.")
    out["actual_closing_date"] = closing
    out["closing_price"] = _money(row, "closing_price", errors, warnings, "Closing price")
    out["contract_price"] = _money(row, "contract_price", errors, warnings, "Contract price")
    out["lease_total_consideration"] = _money(row, "lease_total_consideration", errors, warnings, "Lease consideration")
    if stage == "closed" and ttype and ttype not in {"lease", "lease_renewal", "lease_expansion", "lease_assignment"} \
            and out["closing_price"] is None:
        warnings.append("Closing price is blank; the consideration will remain unknown (not $0).")
    out["skw_commission"] = _money(row, "skw_commission", errors, warnings, "Commission payable to SKW")
    out["commission_received"] = _money(row, "commission_received", errors, warnings, "Commission received")
    out["commission_received_date"] = _date_val(row, "commission_received_date", errors, "Commission receipt date")
    out["designated_broker_received"] = _money(row, "designated_broker_received", errors, warnings,
                                               "Designated broker receipt")
    out["designated_broker_received_date"] = _date_val(row, "designated_broker_received_date", errors,
                                                       "Designated broker payment date")
    if out["skw_commission"] is None:
        warnings.append("Commission is blank and will remain unknown (not $0).")
    if out["commission_received"] and not out["commission_received_date"]:
        errors.append("A commission receipt needs its receipt date.")
    if out["designated_broker_received"] and not out["designated_broker_received_date"]:
        errors.append("The designated broker's receipt needs its payment date.")
    if (out["commission_received"] or out["designated_broker_received"]) and stage != "closed":
        warnings.append("Commission cash recorded on a deal that is not closed.")
    sides = []
    for part in re.split(r"[;/,&]| and ", row.get("represented_side", "").lower()):
        part = part.strip()
        if not part:
            continue
        if part in {"dual", "both"}:
            sides += ["buyer", "seller"] if ttype in {"purchase", "sale", "land_purchase", "land_sale", "business_asset"} \
                else ["landlord", "tenant"]
        elif part in {"buyer", "seller", "landlord", "tenant"}:
            sides.append(part)
        else:
            errors.append(f"Represented side '{part}' is not recognized.")
    out["sides"] = sorted(set(sides))
    ptype = _norm(row.get("property_type", "")).replace(" ", "_")
    out["property_type"] = ptype if ptype in PROPERTY_TYPES else ("other" if ptype else "")
    if ptype and ptype not in PROPERTY_TYPES:
        warnings.append(f"Property type '{row.get('property_type')}' not recognized; recorded as Other.")
    for k in ["property_name", "street", "suite", "city", "state", "postal_code", "county", "client", "broker",
              "title_company", "notes", "source_reference"]:
        out[k] = row.get(k, "")
    try:
        out["lease_area_sf"] = str(float(row["lease_area_sf"].replace(",", ""))) if row.get("lease_area_sf") else None
    except ValueError:
        errors.append("Leased area is not a number.")
    if not (out["property_name"] or out["street"]):
        warnings.append("No property given; the deal will be created without a property link.")
    return out, errors, warnings


def validate_property_row(row):
    errors, warnings = [], []
    out = {k: row.get(k, "") for k, *_ in FIELDS["properties"]}
    if not out["name"]:
        errors.append("Property name is required.")
    if not out["street"]:
        errors.append("Street address is required.")
    ptype = _norm(out["property_type"]).replace(" ", "_")
    out["property_type"] = ptype if ptype in PROPERTY_TYPES else "other"
    for k in ["building_area_sf", "land_area_sf"]:
        if out[k]:
            try:
                out[k] = str(float(out[k].replace(",", "")))
            except ValueError:
                errors.append(f"{k.replace('_', ' ')} is not a number.")
                out[k] = None
        else:
            out[k] = None
    return out, errors, warnings


def validate_contact_row(row):
    errors, warnings = [], []
    out = {k: row.get(k, "") for k, *_ in FIELDS["contacts"]}
    if out["full_name"] and not (out["first_name"] or out["last_name"]):
        parts = out["full_name"].split()
        out["first_name"], out["last_name"] = " ".join(parts[:-1]), parts[-1] if parts else ""
    if not (out["first_name"] or out["last_name"] or out["company"]):
        errors.append("A name or company is required.")
    return out, errors, warnings


def _find_property(name, street, city):
    if street:
        key = norm_address(street, city)
        for p in Property.objects.filter(archived_at__isnull=True).only("id", "street", "city", "name"):
            if norm_address(p.street, p.city) == key or (not city and norm_address(p.street) == norm_address(street)):
                return p
    if name:
        return Property.objects.filter(name__iexact=name, archived_at__isnull=True).first()
    return None


def _find_org(name, org_type=None):
    if not name:
        return None
    qs = Organization.objects.filter(archived_at__isnull=True)
    for org in qs.only("id", "name"):
        if _norm(org.name) == _norm(name):
            return org
    return None


@transaction.atomic
def validate_batch(batch, mapping=None):
    if mapping is not None:
        batch.mapping = {k: v for k, v in mapping.items() if v}
    missing = [label for key, label, req, _ in FIELDS[batch.kind] if req and key not in batch.mapping]
    today = timezone.localdate()
    seen = {}
    counts = {"valid": 0, "invalid": 0, "duplicates": 0}
    for row in batch.rows.all():
        mapped = _map(batch, row.raw)
        if batch.kind == "deals":
            out, errors, warnings = validate_deal_row(mapped, today)
        elif batch.kind == "properties":
            out, errors, warnings = validate_property_row(mapped)
        else:
            out, errors, warnings = validate_contact_row(mapped)
        if missing:
            errors = [f"Required field not mapped: {', '.join(missing)}."] + errors
        matches, dup = {}, ""
        action = "create"
        if batch.kind == "deals" and not errors:
            prop = _find_property(out["property_name"], out["street"], out["city"])
            if prop:
                matches["property"] = [prop.pk, str(prop)]
            for label, name in (("client", out["client"]), ("title_company", out["title_company"])):
                org = _find_org(name)
                if org:
                    matches[label] = [org.pk, str(org)]
            sig = (_norm(out["deal_name"]), out["actual_closing_date"], norm_address(out["street"], out["city"]))
            if sig in seen:
                errors.append(f"Duplicate of row {seen[sig]} in this file.")
            seen.setdefault(sig, row.row_number)
            existing = Deal.objects.filter(archived_at__isnull=True)
            cand = [d for d in existing.filter(name__iexact=out["deal_name"])]
            if prop:
                cand += list(existing.filter(deal_properties__property=prop, actual_closing_date=out["actual_closing_date"])
                             ) if out["actual_closing_date"] else []
            for d in cand:
                if (out["actual_closing_date"] and str(d.actual_closing_date) == out["actual_closing_date"]) or \
                        _norm(d.name) == _norm(out["deal_name"]):
                    dup = f"Possible duplicate of existing deal {d.internal_id} '{d.name}'."
                    matches["duplicate_deal"] = [d.pk, str(d)]
                    action = "skip"
                    break
        elif batch.kind == "properties" and not errors:
            prop = _find_property(out["name"], out["street"], out["city"])
            sig = norm_address(out["street"], out["city"])
            if sig in seen:
                errors.append(f"Duplicate of row {seen[sig]} in this file.")
            seen.setdefault(sig, row.row_number)
            if prop:
                dup = f"Matches existing property '{prop}'."
                matches["duplicate_property"] = [prop.pk, str(prop)]
                action = "skip"
        elif batch.kind == "contacts" and not errors:
            q = Q()
            if out["email"]:
                q |= Q(email__iexact=out["email"])
            if out["first_name"] or out["last_name"]:
                q |= Q(first_name__iexact=out["first_name"], last_name__iexact=out["last_name"])
            existing = Contact.objects.filter(q).first() if q else None
            sig = (out["email"].lower(), _norm(out["first_name"] + out["last_name"]), _norm(out["company"]))
            if sig in seen:
                errors.append(f"Duplicate of row {seen[sig]} in this file.")
            seen.setdefault(sig, row.row_number)
            if existing:
                dup = f"Matches existing contact '{existing}'."
                matches["duplicate_contact"] = [existing.pk, str(existing)]
                action = "skip"
            org = _find_org(out["company"])
            if org:
                matches["company"] = [org.pk, str(org)]
        row.mapped = out
        row.errors = errors
        row.warnings = warnings
        row.matches = matches
        row.duplicate_note = dup
        row.action = action
        row.status = "invalid" if errors else "valid"
        row.save()
        counts["invalid" if errors else "valid"] += 1
        counts["duplicates"] += bool(dup)
    batch.status = "validated"
    batch.summary = {**batch.summary, **counts}
    batch.save()
    return counts


def _org(name, org_type, batch, created, is_client=False):
    org = _find_org(name)
    if org:
        return org
    org = Organization.objects.create(name=name, org_type=org_type, is_client=is_client, import_batch=batch,
                                      source_reference=f"Import #{batch.pk}")
    created.append(["crm.Organization", org.pk])
    return org


def _broker_user(name):
    from core.models import User

    if not name:
        return None
    for u in User.objects.filter(is_active=True):
        if _norm(u.get_full_name()) == _norm(name) or u.username.lower() == name.lower():
            return u
    return None


def _commit_deal_row(batch, row, actor, created):
    from commissions.models import CommissionAgreement, CommissionAllocation, CommissionInstallment
    from commissions.services import record_entry

    m = row.mapped
    ref = m.get("source_reference") or f"{batch.original_filename} row {row.row_number}"
    prop = None
    if m["property_name"] or m["street"]:
        prop = _find_property(m["property_name"], m["street"], m["city"])
        if prop is None:
            prop = Property.objects.create(
                name=m["property_name"] or m["street"], street=m["street"] or "(address not provided)", suite=m["suite"],
                city=m["city"] or "Houston", state=(m["state"] or "TX")[:2], postal_code=m["postal_code"],
                county=m["county"], property_type=m["property_type"] or "other", import_batch=batch,
                source_reference=ref,
            )
            created.append(["properties.Property", prop.pk])
    client = _org(m["client"], "client_entity", batch, created, is_client=True) if m["client"] else None
    stage = Stage.objects.get(key=m["stage"])
    deal = Deal.objects.create(
        name=m["deal_name"], transaction_type=m["transaction_type"], stage=stage, client=client,
        description=m.get("notes", ""), import_batch=batch, source_reference=ref,
        actual_closing_date=m["actual_closing_date"] if m["stage"] == "closed" else None,
        target_closing_date=m["actual_closing_date"] if m["stage"] != "closed" else None,
        actual_closing_price_cents=m["closing_price"] if m["stage"] == "closed" else None,
        lease_total_consideration_cents=m["lease_total_consideration"],
        lease_area_sf=m.get("lease_area_sf"),
        responsible_broker=_broker_user(m["broker"]),
    )
    created.append(["deals.Deal", deal.pk])
    if prop:
        dp = DealProperty.objects.create(deal=deal, property=prop, is_primary=True)
        created.append(["deals.DealProperty", dp.pk])
    if m["contract_price"] is not None:
        from deals.models import PriceEvent

        pe = PriceEvent.objects.create(deal=deal, kind="executed_contract", amount_cents=m["contract_price"],
                                       event_date=m["actual_closing_date"] or timezone.localdate(),
                                       notes=f"Imported ({ref}); date approximate", created_by=actor)
        created.append(["deals.PriceEvent", pe.pk])
    for side in m["sides"]:
        rep = Representation.objects.create(deal=deal, side=side, is_skw=True, broker_user=_broker_user(m["broker"]),
                                            broker_name=m["broker"])
        created.append(["deals.Representation", rep.pk])
    if m["title_company"]:
        org = _org(m["title_company"], "title_company", batch, created)
        party = DealParty.objects.create(deal=deal, role="title_company", organization=org)
        created.append(["deals.DealParty", party.pk])
    if m["stage"] == "closed":
        ev = DealEvent.objects.create(deal=deal, key="closing", occurred_on=m["actual_closing_date"],
                                      evidence_note=f"Imported from {ref}", recorded_by=actor)
        created.append(["deals.DealEvent", ev.pk])
    act = Activity.objects.create(deal=deal, kind="system", summary=f"Imported from {batch.original_filename} (row {row.row_number})",
                                  body=m.get("notes", ""), created_by=actor)
    created.append(["deals.Activity", act.pk])

    if m["skw_commission"] is not None or m["commission_received"] or m["designated_broker_received"]:
        side = m["sides"][0] if m["sides"] else ("seller" if deal.transaction_type in {"sale", "land_sale"} else "buyer")
        agreement = CommissionAgreement.objects.create(
            deal=deal, title=f"Historical commission — {deal.name}", represented_side=side, basis_type="custom",
            stated_gross_cents=m["skw_commission"], import_batch=batch, source_reference=ref,
            notes="Imported historical record. The amount is the commission payable to SKW as given in the source; "
                  "the underlying agreement terms were not imported.",
        )
        created.append(["commissions.CommissionAgreement", agreement.pk])
        alloc = CommissionAllocation.objects.create(
            agreement=agreement, level="payer", recipient_type="skw", recipient_name="SKW Realty LLC",
            method="flat" if m["skw_commission"] is not None else "unknown", amount_cents=m["skw_commission"],
        )
        created.append(["commissions.CommissionAllocation", alloc.pk])
        inst = CommissionInstallment.objects.create(
            agreement=agreement, label="Historical commission", amount_cents=m["skw_commission"],
            earned_status="earned" if m["stage"] == "closed" else "not_earned",
            earned_on=m["actual_closing_date"] if m["stage"] == "closed" else None,
        )
        created.append(["commissions.CommissionInstallment", inst.pk])
        if m["commission_received"]:
            e = record_entry(agreement, actor, entry_type="receipt", amount_cents=m["commission_received"],
                             entry_date=date.fromisoformat(m["commission_received_date"]), installment=inst,
                             notes=f"Imported ({ref})", import_batch=batch)
            created.append(["commissions.LedgerEntry", e.pk])
        if m["designated_broker_received"]:
            from core.models import User

            db_user = User.objects.filter(is_designated_broker=True).first()
            db_alloc = CommissionAllocation.objects.create(
                agreement=agreement, level="internal", recipient_type="designated_broker",
                recipient_name=db_user.display_name if db_user else "Designated broker", recipient_user=db_user,
                method="unknown", notes="Allocation amount not in source; only the actual payment was imported.",
            )
            created.append(["commissions.CommissionAllocation", db_alloc.pk])
            e = record_entry(agreement, actor, entry_type="distribution", amount_cents=m["designated_broker_received"],
                             entry_date=date.fromisoformat(m["designated_broker_received_date"]), allocation=db_alloc,
                             notes=f"Imported ({ref})", import_batch=batch)
            created.append(["commissions.LedgerEntry", e.pk])
    return deal


def _commit_property_row(batch, row, created):
    m = row.mapped
    prop = Property.objects.create(
        name=m["name"], street=m["street"], suite=m["suite"], city=m["city"] or "Houston", state=(m["state"] or "TX")[:2],
        postal_code=m["postal_code"], county=m["county"], property_type=m["property_type"],
        building_area_sf=m["building_area_sf"], land_area_sf=m["land_area_sf"], notes=m["notes"],
        import_batch=batch, source_reference=m.get("source_reference") or f"{batch.original_filename} row {row.row_number}",
    )
    created.append(["properties.Property", prop.pk])


def _commit_contact_row(batch, row, created):
    m = row.mapped
    org = None
    if m["company"]:
        org = _org(m["company"], m.get("company_type") or "other", batch, created)
    if m["first_name"] or m["last_name"]:
        c = Contact.objects.create(
            first_name=m["first_name"], last_name=m["last_name"], organization=org, title=m["title"], roles=m["roles"],
            email=m["email"], phone=m["phone"], notes=m["notes"], import_batch=batch,
            source_reference=m.get("source_reference") or f"{batch.original_filename} row {row.row_number}",
        )
        created.append(["crm.Contact", c.pk])


@transaction.atomic
def commit_batch(batch, actor):
    if batch.status != "validated":
        raise ValueError("Validate the batch before committing.")
    committed = skipped = 0
    for row in batch.rows.all():
        if row.status != "valid" or row.action == "skip":
            row.status = "skipped" if row.status == "valid" else row.status
            row.save(update_fields=["status"])
            skipped += 1
            continue
        created = []
        if batch.kind == "deals":
            _commit_deal_row(batch, row, actor, created)
        elif batch.kind == "properties":
            _commit_property_row(batch, row, created)
        else:
            _commit_contact_row(batch, row, created)
        row.created_objects = created
        row.status = "committed"
        row.save(update_fields=["created_objects", "status"])
        committed += 1
    batch.status = "committed"
    batch.committed_at = timezone.now()
    batch.summary = {**batch.summary, "committed": committed, "skipped": skipped}
    batch.save()
    audit(actor, "import.committed", batch, {"committed": committed, "skipped": skipped})
    return committed, skipped


# --- Reversal --------------------------------------------------------------

def _blockers(label, obj, batch, row_objects):
    """Reasons this object must not be deleted: it was edited or used by other work."""
    reasons = []
    grace = batch.committed_at + timedelta(seconds=5) if batch.committed_at else None
    updated = getattr(obj, "updated_at", None)
    if grace and updated and updated > grace:
        reasons.append(f"{obj} was edited after the import.")
    if label == "deals.Deal":
        if obj.document_links.exists():
            reasons.append(f"{obj} has linked documents.")
        if obj.deadlines.exists() or obj.checklist_items.exists() or obj.terms.exists():
            reasons.append(f"{obj} has deadlines, checklist items or contract terms added after import.")
        if obj.activities.exclude(pk__in=row_objects.get("deals.Activity", set())).exclude(kind="system").exists():
            reasons.append(f"{obj} has activity entries added after import.")
        if obj.issues.exists():
            reasons.append(f"{obj} has issues recorded.")
        extra_agreements = obj.commission_agreements.exclude(pk__in=row_objects.get("commissions.CommissionAgreement", set()))
        if extra_agreements.exists():
            reasons.append(f"{obj} has commission agreements added after import.")
    if label == "commissions.CommissionAgreement":
        extra = obj.ledger_entries.exclude(pk__in=row_objects.get("commissions.LedgerEntry", set()))
        if extra.exists():
            reasons.append(f"Commission agreement for {obj.deal} has ledger entries added after import.")
    if label == "properties.Property":
        others = obj.deal_links.exclude(pk__in=row_objects.get("deals.DealProperty", set()))
        if others.exists():
            reasons.append(f"Property {obj} is linked to other deals.")
        if obj.document_links.exists() or obj.facts.exists() or obj.parcels.exists():
            reasons.append(f"Property {obj} has documents, facts or parcels added after import.")
    if label == "crm.Organization":
        used = (
            obj.client_deals.exclude(pk__in=row_objects.get("deals.Deal", set())).exists()
            or obj.contacts.exclude(pk__in=row_objects.get("crm.Contact", set())).exists()
            or DealParty.objects.filter(organization=obj).exclude(pk__in=row_objects.get("deals.DealParty", set())).exists()
            or obj.owned_properties.exists()
        )
        if used:
            reasons.append(f"Organization {obj} is now used by other records.")
    return reasons


DELETE_ORDER = [
    "commissions.LedgerEntry", "commissions.CommissionInstallment", "commissions.CommissionAllocation",
    "commissions.CommissionAgreement", "deals.Activity", "deals.DealEvent", "deals.DealParty", "deals.Representation",
    "deals.PriceEvent", "deals.DealProperty", "deals.Deal", "crm.Contact", "properties.Property", "crm.Organization",
]


@transaction.atomic
def revert_batch(batch, actor):
    """Delete records created by this batch, row by row. Rows whose records have
    since been edited or used are left in place and reported."""
    if batch.status not in {"committed", "partially_reverted"}:
        raise ValueError("Only committed batches can be reverted.")
    # Objects created by all rows of this batch (shared organizations may be created
    # by one row and referenced by another).
    batch_objects = {}
    for row in batch.rows.filter(status__in=["committed", "revert_blocked"]):
        for label, pk in row.created_objects:
            batch_objects.setdefault(label, set()).add(pk)
    reverted = blocked = 0
    for row in batch.rows.filter(status__in=["committed", "revert_blocked"]).order_by("-row_number"):
        objs = []
        for label, pk in row.created_objects:
            model = apps.get_model(label)
            obj = model.objects.filter(pk=pk).first()
            if obj is not None:
                objs.append((label, obj))
        reasons = []
        for label, obj in objs:
            reasons += _blockers(label, obj, batch, batch_objects)
        if reasons:
            row.status = "revert_blocked"
            row.revert_note = " ".join(reasons)[:255]
            row.save(update_fields=["status", "revert_note"])
            blocked += 1
            continue
        for label in DELETE_ORDER:
            for obj_label, obj in objs:
                if obj_label != label:
                    continue
                if label == "crm.Organization" and _org_still_used(obj, batch_objects, row):
                    continue
                if label == "commissions.LedgerEntry":
                    # Reversal links are protected; remove reversals first.
                    type(obj).objects.filter(reverses=obj).delete()
                obj.delete()
        row.status = "reverted"
        row.revert_note = ""
        row.save(update_fields=["status", "revert_note"])
        reverted += 1
    batch.status = "reverted" if blocked == 0 else "partially_reverted"
    batch.reverted_at = timezone.now()
    batch.summary = {**batch.summary, "reverted": reverted, "revert_blocked": blocked}
    batch.save()
    audit(actor, "import.reverted", batch, {"reverted": reverted, "blocked": blocked})
    return reverted, blocked


def _org_still_used(org, batch_objects, row):
    """An organization created by an earlier row may still be used by rows that were
    not reverted; keep it in that case."""
    return (
        org.client_deals.exists()
        or org.contacts.exists()
        or DealParty.objects.filter(organization=org).exists()
        or org.owned_properties.exists()
    )
