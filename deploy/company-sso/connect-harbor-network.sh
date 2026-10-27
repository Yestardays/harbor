#!/usr/bin/env bash
# Make the running Harbor core container resolve the Keycloak issuer host.
#
# The local realm is served at http://keycloak.localhost:8081:
#   - browsers resolve *.localhost to 127.0.0.1 (no /etc/hosts entry needed)
#   - the core container resolves the same name through the Docker alias added
#     below, so both sides see one issuer and go-oidc accepts the discovery doc
#
# `make start` runs Harbor with an explicit `-f make/docker-compose.yml`, so a
# docker-compose.override.yml is not loaded; attaching the container to Harbor's
# network is the reliable way in.
#
# Re-running is safe.
set -euo pipefail

CORE_CONTAINER="${CORE_CONTAINER:-harbor-core}"
KEYCLOAK_CONTAINER="${KEYCLOAK_CONTAINER:-harbor-sso-keycloak}"
ALIAS="${KEYCLOAK_ALIAS:-keycloak.localhost}"

if ! docker inspect "${CORE_CONTAINER}" >/dev/null 2>&1; then
  echo "!! Harbor core container '${CORE_CONTAINER}' not found. Start Harbor first." >&2
  exit 1
fi
if ! docker inspect "${KEYCLOAK_CONTAINER}" >/dev/null 2>&1; then
  echo "!! Keycloak container '${KEYCLOAK_CONTAINER}' not found. Run 'docker compose up -d' here first." >&2
  exit 1
fi

network=$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' "${CORE_CONTAINER}" | head -n1)
if [ -z "${network}" ]; then
  echo "!! Could not determine the network of ${CORE_CONTAINER}" >&2
  exit 1
fi

attached=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}};{{range $v.Aliases}}{{.}},{{end}}{{"\n"}}{{end}}' "${KEYCLOAK_CONTAINER}")

if printf '%s\n' "${attached}" | grep -q "^${network};.*${ALIAS},"; then
  echo "==> ${KEYCLOAK_CONTAINER} is already on ${network} as ${ALIAS}"
else
  # Disconnect first so a container attached without the alias is repaired.
  docker network disconnect "${network}" "${KEYCLOAK_CONTAINER}" >/dev/null 2>&1 || true
  echo "==> Attaching ${KEYCLOAK_CONTAINER} to ${network} as ${ALIAS}"
  docker network connect --alias "${ALIAS}" "${network}" "${KEYCLOAK_CONTAINER}"
fi

echo "==> Done. ${CORE_CONTAINER} can reach http://${ALIAS}:8081"
