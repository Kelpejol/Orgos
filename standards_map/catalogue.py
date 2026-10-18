# =============================================================================
# standards_map/catalogue.py — the standards Dragnet maps to, and their clauses
#
# One list, used by the Standards Map and the Gap Analyzer alike. They each
# kept their own hand-written list before — 23 clauses and 18 — and the two had
# already drifted: five clauses were shown on the map but never checked for
# gaps. Neither had ISO 22301 or any clause the BCDR documents map to.
#
# Matching a control to a clause is decided here too, and exactly:
#   - by standard AND clause — ISO 27001 7.5 and ISO 9001 7.5 are different
#     clauses. The old map matched on the clause string alone;
#   - by the clause's own path — a control mapped to 7.5.2 counts towards
#     7.5, but one mapped to A.5.18 does NOT count towards A.5.1. The old
#     `startswith` counted A.5.18 under A.5.1 as well.
#
# Titles: ISO/IEC 27001:2022 (clauses and all 93 Annex A controls), ISO
# 9001:2015 and ISO 22301:2019 are enumerated with their titles. Laws — the
# NDPA 2023 and its GAID 2025 — are open: any section or article is a valid
# reference, and no titles are held, because a wrong title on a compliance map
# is worse than none. Compliance can add them.
# =============================================================================

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from cdi.fields import parse_mapping
from cdi.model import StandardsRef


@dataclass(frozen=True)
class Standard:
    name: str            # "ISO 27001"
    edition: str         # "2022"
    title: str
    # Closed: only the clauses listed here exist. Open: any section, article
    # or clause is accepted as a reference (laws; standards not enumerated).
    closed: bool


@dataclass(frozen=True)
class Clause:
    standard: str
    clause: str
    title: str = ""

    @property
    def key(self) -> str:
        return f"{self.standard} {self.clause}"


STANDARDS: dict[str, Standard] = {s.name: s for s in (
    Standard("ISO 27001", "2022", "Information security management systems", closed=True),
    Standard("ISO 9001", "2015", "Quality management systems", closed=True),
    Standard("ISO 22301", "2019", "Business continuity management systems", closed=True),
    Standard("NDPA", "2023", "Nigeria Data Protection Act", closed=False),
    Standard("GAID", "2025", "NDPA General Application and Implementation Directive", closed=False),
    Standard("NDPR", "2019", "Nigeria Data Protection Regulation", closed=False),
    Standard("ISO 27017", "", "Information security controls for cloud services", closed=False),
    Standard("ISO 27018", "", "Protection of PII in public clouds", closed=False),
)}


# ── ISO/IEC 27001:2022 ───────────────────────────────────────────────────────

