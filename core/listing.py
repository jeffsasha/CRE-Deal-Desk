"""Reusable list screens: search, filters, sorting, customizable columns, saved
views and CSV export. Every list page uses this so behavior is consistent."""
import csv
from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.utils.html import strip_tags

from .models import SavedView


@dataclass
class Column:
    key: str
    label: str
    value: callable
    sort: str | None = None
    default: bool = True
    cls: str = ""
    export: callable = None


@dataclass
class Filter:
    name: str
    label: str
    choices: list
    apply: callable
    multiple: bool = False


@dataclass
class Listing:
    request: object
    queryset: object
    columns: list
    area: str
    search_fields: list = field(default_factory=list)
    filters: list = field(default_factory=list)
    default_sort: str = ""
    page_size: int = 100
    row_url: callable = None
    row_class: callable = None

    def __post_init__(self):
        params = self.request.GET
        qs = self.queryset
        self.q = params.get("q", "").strip()
        if self.q and self.search_fields:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f"{f}__icontains": self.q})
            qs = qs.filter(cond)
        self.active_filters = {}
        for flt in self.filters:
            value = params.get(flt.name, "")
            if value:
                self.active_filters[flt.name] = value
                qs = flt.apply(qs, value)
        sort = params.get("sort", self.default_sort)
        sortable = {c.sort for c in self.columns if c.sort}
        self.sort = sort if sort.lstrip("-") in sortable else self.default_sort
        if self.sort:
            qs = qs.order_by(self.sort, "pk")
        self.filtered = qs.distinct()
        cols = params.get("cols")
        if cols:
            keys = set(cols.split(","))
            self.visible = [c for c in self.columns if c.key in keys] or [c for c in self.columns if c.default]
        else:
            self.visible = [c for c in self.columns if c.default]
        self.page = Paginator(self.filtered, self.page_size).get_page(params.get("page"))

    def rows(self):
        out = []
        for obj in self.page.object_list:
            out.append({
                "obj": obj,
                "url": self.row_url(obj) if self.row_url else getattr(obj, "get_absolute_url", lambda: "")(),
                "cls": self.row_class(obj) if self.row_class else "",
                "cells": [(c, c.value(obj)) for c in self.visible],
            })
        return out

    def header(self):
        out = []
        for c in self.visible:
            next_sort = None
            if c.sort:
                next_sort = f"-{c.sort}" if self.sort == c.sort else c.sort
            out.append({"col": c, "url": self.url_with(sort=next_sort, page=None) if next_sort else None,
                        "active": self.sort.lstrip("-") == (c.sort or "~"), "desc": self.sort.startswith("-")})
        return out

    def url_with(self, **changes):
        params = self.request.GET.copy()
        for k, v in changes.items():
            if v is None:
                params.pop(k, None)
            else:
                params[k] = v
        return "?" + params.urlencode()

    @property
    def querystring(self):
        params = self.request.GET.copy()
        params.pop("page", None)
        params.pop("export", None)
        return params.urlencode()

    @property
    def saved_views(self):
        return SavedView.objects.filter(user=self.request.user, area=self.area)

    @property
    def visible_keys(self):
        return {c.key for c in self.visible}

    def filter_widgets(self):
        return [{"f": f, "value": self.active_filters.get(f.name, "")} for f in self.filters]

    def export_csv(self, filename):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        writer = csv.writer(response)
        writer.writerow([c.label for c in self.visible])
        for obj in self.filtered[:20000]:
            row = []
            for c in self.visible:
                val = c.export(obj) if c.export else c.value(obj)
                row.append(strip_tags(str(val if val is not None else "")))
            writer.writerow(row)
        return response


def querystring(**params):
    return urlencode({k: v for k, v in params.items() if v not in (None, "")})
