"""Integer-cent money helpers.

All stored money amounts are integer cents. `None` means *unknown* and is never
coerced to zero: totals report how many inputs were unknown instead.
"""
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


class MoneyParseError(ValueError):
    pass


def parse_cents(value):
    """Parse '$1,250,000.50' -> 125000050. Blank -> None (unknown). '0' -> 0."""
    if value is None:
        return None
    if isinstance(value, int):
        return value * 100
    if isinstance(value, (float, Decimal)):
        return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    text = str(value).strip()
    if text == "" or text.lower() in {"unknown", "n/a", "na", "tbd", "?", "-", "—"}:
        return None
    negative = text.startswith("(") and text.endswith(")") or text.startswith("-") or "$-" in text
    cleaned = re.sub(r"[\s$,()]", "", text).lstrip("-")
    if not cleaned or not re.fullmatch(r"\d*\.?\d*", cleaned) or cleaned == ".":
        raise MoneyParseError(f"Not a money amount: {value!r}")
    try:
        cents = int((Decimal(cleaned) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise MoneyParseError(f"Not a money amount: {value!r}") from exc
    return -cents if negative else cents


def cents_from_decimal(amount):
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def percent_of(cents, percent):
    """Apply a percentage (Decimal like 3.0 meaning 3%) to cents with half-up rounding."""
    if cents is None or percent is None:
        return None
    return int((Decimal(cents) * Decimal(percent) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_cents(cents, unknown="Unknown", show_cents=True):
    if cents is None:
        return unknown
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    dollars, rem = divmod(cents, 100)
    if show_cents:
        return f"{sign}${dollars:,}.{rem:02d}"
    return f"{sign}${dollars + (1 if rem >= 50 else 0):,}"


@dataclass
class Total:
    """Sum of possibly-unknown amounts. `unknown_count` items are excluded from `known`."""

    known: int = 0
    unknown_count: int = 0
    count: int = 0
    sources: list = field(default_factory=list)

    def add(self, cents, source=None):
        self.count += 1
        if cents is None:
            self.unknown_count += 1
        else:
            self.known += int(cents)
        if source is not None:
            self.sources.append(source)
        return self

    @property
    def is_complete(self):
        return self.unknown_count == 0

    def display(self):
        text = format_cents(self.known)
        if self.unknown_count:
            text += f" + {self.unknown_count} unknown"
        return text
