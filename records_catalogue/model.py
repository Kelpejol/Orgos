# =============================================================================
# records_catalogue/model.py — one governed record in the Enterprise Records
# Catalogue (REC-0632)
#
# The Catalogue names its own system of record as "S09 OrgOS GRC", so OrgOS
# holds it. Every field is carried as the Catalogue states it, and above all
# every VALIDATION status: 625 of 729 records are "identity/type-only" —
# their ID and Type are admitted, their operational metadata is not — and
# Bobby's brief requires that "Catalogue entries marked recommended or pending
# business review must retain that status".
#
# Nothing here is inferred. A blank in the Catalogue is a blank here.
# =============================================================================

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecordEntry:
    record_id: str                       # REC-0676
    name: str                            # Canonical Record Name
    aliases: list[str] = field(default_factory=list)
    record_type: str = ""                # Controlled Record Type (semantics only, GR-01)
    type_mapping_confidence: str = ""
    admission_status: str = ""           # "Governed Record" | "Withdrawn duplicate proposal"
    discovery_proposed_type: str = ""
    source_count: str = ""
    source_documents: str = ""
    source_process_references: str = ""
    source_urls: str = ""
    privacy_overlay: str = ""
    findability_statement: str = ""
    findability_validation: str = ""
    retention_statement: str = ""
    retention_validation: str = ""
    custodian: str = ""                  # Process Custodian — a role, may be functional
    location: str = ""                   # Authoritative Location / System (System ID first)
    retrieval_instruction: str = ""
    retention_rule: str = ""             # e.g. RR-26 (defined in the Retention Rule Schedule)
    retention_trigger: str = ""
    retention_authority: str = ""
    disposition: str = ""
    destruction_method: str = ""
    destruction_evidence: str = ""
    legal_hold: str = ""
    specialist_register_reference: str = ""
    mapping_rationale: str = ""
    record_validation_status: str = ""

    # ── what the record may be used for ─────────────────────────────────────

    @property
    def withdrawn(self) -> bool:
        """A withdrawn duplicate proposal: never link evidence to it."""
        return "withdrawn" in self.admission_status.lower()

    @property
    def system_id(self) -> str:
        """'S01' from 'S01 SharePoint, Governance & Records library, …', or ''."""
        m = re.match(r"^\s*(S\d{2})\b", self.location)
        return m.group(1) if m else ""

    @property
    def retention_validated(self) -> bool:
        return self.retention_validation.strip().lower().startswith("validated")

    def disposition_gate(self) -> tuple[bool, str]:
        """
        May this record be disposed of AUTOMATICALLY? (allowed, reason)

        Catalogue rule GR-11 and Bobby's brief: automated disposal must not
        proceed on unvalidated retention. Even the eight validated records say
        their final destruction method "remains controlled separately", so the
        gate also honours any record whose own status prohibits it.
        """
        if self.withdrawn:
            return False, "Withdrawn duplicate proposal — not a governed record."
        if not self.retention_validated:
            return False, (
                f"Retention is not validated (“{self.retention_validation or 'not stated'}”). "
                "Automated disposition is prohibited until it is (Catalogue GR-11)."
            )
        if "prohibited" in self.record_validation_status.lower():
            return False, f"The record's own status prohibits it: “{self.record_validation_status}”."
        return True, "Retention validated from a controlled source."

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecordEntry":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def normalise_name(text: str) -> str:
    """Comparison key for record names: case, punctuation and spacing ignored."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
