/*
Company SSO (Keycloak OIDC): record the employee number claimed by the
identity provider on the user row.

Mirrors the `employee_number` column the Multica fork added to its `user`
table. It is written on the first OIDC login and backfilled on later logins,
but never overwritten once a value exists. NULL means the user was not created
through the company IdP, or the IdP has no `employee_number` mapper yet.
*/
ALTER TABLE harbor_user ADD COLUMN IF NOT EXISTS employee_number text;
