#!/usr/bin/env bash
# check-interface-lock.sh — Cap-token primitive interface lock guard
#
# Purpose: Detects when frozen interface files are modified without a
# corresponding update to the off-chain TS consumer mirror. Exits nonzero
# if a violation is found, zero otherwise.
#
# Stage 1 SHIP gate deliverable — F62 room-admission-control M1 (S53 2026-05-25).
#
# Usage:
#   # Check staged-vs-HEAD diff (pre-commit mode):
#   bash scripts/check-interface-lock.sh --staged
#
#   # Check HEAD-vs-BASE_BRANCH diff (CI / pre-merge mode, default):
#   bash scripts/check-interface-lock.sh [--base <branch>]
#
#   # Enable verbose output:
#   INTERFACE_LOCK_VERBOSE=1 bash scripts/check-interface-lock.sh
#
# Install as a git pre-commit hook (opt-in):
#   ln -sf ../../dvconf-contracts/scripts/check-interface-lock.sh \
#          "$(git rev-parse --show-toplevel)/.git/hooks/pre-commit"
#
# Frozen files (Phase 1.1 + Phase 1.2, locked S53):
#   dvconf-contracts/sources/security/cp_quorum_sig.spec.move
#   dvconf-contracts/sources/security/capability_events.move
#   dvconf-contracts/sources/security/capability_errors.move
#
# Required co-modification (consumer file):
#   dvconf-daemons/packages/shared/src/interfaces/cp-quorum-sig.contract.ts
#
# Future frozen files (warn only — not yet created, do not block):
#   dvconf-contracts/sources/security/room_capability.move  (Phase 2.1+)

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

VERBOSE="${INTERFACE_LOCK_VERBOSE:-0}"

# Paths relative to workspace root (C:\Thesis\dvconf)
FROZEN_FILES=(
  "dvconf-contracts/sources/security/cp_quorum_sig.spec.move"
  "dvconf-contracts/sources/security/capability_events.move"
  "dvconf-contracts/sources/security/capability_errors.move"
)

# Consumer files that MUST change when any frozen file changes (block if missing)
REQUIRED_CONSUMERS=(
  "dvconf-daemons/packages/shared/src/interfaces/cp-quorum-sig.contract.ts"
)

# Future consumer files — warn only (file may not exist yet, don't block)
WARN_CONSUMERS=(
  "dvconf-contracts/sources/security/room_capability.move"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

log() { echo "[interface-lock] $*"; }
verbose() { [[ "$VERBOSE" == "1" ]] && echo "[interface-lock:verbose] $*" || true; }
error() { echo "[interface-lock] ERROR: $*" >&2; }

usage() {
  echo "Usage: $0 [--staged] [--base <branch>]"
  echo "  --staged       Compare staged changes vs HEAD (pre-commit mode)"
  echo "  --base <ref>   Compare HEAD vs this base branch/ref (default: main)"
  exit 1
}

# ── Argument parsing ──────────────────────────────────────────────────────────

MODE="ci"         # ci = HEAD vs base branch; staged = staged vs HEAD
BASE_REF="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --staged) MODE="staged"; shift ;;
    --base)   BASE_REF="${2:-main}"; shift 2 ;;
    -h|--help) usage ;;
    *) error "Unknown argument: $1"; usage ;;
  esac
done

# ── Locate workspace root ─────────────────────────────────────────────────────

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  error "Not inside a git repository. Run from within C:\\Thesis\\dvconf."
  exit 1
}
verbose "workspace root: $REPO_ROOT"
cd "$REPO_ROOT"

# ── Build changed-file list ───────────────────────────────────────────────────

if [[ "$MODE" == "staged" ]]; then
  verbose "mode: staged vs HEAD"
  CHANGED_FILES="$(git diff --cached --name-only 2>/dev/null)"
else
  verbose "mode: HEAD vs $BASE_REF"
  # If base ref doesn't exist locally, fall back to comparing last two commits
  if git rev-parse --verify "$BASE_REF" >/dev/null 2>&1; then
    CHANGED_FILES="$(git diff --name-only "$BASE_REF"...HEAD 2>/dev/null)"
  else
    verbose "base ref '$BASE_REF' not found; falling back to HEAD~1..HEAD"
    CHANGED_FILES="$(git diff --name-only HEAD~1..HEAD 2>/dev/null || echo "")"
  fi
fi

verbose "changed files:"
[[ "$VERBOSE" == "1" ]] && echo "$CHANGED_FILES" | sed 's/^/  /' || true

# ── Check: frozen file changed without consumer update ────────────────────────

VIOLATIONS=0
FROZEN_CHANGED=()

for frozen in "${FROZEN_FILES[@]}"; do
  if echo "$CHANGED_FILES" | grep -qF "$frozen"; then
    FROZEN_CHANGED+=("$frozen")
    verbose "frozen file changed: $frozen"
  fi
done

if [[ ${#FROZEN_CHANGED[@]} -eq 0 ]]; then
  verbose "no frozen files changed — interface lock not triggered"
  log "OK — no frozen interface files changed."
  exit 0
fi

log "FROZEN FILES CHANGED:"
for f in "${FROZEN_CHANGED[@]}"; do
  log "  - $f"
done

# Check required consumers
MISSING_CONSUMERS=()
for consumer in "${REQUIRED_CONSUMERS[@]}"; do
  if echo "$CHANGED_FILES" | grep -qF "$consumer"; then
    verbose "required consumer also changed: $consumer — OK"
  else
    MISSING_CONSUMERS+=("$consumer")
    error "Required consumer NOT updated: $consumer"
  fi
done

# Check warn-only consumers (future files)
for consumer in "${WARN_CONSUMERS[@]}"; do
  if [[ -f "$REPO_ROOT/$consumer" ]]; then
    if ! echo "$CHANGED_FILES" | grep -qF "$consumer"; then
      log "WARNING: future consumer exists but was not updated: $consumer"
      log "         If this is intentional, update it or document the deviation."
    fi
  else
    verbose "future consumer not yet created (skipping): $consumer"
  fi
done

# ── Verdict ───────────────────────────────────────────────────────────────────

if [[ ${#MISSING_CONSUMERS[@]} -gt 0 ]]; then
  echo ""
  error "Interface lock VIOLATION detected."
  error ""
  error "The following frozen cap-token interface files were modified:"
  for f in "${FROZEN_CHANGED[@]}"; do
    error "  - $f"
  done
  error ""
  error "But the required consumer mirror was NOT updated:"
  for c in "${MISSING_CONSUMERS[@]}"; do
    error "  - $c"
  done
  error ""
  error "Resolution:"
  error "  1. Update the TS interface to mirror any changed type/event/error-code."
  error "  2. Update the module-level docstring 'Last sync' date."
  error ""
  error "See: plans/room-admission-control/milestone-1/DECISIONS.md § D-003"
  exit 1
fi

log "OK — all frozen files have matching consumer updates."
exit 0
