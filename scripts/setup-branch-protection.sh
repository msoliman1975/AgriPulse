#!/usr/bin/env bash
# Apply MissionAgre's branch-protection ruleset to `main` via the GitHub
# Rulesets API. Rulesets are the modern replacement for classic branch
# protection and work on free private repos — classic branch protection
# requires GitHub Pro / Team.
#
# Run once per repo, then any time the required-checks list changes.
# Requires `gh auth status` for an account with admin rights on the repo.
#
# Usage:
#     scripts/setup-branch-protection.sh                # apply
#     scripts/setup-branch-protection.sh --dry-run      # show payload only
#     OWNER=foo REPO=bar scripts/setup-branch-protection.sh
#
# Idempotent: if a ruleset named "$RULESET_NAME" already exists, this
# updates it in place (PUT against its ID); otherwise it creates a new
# one (POST). No-op-on-no-change is the API's responsibility.

set -euo pipefail

OWNER="${OWNER:-msoliman1975}"
REPO="${REPO:-MissionAgre}"
RULESET_NAME="${RULESET_NAME:-main-branch-protection}"
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# Required-checks list. Names must exactly match the `name:` field on
# each job in .github/workflows/ci.yml.
REQUIRED_CHECKS=(
    "pre-commit"
    "backend"
    "frontend"
    "helm"
    "infra-tf"
    "containers"
)

# Build the contexts JSON array for the required_status_checks rule.
contexts_json=""
for c in "${REQUIRED_CHECKS[@]}"; do
    contexts_json="${contexts_json}{\"context\":\"${c}\"},"
done
contexts_json="${contexts_json%,}"

PAYLOAD=$(cat <<EOF
{
    "name": "${RULESET_NAME}",
    "target": "branch",
    "enforcement": "active",
    "conditions": {
        "ref_name": {
            "include": ["~DEFAULT_BRANCH"],
            "exclude": []
        }
    },
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "required_linear_history"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews_on_push": true,
                "require_code_owner_review": true,
                "require_last_push_approval": false,
                "required_review_thread_resolution": true
            }
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": false,
                "required_status_checks": [${contexts_json}]
            }
        }
    ],
    "bypass_actors": []
}
EOF
)

echo "Repo: ${OWNER}/${REPO}"
echo "Ruleset: ${RULESET_NAME}"
echo "Required checks: ${REQUIRED_CHECKS[*]}"
echo

if [ "$DRY_RUN" -eq 1 ]; then
    echo "--- payload (dry-run) ---"
    if command -v jq >/dev/null 2>&1; then
        echo "$PAYLOAD" | jq .
    else
        echo "$PAYLOAD"
    fi
    exit 0
fi

# Look up an existing ruleset with the same name; PUT to update if found,
# POST to create otherwise.
EXISTING_ID=$(
    gh api "repos/${OWNER}/${REPO}/rulesets" \
        -H "Accept: application/vnd.github+json" \
        --jq ".[] | select(.name == \"${RULESET_NAME}\") | .id" 2>/dev/null \
        || true
)

if [ -n "${EXISTING_ID}" ]; then
    echo "Updating existing ruleset id=${EXISTING_ID}..."
    METHOD="PUT"
    URL="repos/${OWNER}/${REPO}/rulesets/${EXISTING_ID}"
else
    echo "Creating new ruleset..."
    METHOD="POST"
    URL="repos/${OWNER}/${REPO}/rulesets"
fi

echo "$PAYLOAD" | gh api \
    --method "$METHOD" \
    -H "Accept: application/vnd.github+json" \
    "$URL" \
    --input -

echo
echo "Done. Verify at:"
echo "  https://github.com/${OWNER}/${REPO}/rules"