_ISO_27001 = """
4|Context of the organization
4.1|Understanding the organization and its context
4.2|Understanding the needs and expectations of interested parties
4.3|Determining the scope of the information security management system
4.4|Information security management system
5|Leadership
5.1|Leadership and commitment
5.2|Policy
5.3|Organizational roles, responsibilities and authorities
6|Planning
6.1|Actions to address risks and opportunities
6.1.1|General
6.1.2|Information security risk assessment
6.1.3|Information security risk treatment
6.2|Information security objectives and planning to achieve them
6.3|Planning of changes
7|Support
7.1|Resources
7.2|Competence
7.3|Awareness
7.4|Communication
7.5|Documented information
7.5.1|General
7.5.2|Creating and updating
7.5.3|Control of documented information
8|Operation
8.1|Operational planning and control
8.2|Information security risk assessment
8.3|Information security risk treatment
9|Performance evaluation
9.1|Monitoring, measurement, analysis and evaluation
9.2|Internal audit
9.2.1|General
9.2.2|Internal audit programme
9.3|Management review
9.3.1|General
9.3.2|Management review inputs
9.3.3|Management review results
10|Improvement
10.1|Continual improvement
10.2|Nonconformity and corrective action
A.5|Organizational controls
A.5.1|Policies for information security
A.5.2|Information security roles and responsibilities
A.5.3|Segregation of duties
A.5.4|Management responsibilities
A.5.5|Contact with authorities
A.5.6|Contact with special interest groups
A.5.7|Threat intelligence
A.5.8|Information security in project management
A.5.9|Inventory of information and other associated assets
A.5.10|Acceptable use of information and other associated assets
A.5.11|Return of assets
A.5.12|Classification of information
A.5.13|Labelling of information
A.5.14|Information transfer
A.5.15|Access control
A.5.16|Identity management
A.5.17|Authentication information
A.5.18|Access rights
A.5.19|Information security in supplier relationships
A.5.20|Addressing information security within supplier agreements
A.5.21|Managing information security in the ICT supply chain
A.5.22|Monitoring, review and change management of supplier services
A.5.23|Information security for use of cloud services
A.5.24|Information security incident management planning and preparation
A.5.25|Assessment and decision on information security events
A.5.26|Response to information security incidents
A.5.27|Learning from information security incidents
A.5.28|Collection of evidence
A.5.29|Information security during disruption
A.5.30|ICT readiness for business continuity
A.5.31|Legal, statutory, regulatory and contractual requirements
A.5.32|Intellectual property rights
A.5.33|Protection of records
A.5.34|Privacy and protection of PII
A.5.35|Independent review of information security
A.5.36|Compliance with policies, rules and standards for information security
A.5.37|Documented operating procedures
A.6|People controls
A.6.1|Screening
A.6.2|Terms and conditions of employment
A.6.3|Information security awareness, education and training
A.6.4|Disciplinary process
A.6.5|Responsibilities after termination or change of employment
A.6.6|Confidentiality or non-disclosure agreements
A.6.7|Remote working
A.6.8|Information security event reporting
A.7|Physical controls
A.7.1|Physical security perimeters
A.7.2|Physical entry
A.7.3|Securing offices, rooms and facilities
A.7.4|Physical security monitoring
A.7.5|Protecting against physical and environmental threats
A.7.6|Working in secure areas
A.7.7|Clear desk and clear screen
A.7.8|Equipment siting and protection
A.7.9|Security of assets off-premises
A.7.10|Storage media
A.7.11|Supporting utilities
A.7.12|Cabling security
A.7.13|Equipment maintenance
A.7.14|Secure disposal or re-use of equipment
A.8|Technological controls
A.8.1|User end point devices
A.8.2|Privileged access rights
A.8.3|Information access restriction
A.8.4|Access to source code
A.8.5|Secure authentication
A.8.6|Capacity management
A.8.7|Protection against malware
A.8.8|Management of technical vulnerabilities
A.8.9|Configuration management
A.8.10|Information deletion
A.8.11|Data masking
A.8.12|Data leakage prevention
A.8.13|Information backup
A.8.14|Redundancy of information processing facilities
A.8.15|Logging
A.8.16|Monitoring activities
A.8.17|Clock synchronization
A.8.18|Use of privileged utility programs
A.8.19|Installation of software on operational systems
A.8.20|Networks security
A.8.21|Security of network services
A.8.22|Segregation of networks
A.8.23|Web filtering
A.8.24|Use of cryptography
A.8.25|Secure development life cycle
A.8.26|Application security requirements
A.8.27|Secure system architecture and engineering principles
A.8.28|Secure coding
A.8.29|Security testing in development and acceptance
A.8.30|Outsourced development
A.8.31|Separation of development, test and production environments
A.8.32|Change management
A.8.33|Test information
A.8.34|Protection of information systems during audit testing
"""

# ── ISO 9001:2015 ────────────────────────────────────────────────────────────

