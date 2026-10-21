#!/usr/bin/env python3
# =============================================================================
# scripts/doc_standards_proof.py — prove the converter on a whole library
#
# Converts every .docx in a local copy of the library (nothing is written) and
# says how many converted, how many were refused and why, and whether any proof
# failed. Run it after any change to the converter or the graft: a surprise
# here is a document that would have been damaged.
#
#   python scripts/doc_standards_proof.py .cdi_corpus cdt_templates_out
# =============================================================================

import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from doc_standards.convert import convert_document  # noqa: E402


def main(library: str, templates: str) -> int:
    outcome, reasons, proof_failures, warnings = Counter(), Counter(), [], Counter()
    for path in sorted(Path(library).rglob("*.docx")):
        if path.name.startswith("~$"):
            continue
        data = path.read_bytes()
        first = convert_document(data, path.name)            # plan only: picks the template
        template = first.doc_type
        master = Path(templates, f"{template}.docx").read_bytes() if template else None
        plan = convert_document(data, path.name, master) if master else first
        if plan.ok and plan.proofs:
            outcome["converted, every proof holds"] += 1
        elif plan.ok:
            outcome["planned"] += 1
        elif plan.proofs:
            outcome["REFUSED: a proof failed"] += 1
            proof_failures.append((str(path.relative_to(library)), plan.reason))
        else:
            outcome["refused (cannot convert)"] += 1
            reasons[plan.reason[:110]] += 1
        for w in plan.warnings:
            warnings[w[:90]] += 1
    print(f"\nlibrary: {library}")
    for k, n in outcome.most_common():
        print(f"  {n:4}  {k}")
    if reasons:
        print("\nwhy documents were refused:")
        for k, n in reasons.most_common():
            print(f"  {n:4}  {k}")
    if proof_failures:
        print("\nPROOF FAILURES (the converter would have damaged these):")
        for p, r in proof_failures:
            print(f"   {p}\n      {r[:240]}")
    if warnings:
        print("\nwarnings shown to the person:")
        for k, n in warnings.most_common():
            print(f"  {n:4}  {k}")
    return 1 if proof_failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
