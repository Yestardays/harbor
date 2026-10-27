"""Check local broker provisioning and its fail-before-mutation prerequisite."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

spec = importlib.util.spec_from_file_location("broker", Path(__file__).with_name("setup-local-company-broker.py"))
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


class LocalBrokerTest(unittest.TestCase):
    def test_missing_company_client_does_not_contact_or_modify_keycloak(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(broker, "request") as request:
            with self.assertRaises(SystemExit) as error:
                broker.main()
            self.assertIn(broker.CALLBACK, str(error.exception))
            request.assert_not_called()

    def test_repeated_setup_updates_owned_broker_and_mapper(self):
        writes = []

        def request(url, method="GET", body=None, **kwargs):
            if url.endswith("/.well-known/openid-configuration"):
                return dict(issuer=broker.COMPANY_ISSUER,
                            authorization_endpoint=broker.COMPANY_ISSUER + "/protocol/openid-connect/auth",
                            token_endpoint=broker.COMPANY_ISSUER + "/protocol/openid-connect/token",
                            userinfo_endpoint=broker.COMPANY_ISSUER + "/protocol/openid-connect/userinfo",
                            jwks_uri=broker.COMPANY_ISSUER + "/protocol/openid-connect/certs")
            if url.endswith("/master/protocol/openid-connect/token"):
                return {"access_token": "local-admin-test-token"}
            if method != "GET":
                writes.append((url, method, body))
                return None
            if url.endswith("/mappers"):
                return [{"name": "company-employee-number", "id": "existing-mapper"}]
            return [{"alias": "company"}]

        env = dict(COMPANY_OIDC_CLIENT_ID="development-client", COMPANY_OIDC_CLIENT_SECRET="dummy-secret")
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch.object(broker, "request", side_effect=request), \
                patch.object(broker.subprocess, "run") as run, contextlib.redirect_stdout(output):
            broker.main()
        self.assertTrue(all(method == "PUT" for _, method, _ in writes))
        provider = writes[0][2]
        config = provider["config"]
        self.assertEqual(["lark"], parse_qs(urlparse(config["authorizationUrl"]).query)["kc_idp_hint"])
        self.assertEqual("true", config["validateSignature"])
        self.assertEqual("S256", config["pkceMethod"])
        self.assertFalse(provider["trustEmail"])
        self.assertTrue(writes[1][0].endswith("/existing-mapper"))
        self.assertEqual("employee_number", writes[1][2]["config"]["user.attribute"])
        self.assertEqual('{"kc_idp_hint": "company"}', run.call_args.kwargs["env"]["OIDC_EXTRA_REDIRECT_PARMS"])
        self.assertNotIn("dummy-secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
