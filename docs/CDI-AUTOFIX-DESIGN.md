# CDI Auto-Fix — Design

**What it is:** when a document fails a CDI check, show the reviewer each issue with a suggested fix (the exact text to use), let them **confirm / edit / skip** each one, and on confirm **apply that exact fix to the document** — without ever letting the AI corrupt the file.

---

## 1. The one principle that keeps it safe

**The AI suggests. Deterministic code applies. The AI never touches the file.**

This is the same rule we locked in for CDT templating, and it's what stops the document being spoiled:

- The AI already ran at **check** time and produced, for each issue, two exact strings: **`current_text`** (the offending phrase, quoted from the document) and **`proposed_fix`** (the exact replacement).
- Applying a fix is therefore a **precise find-and-replace of one known string with another known string** — not an AI rewrite of the document. No model is called during "apply."
- Every apply is **located, single-span, verified, and reversible**. If anything is uncertain, it does **nothing** and asks a human.

So the worst realistic outcome is "a fix didn't apply, apply it manually" — never "the AI mangled the document."

## 2. We already have the raw material

The CDI checker's finding shape (`agents/cdi_checker/service.py::_fail`) is already exactly what a fixer needs:

```
{ check_id, check_name, finding, current_text, proposed_fix, fix_source, confidence }
```

`current_text` = *what to find*. `proposed_fix` = *what to replace it with*. That pairing is the feature.

**Prerequisite:** persist the **full** finding (including `current_text` and `proposed_fix`) in the document's stored `CDIFailures`. Today the stored form is simplified to `{check, detail, fix}`; the fixer needs the exact `current_text`/`proposed_fix`, so we store those too.

## 3. Three kinds of fix (not all are one-click)

| Kind | Example | How it applies |
|------|---------|----------------|
| **Exact swap** | CDI-06 aspirational: "the team will *endeavour to* protect" → "the team *shall* protect" | `current_text` → `proposed_fix` is a clean drop-in. **One-click confirm**, deterministic apply. |
| **Needs a choice** | CDI-16 unregistered role → pick a registered Role Register title; CDI-08 evidence → pick one of the 16 taxonomy codes | `proposed_fix` is a template/placeholder or needs a decision. The human **picks or edits** the replacement (dropdown of valid options), which turns it into an exact swap, then applies. |
| **Structural / metadata** | Missing Version, wrong document-code format, incomplete control block | Not a body-text replacement. Fixed by correcting the **control block / register fields** — the CDT templating domain (re-merge the template with the corrected field), *not* find-and-replace. Shown but routed differently. |

The "apply to the document" feature is for the first two (text in the body). Structural findings are handled by fixing the control block (ties into the CDT work).

## 4. The flow

```
Draft fails CDI
   │
   ▼
Reviewer opens "Fix CDI issues"
   │
   ├─ for each finding: LOCATE current_text in the .docx (deterministic)
   │     → located (unique) / ambiguous (many) / not-found
   │
   ▼
Reviewer reviews each card:
   • the issue + the current text (highlighted in context if located)
   • the proposed replacement (editable; dropdown when it's a choice)
   • Confirm / Edit-then-confirm / Pick-then-confirm / Skip
   │
   ▼
APPLY (deterministic, on a working copy):
   for each confirmed fix, in turn:
     • re-locate current_text in the CURRENT doc state (fixes can shift text)
     • replace that one span with the confirmed replacement
       (run-split-aware, formatting-preserving)
     • VERIFY: doc still opens; old text gone; new text present
     • on verify-fail → roll back THIS fix, mark "couldn't apply"
   │
   ▼
Save as a NEW draft version (original preserved via SharePoint history)
Re-run the CDI check → show before/after score
Audit-log every applied fix (who, when, check, old → new)
```

Fixes are applied **one at a time, re-locating before each**, so a fix that edits a sentence can't silently break a later fix that targeted the same sentence.

## 5. The locate engine (deterministic, fail-safe)

Finds *where* `current_text` lives in the `.docx`, robustly, and refuses to guess.

- **Search everywhere text can be:** body paragraphs, table cells, headers, footers.
- **Normalize both sides before matching:** smart quotes → straight quotes, non-breaking spaces → spaces, en/em-dashes, collapse runs of whitespace, trim. Word text and the AI's quoted text often differ only in these.
- **Reassemble run-split text:** Word chops a sentence across several "runs"; the locator matches against the *joined* paragraph text, not individual runs.
- **Outcomes:**
  - **Unique match** → applicable.
  - **Multiple matches** → show all occurrences with surrounding context; the reviewer picks which one(s). Never auto-replace-all.
  - **No match** (paraphrased/truncated finding, heavy formatting) → mark **"couldn't locate — here's the fix, apply manually."** Never touch the file.

## 6. The apply engine (formatting-preserving, verified)

Replaces one located span with the confirmed text, in a way Word keeps intact.

