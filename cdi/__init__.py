# =============================================================================
# cdi — reading Dragnet's controlled documents as the CDI framework structures them
#
#   codes     identifiers: document codes, control IDs, Record IDs
#   reader    a .docx or .pdf → ordered paragraphs and tables
#   fields    the value of one labelled field → structure
#   parser    a document → its control block, controls, implementations,
#             roles, records, open parameters and findings
#   library   many documents → what they say together
#
# Everything here is pure: bytes in, structure out. Storing results, resolving
# roles and records against the catalogues, and the review queue are separate
# layers built on top.
# =============================================================================

from cdi.library import LibraryFinding, LibraryIndex
from cdi.model import (
    ControlDefinition,
    DocumentRole,
    Finding,
    FindingKind,
    ImplementationStep,
    ParsedDocument,
    RecordRef,
    Severity,
)
from cdi.parser import PARSER_VERSION, parse_document
from cdi.reader import UnsupportedDocument

__all__ = [
    "PARSER_VERSION",
    "ControlDefinition",
    "DocumentRole",
    "Finding",
    "FindingKind",
    "ImplementationStep",
    "LibraryFinding",
    "LibraryIndex",
    "ParsedDocument",
    "RecordRef",
    "Severity",
    "UnsupportedDocument",
    "parse_document",
]
