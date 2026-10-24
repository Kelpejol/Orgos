# =============================================================================
# doc_standards/roles.py — does this role exist, and if not, which one is meant?
#
# Org Roles is the Role Register (until the organogram fills it). A role named in
# a controlled document must be one of its roles — by name, or by an alias someone
# has already agreed (CDI V07). A Microsoft job title alone is never a role.
#
# When a document names something that is not a role, the author is helped, not
# just told off: the nearest roles that EXIST are suggested, with why. Nothing is
# invented — a suggestion is always an existing role, scored by plain text
# similarity (shared words, shared initials, close spelling), so that every
# suggestion can be explained in one line. A person always makes the choice.
#
# Pure: no I/O. Loading Org Roles is the caller's job.
# =============================================================================

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

_STOP = {"the", "of", "and", "for", "a", "an", "to", "in", "on"}

# The names of fields and of context roles, which are not roles themselves. A control
# that says "Control owner: Control Owner" has named the field, not a role.
PLACEHOLDERS = {"control owner", "document owner", "custodian role", "custodian", "owner", "responsible role",
                "accountable", "executing", "accountable role", "executing role"}

MIN_SUGGESTION_SCORE = 50


def norm(text: str) -> str:
    """Lower case; '&' and '/' both read as "and"; punctuation and extra space gone."""
    t = (text or "").lower().replace("&", " and ").replace("/", " and ")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", t).split())


def _strip_parenthetical(text: str) -> str:
    return norm(re.sub(r"\([^)]*\)", " ", text or ""))


def _tokens(text: str) -> list[str]:
    return [w for w in norm(text).split() if w not in _STOP]


def _initials(tokens: list[str]) -> str:
    return "".join(t[0] for t in tokens)


def _token_match(a: str, b: str) -> bool:
    """Same word, or one begins the other ('info' / 'information'; at least 3 letters)."""
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


@dataclass(frozen=True)
class Role:
    group_id: str
    name: str
    aliases: tuple[str, ...] = ()
    description: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class Suggestion:
    role: Role
    score: int            # 0–100
    reason: str
    via: str = ""         # the alias that matched, if it was not the name

    def as_dict(self) -> dict:
        return {"group_id": self.role.group_id, "name": self.role.name, "score": self.score,
                "reason": self.reason, "via": self.via}


def similarity(written: str, candidate: str) -> tuple[int, str]:
    """(0–100, why) — how likely `written` means `candidate`."""
    a, b = norm(written), norm(candidate)
    if not a or not b:
        return 0, ""
    if a == b:
        return 100, "the same role"
    if _strip_parenthetical(written) == _strip_parenthetical(candidate):
        return 97, "the same role, apart from the bracketed part"
    ta, tb = _tokens(written), _tokens(candidate)
    if not ta or not tb:
        return 0, ""
    # An abbreviation: "ISO" for Information Security Officer, "CCO" for Chief Compliance Officer.
    compact = a.replace(" ", "")
    if len(ta) == 1 and 2 <= len(compact) <= 6 and compact.isalpha() and compact == _initials(tb):
        return 90, f"“{written.strip()}” are the initials of {candidate}"
    if len(tb) == 1 and 2 <= len(b) <= 6 and b.isalpha() and b == _initials(ta):
        return 90, f"{candidate} are the initials of “{written.strip()}”"
    hit_a = sum(1 for x in ta if any(_token_match(x, y) for y in tb))
    hit_b = sum(1 for y in tb if any(_token_match(x, y) for x in ta))
    cover_a, cover_b = hit_a / len(ta), hit_b / len(tb)
    f1 = 0.0 if not (cover_a and cover_b) else 2 * cover_a * cover_b / (cover_a + cover_b)
    ratio = SequenceMatcher(None, a, b).ratio()
    score = round(100 * max(0.9 * f1, 0.5 * f1 + 0.5 * ratio))
    shared = [x for x in ta if any(_token_match(x, y) for y in tb)]
    if score >= MIN_SUGGESTION_SCORE:
        if cover_a == 1.0 or cover_b == 1.0:
            return score, "every word of one is in the other"
        if shared:
            return score, "shares " + ", ".join(shared)
        return score, "close spelling"
    return score, ""


class RoleBook:
    """The roles that exist: Org Roles, with the spellings already agreed as aliases."""

    def __init__(self, roles: Iterable[Role] = ()):
        self.roles = list(roles)
        self._exact: dict[str, tuple[Role, str]] = {}
        for role in self.roles:
            for spelling in role.names:
                key = norm(spelling)
                # A name beats an alias of another role, and the first role to claim a spelling keeps it.
                if key and (key not in self._exact or spelling == role.name):
                    self._exact.setdefault(key, (role, "" if spelling == role.name else spelling))

    @classmethod
    def from_groups(cls, groups: Iterable[dict]) -> "RoleBook":
        return cls(Role(str(g.get("id", "")), (g.get("name") or "").strip(),
                        tuple(a for a in g.get("aliases", []) if (a or "").strip()),
                        g.get("description", "") or "")
                   for g in groups if (g.get("name") or "").strip())

    def __len__(self) -> int:
        return len(self.roles)

    def find(self, text: str) -> Optional[Role]:
        """The role this text names — by its name or an agreed alias — or None."""
        hit = self._exact.get(norm(text))
        return hit[0] if hit else None

    def suggest(self, text: str, limit: int = 3) -> list[Suggestion]:
        """The roles that exist and are most likely meant. Empty when nothing is close."""
        if is_placeholder(text):
            return []
        best: dict[str, Suggestion] = {}
        for role in self.roles:
            for spelling in role.names:
                score, why = similarity(text, spelling)
                if score >= MIN_SUGGESTION_SCORE and why:
                    via = "" if spelling == role.name else spelling
                    if role.group_id not in best or score > best[role.group_id].score:
                        best[role.group_id] = Suggestion(role, score, why, via)
        return sorted(best.values(), key=lambda s: (-s.score, s.role.name))[:limit]


def is_placeholder(text: str) -> bool:
    return norm(text) in PLACEHOLDERS


def describes_a_group(text: str) -> bool:
    """A phrase that describes kinds of roles rather than naming one ("Requester, approver and owner roles")."""
    t = norm(text)
    return t.endswith(" roles") or t.endswith(" role holders") or t in {"all staff", "everyone", "all employees", "all users"}


def names_several(text: str) -> bool:
    """A value that lists more than one role. ';' separates roles; a role's own name may contain 'and' or '/'."""
    return ";" in (text or "")