- **Single run:** replace the substring inside that run — formatting preserved exactly.
- **Spanning runs:** put the whole replacement into the first run of the span, blank the covered text in the following runs. The replacement inherits the first run's formatting. (A bolded word inside the replaced span may normalize to the surrounding style — acceptable for a plain-text correction, and the reviewer saw the result before confirming.)
- **Match the document's quote/space style** in the replacement (straight vs smart quotes) so the fix doesn't look foreign.
- **Verify after each apply:** re-open the `.docx` (it must be a valid package), confirm `current_text` is gone and the replacement is present. If not → **roll back that one fix** and report it; other fixes are unaffected.

## 7. Scenarios, and how each is handled

| # | Scenario | Handling |
|---|----------|----------|
| A | Offending text appears once | Locate + replace. |
| B | Appears multiple times | Show every occurrence in context; reviewer chooses which; never blind replace-all. |
| C | Can't find the exact text (paraphrase/truncation/quotes) | Normalize + retry; if still not found, **don't touch it** — "apply manually." |
| D | Text spans several Word runs | Match against joined paragraph text; replace across the span (§6). |
| E | Replacing changes formatting | Preserve the paragraph/first-run style; reviewer previewed the result before confirming. |
| F | Issue is in a table cell / header / footer | Locator searches those too. |
| G | Two fixes touch the same sentence | Apply sequentially, **re-locate before each**; if a later fix no longer matches, skip + flag (don't corrupt). |
| H | Document is a **PDF**, not `.docx` | Can't safely edit a PDF (same reason as CDT migration). Show the suggestions, **disable auto-apply**; require the editable `.docx`. |
| I | Reviewer edits the suggested replacement | The edited text is what gets applied — the AI's suggestion is a starting point, not the final word. |
| J | A fix would create a *new* CDI violation | Re-check after applying; show the new score. Not blocked, but surfaced. |
| K | Fix needs a judgement (which role? which evidence code?) | "Needs a choice" card — reviewer picks from valid options (registered roles / the 16 evidence codes); then it's an exact swap. |
| L | Smart quotes / non-breaking spaces / dashes | Normalized on match; replacement written in the document's own style. |
| M | Finding is about a metadata/control-block field | Routed to the control-block/template fix, not body find-and-replace (§3). |
| N | Two people fix the same doc at once | Apply against the latest version; on a version conflict, reload and re-confirm (no blind overwrite). |
| O | A fix goes wrong / reviewer regrets it | Every apply produces a new version and is audit-logged; the prior version is intact in SharePoint history → revert. |

## 8. The "won't spoil the document" guarantees (the lock-in)

1. **AI never mutates the file** — apply is deterministic code over known strings.
2. **Only editable `.docx`** can be auto-fixed; PDFs get suggestions only.
3. **Exact, located, single-span** replacement — never a whole-doc rewrite, never blind global replace.
4. **Fail-safe:** can't locate uniquely → does nothing, asks a human.
5. **Verify-after-apply**, with **per-fix rollback** on failure.
6. **New version, original preserved** (SharePoint history) → always reversible.
7. **Human confirms every fix** and can edit the replacement.
8. **Re-check after fixing** to catch anything the fixes introduced.
9. **Audit trail** for every applied fix (who/when/check/old→new).

## 9. What we'd build

- **Persist full findings** in `CDIFailures` (add `current_text`, `proposed_fix`, `check_id`, `confidence`) — small change at CDI-check time.
- **`cdi_locate` (pure):** given `.docx` bytes + `current_text` → normalized search across body/tables/headers/footers → `located | ambiguous(occurrences) | not_found`. Unit-testable, no I/O.
- **`cdi_apply` (pure):** given `.docx` bytes + a list of confirmed `{locate, replace, occurrence}` → run-split-aware, formatting-preserving replacement + verify → new `.docx` bytes (or per-fix failures). Unit-testable, no I/O.
- **Endpoint:** `POST /lifecycle/documents/{id}/cdi-fix/apply` — body = the reviewer's confirmed fixes; downloads the draft `.docx`, runs `cdi_apply`, saves a new draft version, re-runs the CDI check, audit-logs, returns the new score + any fixes that couldn't apply.
- **Frontend:** a "Fix CDI issues" panel — one card per finding (issue, current text in context, editable replacement / choice dropdown, Confirm/Skip), a batch "Apply confirmed" action, and the before/after score.

## 10. Open decisions (small)

- **Batch vs one-at-a-time confirm:** allow "confirm all high-confidence exact swaps" in one click, but choices/edits stay per-card. (Recommended.)
- **Where it runs:** during the **Review** stage on the **draft**, before approval — fixing to get CDI to pass so the doc can progress. (Recommended; matches the current CDI gate.)
- **Formatting on span-crossing replacements:** accept normalization to the first run's style (Recommended) vs refuse to auto-apply those (safer but fewer one-clicks).

---

*Same DNA as CDT: the AI reasons; deterministic code edits; the human confirms; nothing is ever silently mangled, and everything is reversible.*
