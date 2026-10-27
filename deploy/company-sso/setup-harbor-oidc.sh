#!/usr/bin/env bash
# Point a running Harbor at the company Keycloak realm.
#
# This keeps harbor.yml untouched: Harbor stores the OIDC settings in its DB
# through PUT /api/v2.0/configurations. The script is idempotent.
#
# Caveat: Harbor refuses to change auth_mode once any non-admin user exists
# ("the auth mode cannot be modified as new users have been inserted into
# database"). Run this on a fresh instance, or reset the instance first.
set -euo pipefail

HARBOR_URL="${HARBOR_URL:-http://localhost:8080}"
HARBOR_ADMIN_USER="${HARBOR_ADMIN_USER:-admin}"
HARBOR_ADMIN_PASSWORD="${HARBOR_ADMIN_PASSWORD:-Harbor12345}"

OIDC_NAME="${OIDC_NAME:-Company SSO (Keycloak)}"
OIDC_ENDPOINT="${OIDC_ENDPOINT:-http://keycloak.localhost:8081/realms/wxb}"
OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-harbor}"
OIDC_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-harbor-local-secret}"
OIDC_SCOPE="${OIDC_SCOPE:-openid,profile,email}"
OIDC_USER_CLAIM="${OIDC_USER_CLAIM:-preferred_username}"
OIDC_GROUPS_CLAIM="${OIDC_GROUPS_CLAIM:-groups}"
OIDC_ADMIN_GROUP="${OIDC_ADMIN_GROUP:-harbor-admins}"
OIDC_AUTO_ONBOARD="${OIDC_AUTO_ONBOARD:-true}"
OIDC_LOGOUT="${OIDC_LOGOUT:-true}"
# JSON object of string parameters. Set {"kc_idp_hint":"lark"} only for the company realm.
OIDC_EXTRA_REDIRECT_PARMS="${OIDC_EXTRA_REDIRECT_PARMS:-}"
export OIDC_NAME OIDC_ENDPOINT OIDC_CLIENT_ID OIDC_CLIENT_SECRET OIDC_SCOPE
export OIDC_USER_CLAIM OIDC_GROUPS_CLAIM OIDC_ADMIN_GROUP OIDC_AUTO_ONBOARD OIDC_LOGOUT
export OIDC_EXTRA_REDIRECT_PARMS

# Serialize once so quotes in names/secrets and nested redirect JSON stay valid.
payload=$(python3 - <<'PYTHON'
import json
import os
import sys
from urllib.parse import urlparse

try:
    extra = json.loads(os.environ["OIDC_EXTRA_REDIRECT_PARMS"] or "{}")
    if not isinstance(extra, dict) or any(not isinstance(v, str) for v in extra.values()):
        raise ValueError("OIDC_EXTRA_REDIRECT_PARMS must be a JSON object of strings")
    if extra.get("kc_idp_hint") == "lark" and urlparse(os.environ["OIDC_ENDPOINT"]).hostname == "keycloak.localhost":
        raise ValueError("The local test realm has no lark IdP; use the company issuer for this hint")
    payload = {"auth_mode": "oidc_auth", "oidc_verify_cert": True}
    for key in ("NAME", "ENDPOINT", "CLIENT_ID", "CLIENT_SECRET", "SCOPE", "USER_CLAIM", "GROUPS_CLAIM", "ADMIN_GROUP"):
        payload["oidc_" + key.lower()] = os.environ["OIDC_" + key]
    for key in ("AUTO_ONBOARD", "LOGOUT"):
        value = os.environ["OIDC_" + key]
        if value not in ("true", "false"):
            raise ValueError("OIDC_" + key + " must be true or false")
        payload["oidc_" + key.lower()] = value == "true"
    payload["oidc_extra_redirect_parms"] = json.dumps(extra)
except (ValueError, TypeError):
    print("Invalid OIDC settings: check redirect JSON, boolean values, and whether the issuer supports the lark IdP.", file=sys.stderr)
    sys.exit(1)
print(json.dumps(payload))
PYTHON
)

response_file=$(mktemp)
trap 'rm -f "$response_file"' EXIT

AUTH=(-u "${HARBOR_ADMIN_USER}:${HARBOR_ADMIN_PASSWORD}")

echo "==> Waiting for ${HARBOR_URL}/api/v2.0/ping"
ready=false
for _ in $(seq 1 60); do
  if curl -fsS "${AUTH[@]}" "${HARBOR_URL}/api/v2.0/ping" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 2
done
if [ "${ready}" != "true" ]; then
  echo "!! Harbor is not reachable at ${HARBOR_URL}" >&2
  exit 1
fi


echo "==> Applying OIDC configuration to ${HARBOR_URL}"
http_code=$(curl -sS -o "${response_file}" -w '%{http_code}' \
  -X PUT "${AUTH[@]}" -H 'Content-Type: application/json' \
  "${HARBOR_URL}/api/v2.0/configurations" -d "${payload}")

if [ "${http_code}" != "200" ]; then
  echo "!! Harbor rejected the update (HTTP ${http_code}):" >&2
  cat "${response_file}" >&2
  echo >&2
  echo "Hint: auth_mode can only be switched while no users except 'admin' exist." >&2
  exit 1
fi

echo "==> Current auth configuration"
curl -fsS "${AUTH[@]}" "${HARBOR_URL}/api/v2.0/configurations" | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
for key in ("auth_mode", "oidc_name", "oidc_endpoint", "oidc_client_id", "oidc_user_claim", "oidc_auto_onboard", "oidc_admin_group", "oidc_extra_redirect_parms"):
    value = (cfg.get(key) or {}).get("value")
    print(f"    {key} = {value}")
'

echo
echo "==> Done. Open ${HARBOR_URL} and click 'LOGIN VIA OIDC PROVIDER'."
echo "    Local test accounts are defined in deploy/company-sso/realm-wxb.json."
