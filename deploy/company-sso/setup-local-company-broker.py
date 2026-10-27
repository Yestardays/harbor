#!/usr/bin/env python3
"""Connect local Keycloak to the company realm after its client is registered."""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOCAL_URL = "http://keycloak.localhost:8081"
COMPANY_ISSUER = "https://id.wangxiaobao.com/realms/wxb"
ALIAS = "company"
CALLBACK = LOCAL_URL + "/realms/wxb/broker/" + ALIAS + "/endpoint"


def request(url, method="GET", body=None, token=None, form=False):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        body = (urlencode(body) if form else json.dumps(body)).encode()
    with urlopen(Request(url, data=body, headers=headers, method=method), timeout=20) as response:
        data = response.read()
        return json.loads(data) if data else None


def main():
    client_id = os.environ.get("COMPANY_OIDC_CLIENT_ID")
    client_secret = os.environ.get("COMPANY_OIDC_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("Company client registration is required before changing local settings.\n"
                 "Set COMPANY_OIDC_CLIENT_ID and COMPANY_OIDC_CLIENT_SECRET in the environment.\n"
                 "The company client's allowed redirect URI must be: " + CALLBACK)

    discovery = request(COMPANY_ISSUER + "/.well-known/openid-configuration")
    if discovery["issuer"] != COMPANY_ISSUER:
        sys.exit("Company discovery returned an unexpected issuer")
    token = request(LOCAL_URL + "/realms/master/protocol/openid-connect/token", method="POST", form=True, body={
        "client_id": "admin-cli", "grant_type": "password",
        "username": os.environ.get("KEYCLOAK_ADMIN", "admin"),
        "password": os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "admin"),
    })["access_token"]
    admin = LOCAL_URL + "/admin/realms/wxb/identity-provider/instances"
    provider = {
        "alias": ALIAS, "displayName": "飞书登录", "providerId": "keycloak-oidc",
        "enabled": True, "trustEmail": False, "storeToken": False,
        "firstBrokerLoginFlowAlias": "first broker login",
        "config": {
            "clientId": client_id, "clientSecret": client_secret,
            "clientAuthMethod": "client_secret_post",
            "authorizationUrl": discovery["authorization_endpoint"] + "?" + urlencode({"kc_idp_hint": "lark"}),
            "tokenUrl": discovery["token_endpoint"], "userInfoUrl": discovery["userinfo_endpoint"],
            "jwksUrl": discovery["jwks_uri"], "issuer": COMPANY_ISSUER,
            "useJwksUrl": "true", "validateSignature": "true",
            "pkceEnabled": "true", "pkceMethod": "S256",
            "defaultScope": "openid profile email", "syncMode": "FORCE",
        },
    }
    providers = request(admin, token=token)
    exists = any(p["alias"] == ALIAS for p in providers)
    request(admin + ("/" + ALIAS if exists else ""), method="PUT" if exists else "POST", body=provider, token=token)
    mapper_url = admin + "/" + ALIAS + "/mappers"
    mapper = {
        "name": "company-employee-number", "identityProviderAlias": ALIAS,
        "identityProviderMapper": "oidc-user-attribute-idp-mapper",
        "config": {"claim": "employee_number", "user.attribute": "employee_number", "syncMode": "FORCE"},
    }
    existing = next((m for m in request(mapper_url, token=token) if m["name"] == mapper["name"]), None)
    if existing:
        mapper["id"] = existing["id"]
    request(mapper_url + ("/" + existing["id"] if existing else ""), method="PUT" if existing else "POST", body=mapper, token=token)
    print("Local company broker configured; upstream employee groups are not granted local admin privileges automatically.")
    env = dict(os.environ, OIDC_ENDPOINT=LOCAL_URL + "/realms/wxb", OIDC_NAME="飞书",
               OIDC_CLIENT_ID="harbor", OIDC_CLIENT_SECRET="harbor-local-secret",
               OIDC_EXTRA_REDIRECT_PARMS=json.dumps({"kc_idp_hint": ALIAS}))
    subprocess.run(["bash", str(Path(__file__).with_name("setup-harbor-oidc.sh"))], env=env, check=True)


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        sys.exit("SSO setup failed with HTTP " + str(error.code) + "; verify client registration and local admin access.")
    except URLError:
        sys.exit("SSO setup could not reach Keycloak; check network connectivity.")
    except (KeyError, ValueError):
        sys.exit("SSO setup received an invalid Keycloak response.")
