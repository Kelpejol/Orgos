#!/usr/bin/env bash
# =============================================================================
# scripts/setup_intake_cron.sh — Install twice-daily intake cron jobs
#
# Runs the SharePoint → Document Lifecycle intake at:
#   06:00 WAT (05:00 UTC)
#   20:00 WAT (19:00 UTC)
#
# Usage (run once on the server):
#   bash scripts/setup_intake_cron.sh
#
# To remove the jobs later:
#   crontab -e   (delete the two OrgOS Intake lines)
# =============================================================================

set -euo pipefail

# ── Resolve absolute repo root (works wherever the script is called from) ────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# ── Detect python3 interpreter ───────────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
  echo "ERROR: python3 not found on PATH."
  exit 1
fi

# ── Detect virtualenv (optional) ─────────────────────────────────────────────
# If a virtual environment exists at orgos_env/, use its python so all
# dependencies are available without activating the venv in the cron shell.
VENV_PYTHON="$REPO_DIR/orgos_env/bin/python3"
if [ -f "$VENV_PYTHON" ]; then
  PYTHON="$VENV_PYTHON"
  echo "Using venv python: $PYTHON"
else
  echo "Using system python: $PYTHON"
fi

INTAKE_SCRIPT="$REPO_DIR/scripts/intake_sharepoint_to_lifecycle.py"
LOG_DIR="$REPO_DIR/logs/intake"
CRON_LOG="$LOG_DIR/cron.log"

# Ensure log directory exists now so cron can always redirect to it
mkdir -p "$LOG_DIR"

# ── Build the cron command ────────────────────────────────────────────────────
# --no-cdi skips CDI checks (already handled in lifecycle upload).
# stdout/stderr → cron.log (append). Each run also writes its own dated log.
CRON_CMD="$PYTHON $INTAKE_SCRIPT --no-cdi >> $CRON_LOG 2>&1"

# ── Cron entries (UTC — server must be on UTC) ────────────────────────────────
CRON_MORNING="0 5 * * * $CRON_CMD"   # 05:00 UTC = 06:00 WAT
CRON_EVENING="0 19 * * * $CRON_CMD"  # 19:00 UTC = 20:00 WAT

MARKER="# OrgOS Intake"

# ── Install without duplicating ───────────────────────────────────────────────
CURRENT=$(crontab -l 2>/dev/null || true)

if echo "$CURRENT" | grep -qF "$MARKER"; then
  echo "OrgOS intake cron entries already exist. Remove them first with 'crontab -e' if you want to reinstall."
  exit 0
fi

(
  echo "$CURRENT"
  echo ""
  echo "$MARKER — morning 06:00 WAT"
  echo "$CRON_MORNING"
  echo "$MARKER — evening 20:00 WAT"
  echo "$CRON_EVENING"
) | crontab -

echo ""
echo "Cron entries installed:"
echo "  Morning: $CRON_MORNING"
echo "  Evening: $CRON_EVENING"
echo ""
echo "Logs will be written to: $LOG_DIR"
echo ""
echo "To verify: crontab -l | grep OrgOS"
echo "To remove: crontab -e  (delete the two OrgOS Intake lines)"
