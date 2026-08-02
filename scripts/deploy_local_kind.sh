#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
deployment_started_at="$(date +%s)"
stage_started_at="$deployment_started_at"

begin_stage() {
  stage_started_at="$(date +%s)"
  printf '\n==> %s\n' "$1"
}

finish_stage() {
  printf '    completed in %ss\n' "$(( $(date +%s) - stage_started_at ))"
}

cluster_name="${KIND_CLUSTER_NAME:-finance-agent}"
cluster_context="kind-${cluster_name}"
image_name="${FINANCE_AGENT_IMAGE:-finance-agent:staging}"
namespace="finance-agent-staging"
local_secret_dir="${FINANCE_AGENT_LOCAL_SECRET_DIR:-${project_root}/.local}"
web_token_file="${local_secret_dir}/kind-web-access-token"
session_secret_file="${local_secret_dir}/kind-session-secret"

begin_stage "Checking WSL deployment prerequisites"
for command_name in docker kind kubectl openssl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command in WSL: ${command_name}" >&2
    exit 1
  fi
done
finish_stage

begin_stage "Preparing local bootstrap secrets and Kind cluster"
mkdir -p "$local_secret_dir"
chmod 700 "$local_secret_dir"
umask 077

if [[ ! -s "$web_token_file" ]]; then
  openssl rand -hex 24 >"$web_token_file"
fi
if [[ ! -s "$session_secret_file" ]]; then
  openssl rand -hex 32 >"$session_secret_file"
fi

if ! kind get clusters | grep -Fxq "$cluster_name"; then
  kind create cluster --name "$cluster_name" --config deploy/kind-config.yaml
fi

control_plane="${cluster_name}-control-plane"
if [[ "$(docker inspect --format '{{.State.Running}}' "$control_plane" 2>/dev/null || true)" != "true" ]]; then
  docker start "$control_plane"
fi
finish_stage

begin_stage "Waiting for Kubernetes networking and DNS"
api_ready=0
for _attempt in $(seq 1 30); do
  if kubectl --context "$cluster_context" --request-timeout=5s get nodes >/dev/null 2>&1; then
    api_ready=1
    break
  fi
  sleep 2
done
if [[ "$api_ready" != "1" ]]; then
  echo "Kubernetes API did not become ready for ${cluster_context}" >&2
  exit 1
fi
kubectl --context "$cluster_context" wait --for=condition=Ready nodes --all --timeout=120s

if ! kubectl --context "$cluster_context" --namespace kube-system wait \
  --for=condition=Ready pod --selector=k8s-app=kindnet --timeout=30s; then
  kubectl --context "$cluster_context" --namespace kube-system rollout restart daemonset/kindnet
  kubectl --context "$cluster_context" --namespace kube-system rollout status daemonset/kindnet --timeout=120s
fi
if ! kubectl --context "$cluster_context" --namespace kube-system wait \
  --for=condition=Ready pod --selector=k8s-app=kube-dns --timeout=30s; then
  kubectl --context "$cluster_context" --namespace kube-system rollout restart deployment/coredns
  kubectl --context "$cluster_context" --namespace kube-system rollout status deployment/coredns --timeout=120s
fi
finish_stage

if [[ "${SKIP_IMAGE_BUILD:-0}" != "1" ]]; then
  begin_stage "Building container image ${image_name}"
  docker build --tag "$image_name" .
  finish_stage
fi
if [[ "${SKIP_IMAGE_LOAD:-0}" != "1" ]]; then
  begin_stage "Loading container image into Kind"
  kind load docker-image --name "$cluster_name" "$image_name"
  finish_stage
fi

begin_stage "Applying declarative Kubernetes resources"
kubectl --context "$cluster_context" apply -f deploy/kubernetes/namespace.yaml
if ! kubectl --context "$cluster_context" --namespace "$namespace" \
  get secret finance-agent-runtime >/dev/null 2>&1; then
  kubectl --context "$cluster_context" create secret generic finance-agent-runtime \
    --namespace "$namespace" \
    --from-literal="AGENT_WEB_ACCESS_TOKEN=$(<"$web_token_file")" \
    --from-literal="AGENT_SESSION_SECRET=$(<"$session_secret_file")"
fi
kubectl --context "$cluster_context" apply -k deploy/kubernetes
finish_stage

begin_stage "Rolling out and verifying the application"
kubectl --context "$cluster_context" rollout restart deployment/finance-agent \
  --namespace "$namespace"
kubectl --context "$cluster_context" rollout status deployment/finance-agent \
  --namespace "$namespace" --timeout=180s

curl --fail --silent --show-error --retry 15 --retry-delay 2 \
  http://127.0.0.1:18080/health
finish_stage
echo
echo "Finance Agent Staging: http://localhost:18080/web/"
echo "Web access token: ${web_token_file}"
echo "Total deployment time: $(( $(date +%s) - deployment_started_at ))s"
