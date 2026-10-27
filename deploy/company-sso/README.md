# Company SSO for Harbor

Harbor authenticates through Keycloak using OIDC authorization-code flow with
PKCE. The company Keycloak brokers authentication to Feishu (`lark`) and also
supports WeChat Work. Harbor receives Keycloak tokens, not Feishu tokens.

Clicking Harbor's OIDC button can go directly to Feishu without showing the
Keycloak form. This uses Harbor's existing `oidc_extra_redirect_parms` setting;
no custom login endpoint or frontend is needed.

## Implementation

- Migration `0200_2.17.0_schema.up.sql` adds nullable
  `harbor_user.employee_number`; the model and DAO map that column.
- OIDC reads `employee_number`, `given_name` and `family_name` from userinfo,
  falling back to the ID token for missing employee attributes.
- The company realm puts the display name in `given_name` and the login account
  in `family_name`. The display-name order is `given_name`, original `name`,
  `family_name`, then username. The original name survives the manual-onboarding
  session's JSON round trip.
- First login writes the employee number. Later logins atomically fill only
  NULL or empty values; overlapping callbacks cannot overwrite an existing
  number. A failed backfill warns without blocking login.
- The existing user-data erasure operation also clears the employee number.
- OIDC admin-group membership grants session permissions via `AdminRoleInAuth`.
  It does not change `harbor_user.sysadmin_flag`.

Migration 0200 follows upstream's 0190. Renumber it before deployment if an
upstream sync takes that migration number.

## Local development

The local realm has password-based test users and **no `lark` identity provider**.
Keep `OIDC_EXTRA_REDIRECT_PARMS` unset here. Test accounts, employee numbers and
credentials are defined in `realm-wxb.json`; use that fixture rather than
copying those values into other documents or logs.

1. Start Keycloak:

   ```bash
   cd deploy/company-sso
   docker compose up -d
   docker logs harbor-sso-keycloak
   ```

   Wait for successful realm import. The issuer is
   `http://keycloak.localhost:8081/realms/wxb`. Browsers resolve `*.localhost`
   locally; Harbor resolves it using the network alias added below. Keycloak's
   H2 database lives in the container's writable layer and is reset when the
   container is recreated. This stack is for development only.

2. Build Harbor from the repository root. Stock images do not include the Go
   changes or migration:

   ```bash
   make install
   ```

   `make prepare` reads **`make/harbor.yml`**, not a root-level config file.
   Copy `make/harbor.yml.tmpl` there before installation; set the hostname to
   `localhost`, HTTP port to `8080`, and disable the HTTPS block. On macOS place
   `data_volume` and `log.local.location` under your home directory so Docker
   can mount them. Keep this gitignored config out of commits.

   If images are already built, use `make prepare start`. To rebuild using
   existing base images, use `make build BUILD_BASE=false`. A transient network
   download failure can be retried using cached layers.

3. Connect and configure:

   ```bash
   cd deploy/company-sso
   ./connect-harbor-network.sh
   ./setup-harbor-oidc.sh
   ```

   The connection script attaches Keycloak to Harbor's network as
   `keycloak.localhost`; rerunning is safe. Compose overrides are not loaded by
   `make start`, which uses an explicit Compose file.

4. Open `http://localhost:8080`, click the OIDC button, and sign in with a test
   user from the realm fixture. Check the stored attributes:

   ```bash
   docker exec harbor-db psql -U postgres -d registry \
     -c 'select user_id, username, realname, employee_number from harbor_user order by user_id;'
   ```

   Compare locally with the fixture. The admin-group account should be able to
   open user management; the other account should have no system admin menu.
   Do not use `sysadmin_flag` alone to verify OIDC admin privileges.

Harbor locks changes to `auth_mode` after ordinary local users have been added.
Configure a fresh instance before adding such users. Updating OIDC settings on
an already configured OIDC instance does not require deleting users.

## Real Feishu login from local Harbor

This needs a company-side OIDC client even though Harbor and the downstream
Keycloak run locally. Local Keycloak admin access cannot change the callback
allowlist of the existing company Feishu application or company OIDC clients.

Ask the company Keycloak administrator to register this development client:

| Setting | Value |
| --- | --- |
| Suggested client ID | `harbor-local-development` |
| Protocol | OpenID Connect |
| Client authentication | Enabled (confidential client) |
| Standard flow | Enabled |
| PKCE challenge method | S256 |
| Allowed redirect URI | `http://keycloak.localhost:8081/realms/wxb/broker/company/endpoint` |
| Scopes / user attributes | `openid profile email`; expose `employee_number` if available |
| Service accounts and direct password grants | Not required |

The administrator returns the client ID and secret through a private channel.
Set `COMPANY_OIDC_CLIENT_ID` and `COMPANY_OIDC_CLIENT_SECRET` in the shell
**environment**, then run from the repository root:

```bash
python3 deploy/company-sso/setup-local-company-broker.py
```

The script requires both values before making any changes. It configures:

- Local broker alias `company`, using the built-in Keycloak OIDC provider.
- Company authorization requests with `kc_idp_hint=lark`, signature verification
  and PKCE S256. Feishu authentication stays within the existing company broker.
- Company `employee_number` mapped to the local user attribute; upstream group
  claims do not automatically grant local admin permissions.
- Harbor's existing local issuer/client, display name `飞书`, and extra redirect
  parameter `kc_idp_hint=company`.

The resulting flow is local Harbor → local Keycloak → company Keycloak →
Feishu → company Keycloak → local Keycloak → local Harbor. The two Keycloak
servers process their respective callbacks without requiring another provider
selection. First-login profile or account-linking prompts can still appear if
company attributes are missing or a local username already exists; accounts
are not silently linked by matching email.

