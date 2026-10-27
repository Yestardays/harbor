#!/usr/bin/env python3
"""Provision real Feishu login using local Keycloak's built-in OAuth v2 broker."""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
KEYCLOAK = "http://keycloak.localhost:8081"
ALIAS = "lark"
CALLBACK = KEYCLOAK + "/realms/wxb/broker/lark/endpoint"


def request(url, method="GET", body=None, token=None, form=False):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        body = (urlencode(body) if form else json.dumps(body)).encode()
    with urlopen(Request(url, data=body, headers=headers, method=method), timeout=20) as response:
        data = response.read()
        return json.loads(data) if data else None


def credentials():
    values = {}
    path = HERE / ".env.feishu"
    if path.exists():
        path.chmod(0o600)
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator:
                raise ValueError("Invalid credential file line")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET"):
        if key in os.environ:
            values[key] = os.environ[key]
        if not values.get(key) or values[key] == "暂无":
            raise ValueError("Missing " + key + "; configure .env.feishu without sharing its contents")
    return values


def main():
    values = credentials()
    # A credential check does not publish the app or request user permissions.
    result = request("https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal", method="POST", body={
        "app_id": values["FEISHU_APP_ID"], "app_secret": values["FEISHU_APP_SECRET"],
    })
    if result.get("code") != 0 or not result.get("app_access_token"):
        raise ValueError("Feishu rejected app credentials (code " + str(result.get("code")) + ")")
    print("Feishu app credentials verified; no application was published.", flush=True)

    token = request(KEYCLOAK + "/realms/master/protocol/openid-connect/token", method="POST", form=True, body={
        "client_id": "admin-cli", "grant_type": "password",
        "username": os.environ.get("KEYCLOAK_ADMIN", "admin"),
        "password": os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "admin"),
    })["access_token"]
    admin = KEYCLOAK + "/admin/realms/wxb"
    request(admin + "/identity-provider/providers/oauth2", token=token)
    provider = {
        "alias": ALIAS, "displayName": "飞书登录", "providerId": "oauth2", "enabled": True,
        "trustEmail": False, "storeToken": False, "firstBrokerLoginFlowAlias": "first broker login",
        "config": {
            "clientId": values["FEISHU_APP_ID"], "clientSecret": values["FEISHU_APP_SECRET"],
            "clientAuthMethod": "client_secret_post",
            "authorizationUrl": "https://accounts.feishu.cn/open-apis/authen/v1/authorize",
            "tokenUrl": "https://open.feishu.cn/open-apis/authen/v2/oauth/token",
            "userInfoUrl": "https://open.feishu.cn/open-apis/authen/v1/user_info",
            "userIDClaim": "data.open_id", "userNameClaim": "data.open_id",
            "givenNameClaim": "data.name", "fullNameClaim": "data.name", "emailClaim": "data.email",
            "defaultScope": "", "pkceEnabled": "true", "pkceMethod": "S256", "syncMode": "FORCE",
        },
    }
    instances = admin + "/identity-provider/instances"
    exists = any(p["alias"] == ALIAS for p in request(instances, token=token))
    request(instances + ("/" + ALIAS if exists else ""), method="PUT" if exists else "POST", body=provider, token=token)

    # Basic Feishu login does not request email; don't force users to invent one.
    profile = request(admin + "/users/profile", token=token)
    backup = HERE / ".runtime" / "user-profile-before-feishu.json"
    backup.parent.mkdir(mode=0o700, exist_ok=True)
    if not backup.exists():
        with backup.open("x") as output:
            backup.chmod(0o600)
            json.dump(profile, output)
    for attribute in profile["attributes"]:
        if attribute["name"] in ("email", "lastName"):
            attribute.pop("required", None)
    request(admin + "/users/profile", method="PUT", body=profile, token=token)

    env = dict(os.environ, HARBOR_URL="http://localhost:8080", OIDC_ENDPOINT=KEYCLOAK + "/realms/wxb",
               OIDC_NAME="飞书", OIDC_CLIENT_ID="harbor", OIDC_CLIENT_SECRET="harbor-local-secret",
               OIDC_EXTRA_REDIRECT_PARMS=json.dumps({"kc_idp_hint": ALIAS}))
    subprocess.run(["bash", str(HERE / "connect-harbor-network.sh")], check=True)
    subprocess.run(["bash", str(HERE / "setup-harbor-oidc.sh")], env=env, check=True)
    print("Local Feishu broker configured. Callback: " + CALLBACK)
    print("Open http://localhost:8080 in a fresh browser session and complete Feishu login yourself.")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        sys.exit("SSO setup failed with HTTP " + str(error.code) + "; verify Keycloak 26.8.1 and the app settings.")
    except URLError:
        sys.exit("SSO setup could not reach Keycloak or Feishu; check connectivity.")
    except (KeyError, ValueError) as error:
        sys.exit(str(error) if isinstance(error, ValueError) else "SSO setup received an invalid API response.")