_ISO_9001 = """
4|Context of the organization
4.1|Understanding the organization and its context
4.2|Understanding the needs and expectations of interested parties
4.3|Determining the scope of the quality management system
4.4|Quality management system and its processes
5|Leadership
5.1|Leadership and commitment
5.1.1|General
5.1.2|Customer focus
5.2|Policy
5.3|Organizational roles, responsibilities and authorities
6|Planning
6.1|Actions to address risks and opportunities
6.2|Quality objectives and planning to achieve them
6.3|Planning of changes
7|Support
7.1|Resources
7.1.1|General
7.1.2|People
7.1.3|Infrastructure
7.1.4|Environment for the operation of processes
7.1.5|Monitoring and measuring resources
7.1.6|Organizational knowledge
7.2|Competence
7.3|Awareness
7.4|Communication
7.5|Documented information
7.5.1|General
7.5.2|Creating and updating
7.5.3|Control of documented information
8|Operation
8.1|Operational planning and control
8.2|Requirements for products and services
8.2.1|Customer communication
8.2.2|Determining the requirements for products and services
8.2.3|Review of the requirements for products and services
8.2.4|Changes to requirements for products and services
8.3|Design and development of products and services
8.4|Control of externally provided processes, products and services
8.5|Production and service provision
8.5.1|Control of production and service provision
8.5.2|Identification and traceability
8.5.3|Property belonging to customers or external providers
8.5.4|Preservation
8.5.5|Post-delivery activities
8.5.6|Control of changes
8.6|Release of products and services
8.7|Control of nonconforming outputs
9|Performance evaluation
9.1|Monitoring, measurement, analysis and evaluation
9.1.1|General
9.1.2|Customer satisfaction
9.1.3|Analysis and evaluation
9.2|Internal audit
9.3|Management review
9.3.1|General
9.3.2|Management review inputs
9.3.3|Management review outputs
10|Improvement
10.1|General
10.2|Nonconformity and corrective action
10.3|Continual improvement
"""

# ── ISO 22301:2019 ───────────────────────────────────────────────────────────

_ISO_22301 = """
4|Context of the organization
4.1|Understanding the organization and its context
4.2|Understanding the needs and expectations of interested parties
4.3|Determining the scope of the business continuity management system
4.4|Business continuity management system
5|Leadership
5.1|Leadership and commitment
5.2|Policy
5.3|Roles, responsibilities and authorities
6|Planning
6.1|Actions to address risks and opportunities
6.2|Business continuity objectives and planning to achieve them
6.3|Planning changes to the business continuity management system
7|Support
7.1|Resources
7.2|Competence
7.3|Awareness
7.4|Communication
7.5|Documented information
8|Operation
8.1|Operational planning and control
8.2|Business impact analysis and risk assessment
8.3|Business continuity strategies and solutions
8.4|Business continuity plans and procedures
8.5|Exercise programme
8.6|Evaluation of business continuity documentation and capabilities
9|Performance evaluation
9.1|Monitoring, measurement, analysis and evaluation
9.2|Internal audit
9.3|Management review
10|Improvement
10.1|Nonconformity and corrective action
10.2|Continual improvement
"""


def _load(standard: str, table: str) -> list[Clause]:
    return [
        Clause(standard, number.strip(), title.strip())
        for line in table.strip().splitlines()
        for number, title in [line.split("|", 1)]
    ]


CLAUSES: dict[str, Clause] = {
    c.key: c
    for c in (
        _load("ISO 27001", _ISO_27001)
        + _load("ISO 9001", _ISO_9001)
        + _load("ISO 22301", _ISO_22301)
    )
}


# ── what Dragnet must cover ─────────────────────────────────────────────────
#
# The clauses the Gap Analyzer requires, and the Standards Map always shows
# even before any control maps to them. Carried over unchanged from the two
# lists it replaces (the five the map showed but the gap check skipped now
# require a control). Applicability is a business decision — for ISO 27001
# it belongs to the Statement of Applicability — so this is where an SoA
# would be read from.
#
#   requires: "policy" (a governing document), "control", or "control+record"

