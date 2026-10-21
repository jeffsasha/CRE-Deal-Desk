"""Contract extraction produces *proposals only*. Nothing here writes to a deal; a
person reviews every value, and deterministic code (deadlines, ledger) never reads
unreviewed proposals."""
from dataclasses import dataclass, field


@dataclass
class Proposal:
    key: str
    label: str
    value: str
    page: int | None = None
    section: str = ""
    supporting_text: str = ""
    confidence: str = "low"  # high | medium | low
    basis: str = "explicit"  # explicit | calculated
    calculation_note: str = ""
    flags: list = field(default_factory=list)


@dataclass
class ExtractionOutput:
    engine: str
    model_name: str = ""
    doc_type: str = "unknown"
    execution_status: str = "unknown"
    execution_evidence: str = ""
    summary: str = ""
    proposals: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)
