#!/usr/bin/env bash
set -euo pipefail

# Purpose: copy only contract-approved, non-blank external credentials into the
# local Kind runtime Secret without printing or committing their values.
if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/sync_kind_secrets.sh <external-secret-env-file>" >&2
  exit 2
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

source_file="$1"
contract_file="${project_root}/config/external-secrets.env.example"
cluster_name="${KIND_CLUSTER_NAME:-finance-agent}"
cluster_context="kind-${cluster_name}"
namespace="finance-agent-staging"
local_secret_dir="${FINANCE_AGENT_LOCAL_SECRET_DIR:-${project_root}/.local}"
web_token_file="${local_secret_dir}/kind-web-access-token"
session_secret_file="${local_secret_dir}/kind-session-secret"

for required_file in "$source_file" "$contract_file" "$web_token_file" "$session_secret_file"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Required credential input is missing: ${required_file}" >&2
    exit 1
  fi
done
for command_name in kubectl mktemp; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command in WSL: ${command_name}" >&2
    exit 1
  fi
done

declare -A allowed_keys=()
while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
  line="${raw_line%$'\r'}"
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  if [[ ! "$line" =~ ^([A-Z][A-Z0-9_]*)= ]]; then
    echo "The committed credential contract has an invalid record" >&2
    exit 1
  fi
  allowed_keys["${BASH_REMATCH[1]}"]=1
done <"$contract_file"

umask 077
temporary_env="$(mktemp "${TMPDIR:-/tmp}/finance-agent-secrets.XXXXXX")"
trap 'rm -f -- "$temporary_env"' EXIT
chmod 600 "$temporary_env"

# Purpose: bootstrap access/session secrets are generated locally and merged
# with external provider credentials into one complete runtime Secret.
printf 'AGENT_WEB_ACCESS_TOKEN=%s\n' "$(<"$web_token_file")" >>"$temporary_env"
printf 'AGENT_SESSION_SECRET=%s\n' "$(<"$session_secret_file")" >>"$temporary_env"

declare -A seen_keys=()
configured_keys=()
line_number=0
while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
  line_number=$((line_number + 1))
  line="${raw_line%$'\r'}"
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  if [[ ! "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]]; then
    echo "Invalid credential record at line ${line_number}; use KEY=VALUE" >&2
    exit 1
  fi
  key="${BASH_REMATCH[1]}"
  value="${BASH_REMATCH[2]}"
  if [[ -z "${allowed_keys[$key]:-}" ]]; then
    echo "Unknown credential key at line ${line_number}: ${key}" >&2
    exit 1
  fi
  if [[ -n "${seen_keys[$key]:-}" ]]; then
    echo "Duplicate credential key at line ${line_number}: ${key}" >&2
    exit 1
  fi
  seen_keys["$key"]=1
  if [[ "$value" =~ ^[[:space:]] || "$value" =~ [[:space:]]$ ]]; then
    echo "Credential value has leading or trailing whitespace at line ${line_number}: ${key}" >&2
    exit 1
  fi
  if (( ${#value} >= 2 )) && {
    [[ "$value" == \"*\" ]] || [[ "$value" == \'*\' ]]
  }; then
    echo "Credential values must not be wrapped in quotes at line ${line_number}: ${key}" >&2
    exit 1
  fi
  [[ -z "$value" ]] && continue
  printf '%s=%s\n' "$key" "$value" >>"$temporary_env"
  configured_keys+=("$key")
done <"$source_file"

# Purpose: apply from a protected temporary env file. The generated YAML is
# streamed directly between kubectl processes and is never written or printed.
kubectl --context "$cluster_context" apply -f deploy/kubernetes/namespace.yaml >/dev/null
kubectl --context "$cluster_context" create secret generic finance-agent-runtime \
  --namespace "$namespace" \
  --from-env-file="$temporary_env" \
  --dry-run=client \
  --output=yaml \
  | kubectl --context "$cluster_context" apply -f - >/dev/null

if (( ${#configured_keys[@]} )); then
  printf 'Kind runtime Secret synchronized. External keys: %s\n' "$(IFS=', '; echo "${configured_keys[*]}")"
else
  echo "Kind runtime Secret synchronized with bootstrap keys only."
fi
