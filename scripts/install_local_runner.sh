#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TOKEN:?RUNNER_TOKEN is required}"
: "${RUNNER_VERSION:?RUNNER_VERSION is required}"
: "${RUNNER_SHA256:?RUNNER_SHA256 is required}"
: "${RUNNER_REPOSITORY_URL:?RUNNER_REPOSITORY_URL is required}"

runner_user="github-runner"
runner_root="/opt/actions-runner"
runner_archive="/tmp/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
runner_url="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
runner_name="$(hostname)-finance-agent"

if [[ "$(id -u)" != "0" ]]; then
  echo "Run this installer as root inside WSL." >&2
  exit 1
fi

if ! id "$runner_user" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$runner_user"
fi
usermod --append --groups docker "$runner_user"
install -d -o "$runner_user" -g "$runner_user" "$runner_root"
install -d -m 700 -o "$runner_user" -g "$runner_user" "/home/${runner_user}/.kube"
install -m 600 -o "$runner_user" -g "$runner_user" /root/.kube/config \
  "/home/${runner_user}/.kube/config"

if [[ ! -f "${runner_root}/.runner" ]]; then
  curl --fail --location --retry 5 --output "$runner_archive" "$runner_url"
  echo "${RUNNER_SHA256}  ${runner_archive}" | sha256sum --check --strict
  tar --extract --gzip --file "$runner_archive" --directory "$runner_root"
  chown -R "$runner_user:$runner_user" "$runner_root"
  "${runner_root}/bin/installdependencies.sh"
  runuser -u "$runner_user" -- "${runner_root}/config.sh" \
    --unattended \
    --url "$RUNNER_REPOSITORY_URL" \
    --token "$RUNNER_TOKEN" \
    --name "$runner_name" \
    --labels finance-agent-local \
    --work _work \
    --replace
fi

cd "$runner_root"
if ! systemctl list-unit-files --type=service | grep -q 'actions.runner.*finance-agent'; then
  ./svc.sh install "$runner_user"
fi
./svc.sh start
./svc.sh status