APPLICABLE: tuple[tuple[str, str, str], ...] = (
    ("ISO 27001", "A.5.1", "policy"),
    ("ISO 27001", "A.5.12", "control"),
    ("ISO 27001", "A.5.15", "control"),
    ("ISO 27001", "A.5.16", "control"),
    ("ISO 27001", "A.5.17", "control"),
    ("ISO 27001", "A.5.18", "control+record"),
    ("ISO 27001", "A.5.25", "control"),
    ("ISO 27001", "A.5.26", "control+record"),
    ("ISO 27001", "A.6.1", "control"),
    ("ISO 27001", "A.7.1", "control"),
    ("ISO 27001", "A.8.1", "control+record"),
    ("ISO 27001", "A.8.24", "control+record"),
    ("ISO 27001", "A.8.25", "control"),
    ("ISO 27001", "A.8.32", "control"),
    ("ISO 9001", "7.5", "policy"),
    ("ISO 9001", "8.4", "control"),
    ("ISO 9001", "9.1", "control"),
    ("ISO 9001", "9.2", "control+record"),
    ("ISO 9001", "10.2", "control"),
    ("NDPA", "S.24", "control"),
    ("NDPA", "S.30", "control"),
    ("NDPA", "S.39", "control+record"),
    ("NDPA", "S.40", "control"),
)


# =============================================================================
#  Lookups and matching
# =============================================================================

def _parent(clause: str) -> Optional[str]:
    """'7.5.3' → '7.5'; 'A.5.18' → 'A.5'; '7' → None; 'S.24' → None."""
    if "." not in clause or re.fullmatch(r"(?:S|Art|Sch)\.\w+", clause):
        return None
    head, _, _ = clause.rpartition(".")
    return head or None


def clause(standard: str, number: str) -> Optional[Clause]:
    """
    The catalogue entry for a reference. A closed standard resolves to the
    clause itself or its nearest listed parent (9.3.2 → 9.3), and to None if
    nothing matches. An open standard accepts any reference.
    """
    std = STANDARDS.get(standard)
    if std is None or not number:
        return None
    if not std.closed:
        return CLAUSES.get(f"{standard} {number}") or Clause(standard, number)
    current: Optional[str] = number
    while current:
        found = CLAUSES.get(f"{standard} {current}")
        if found:
            return found
        current = _parent(current)
    return None


def covers(row: Clause, ref: StandardsRef) -> bool:
    """
    Does a control mapped to `ref` count towards clause `row`? Same standard,
    and the same clause or one inside it: 7.5.2 counts towards 7.5; A.5.18
    does not count towards A.5.1. A mapping to a whole standard counts
    towards no single clause.
    """
    if ref.standard != row.standard or not ref.clause:
        return False
    return ref.clause == row.clause or ref.clause.startswith(row.clause + ".")


def applicable_clauses() -> list[tuple[Clause, str]]:
    """(clause, what it requires) for every clause Dragnet must cover."""
    return [(clause(s, c) or Clause(s, c), requires) for s, c, requires in APPLICABLE]


# =============================================================================
#  A control's mapping, from what the Control Register holds
# =============================================================================

def control_mapping(fields: dict) -> list[StandardsRef]:
    """
    The clauses a Control Register row maps to.

    MappingJson (structured, written from a parsed control) is used when
    present. Otherwise the free-text ISOClause is parsed. A bare clause with
    no standard is placed only where that is unambiguous — "A.5.18" can only
    be ISO 27001's Annex A, "S.24" only a law's section — and otherwise left
    unplaced, because 7.5 exists in ISO 27001, 9001 and 22301 alike.
    """
    raw = fields.get("MappingJson")
    if raw:
        try:
            return [StandardsRef(**r) for r in json.loads(raw)]
        except (ValueError, TypeError):
            pass

    text = (fields.get("ISOClause") or "").strip()
    if not text:
        return []
    refs, unread = parse_mapping(text)
    for token in unread:
        t = token.strip().rstrip(".")
        if re.fullmatch(r"A\.\s?\d+(?:\.\d+)*", t):
            refs.append(StandardsRef("ISO 27001", t.replace(" ", ""), as_written=token))
        elif re.fullmatch(r"S\.\s?\d+[A-Za-z]?", t, re.IGNORECASE):
            refs.append(StandardsRef("NDPA", "S." + t.split(".", 1)[1].strip().upper(), as_written=token))
    return refs


def rows_for(refs: Iterable[StandardsRef]) -> list[Clause]:
    """The catalogue clauses a set of mapped references lands on."""
    out: dict[str, Clause] = {}
    for ref in refs:
        found = clause(ref.standard, ref.clause)
        if found:
            out[found.key] = found
    return list(out.values())