Open a fresh browser session at `http://localhost:8080` and use the OIDC button.
Complete the real Feishu authentication yourself, then verify your local
Harbor user profile and employee number. If the company policy disallows an
HTTP loopback callback, its administrator must approve an HTTPS development
callback before this flow can be used.

To return to local fixture login, run `./setup-harbor-oidc.sh` in this directory
with its local defaults and no extra redirect parameters. Existing linked
company users remain stored separately; no users are deleted. Removing the
local Keycloak container also removes this runtime broker configuration; rerun
the setup script after recreating it. Never commit company credentials.

Without the registered company client, real Feishu authentication from the
local application remains **unverified and unavailable**. The setup tests only
validate provisioning logic, not employee authentication.

## Company deployment: direct-to-Feishu login

No company Harbor has been deployed yet. Before using the company issuer:

1. Register Harbor as a confidential OIDC client in the company Keycloak, with
   the exact Harbor `/c/oidc/callback` HTTPS URL as its allowed redirect URI.
2. Ensure the client exposes the login claim, employee number and any required
   groups in its ID token/userinfo. Confirm `lark` is the enabled broker alias.
3. Supply Harbor admin credentials and the company OIDC client secret through
   the environment, then run:

   ```bash
   : "${HARBOR_URL:?Set the deployed Harbor HTTPS URL}"
   : "${HARBOR_ADMIN_PASSWORD:?Set the deployed Harbor admin password}"
   : "${OIDC_CLIENT_ID:?Set the registered company client ID}"
   : "${OIDC_CLIENT_SECRET:?Set the company client secret}"
   export HARBOR_URL HARBOR_ADMIN_PASSWORD OIDC_CLIENT_ID OIDC_CLIENT_SECRET
   OIDC_ENDPOINT=https://id.wangxiaobao.com/realms/wxb \
   OIDC_EXTRA_REDIRECT_PARMS='{"kc_idp_hint":"lark"}' \
   ./setup-harbor-oidc.sh
   ```

The script serializes the extra object into Harbor's string-valued
`oidc_extra_redirect_parms` field. It validates JSON and booleans before any
update, escapes quoted names/secrets, and refuses the `lark` hint against the
local test issuer. The default extra object is `{}`.

Use a fresh browser session to verify: Harbor button → Keycloak automatic
redirect → Feishu → Keycloak broker callback → Harbor callback. An existing SSO
session may return directly to Harbor. The Feishu callback belongs to
Keycloak (`/realms/wxb/broker/lark/endpoint`); Harbor's callback belongs to the
Harbor OIDC client. Register them with the respective providers.

To remove forced provider selection, run the same configuration with
`OIDC_EXTRA_REDIRECT_PARMS='{}'`. This does not delete users or change their
issuer/subject identities. Do not switch an existing instance between local
and company issuers expecting those users to be the same accounts.

The company login page also offers local credentials and WeChat Work. A broker
entry proves the authentication path; it does not prove whether a separate
employee sync exists. Feishu account disablement must be handled by the company
identity lifecycle; it does not by itself revoke existing Harbor sessions.

## Checks

```bash
python3 deploy/company-sso/test_setup_harbor_oidc.py
python3 deploy/company-sso/test_setup_local_company_broker.py
bash -n deploy/company-sso/setup-harbor-oidc.sh
bash -n deploy/company-sso/connect-harbor-network.sh
```

Backend tests need a **separate test database**, not Harbor's running database:
set `POSTGRESQL_HOST`, `POSTGRESQL_PORT`, `POSTGRESQL_USR`, `POSTGRESQL_PWD`,
`POSTGRESQL_DATABASE`, `HARBOR_ADMIN_PASSWD`, and
`POSTGRES_MIGRATION_SCRIPTS_PATH` to this checkout's `make/migrations/postgresql`.
The core controller tests also need a temporary gitignored
`src/core/conf/app.conf` (an empty file suffices). From `src/` run:

```bash
go test ./pkg/oidc/ ./pkg/user/... ./controller/user/ ./core/controllers/ -count=1
```

Verified on 2026-10-27:

- The company public `account-console` authorization request with PKCE and
  `kc_idp_hint=lark` returned 303 to the Lark broker, then 303 to Feishu. No
  Keycloak login form appeared; no employee credentials were used.
- This verifies the company's broker redirect, not a company Harbor login.
- Local password-based OIDC login, name/employee persistence, admin separation
  and sequential backfill were verified previously through a browser.
- Additional regression tests cover manual-onboarding name persistence, atomic
  stale-callback backfill, user-data erasure, and redirect-parameter handling.

## Troubleshooting and teardown

- **502 from the homepage while API ping succeeds:** compare the portal's
  current IP with the proxy's upstream error log. A recreated portal can leave
  nginx using an old address; after confirming this, reload nginx with
  `docker exec nginx nginx -s reload`.
- **Issuer mismatch:** browser and core must reach the same issuer URL; rerun
  the network connection script for the local realm.
- **Keycloak form instead of Feishu:** check that extra redirect parameters
  contain `kc_idp_hint=lark`, that the company issuer is selected, and that the
  broker alias and redirector are enabled. The local realm has no Lark broker.
- **Cookie not found during scripted local login:** use a browser for the
  local HTTP realm's secure cookies; a raw cookie-jar script may reject them.
- **Missing employee number:** verify the deployed custom core image, migration
  and IdP mapper, then sign in again.

`docker compose down` in this directory removes the disposable Keycloak
container. Harbor data is stored separately; do not remove it unless you intend
to reset the development instance.
