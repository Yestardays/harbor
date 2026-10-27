"""Regression checks for native OAuth v2 setup without real app credentials."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

spec = importlib.util.spec_from_file_location("feishu", Path(__file__).with_name("setup-local-feishu.py"))
feishu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feishu)


class LocalFeishuTest(unittest.TestCase):
    def test_missing_credentials_stop_before_any_request(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(feishu, "HERE", Path(directory)), \
                patch.dict(os.environ, {}, clear=True), patch.object(feishu, "request") as request:
            with self.assertRaisesRegex(ValueError, "FEISHU_APP_ID"):
                feishu.main()
            request.assert_not_called()

    def test_rejected_credentials_do_not_change_keycloak(self):
        with patch.dict(os.environ, {"FEISHU_APP_ID": "cli_dummy", "FEISHU_APP_SECRET": "dummy-secret"}, clear=True), \
                patch.object(feishu, "request", return_value={"code": 10014}) as request:
            with self.assertRaisesRegex(ValueError, "Feishu rejected"):
                feishu.main()
            self.assertEqual(1, request.call_count)
            self.assertEqual("open.feishu.cn", urlparse(request.call_args.args[0]).hostname)

    def test_native_broker_mapping_and_local_harbor_configuration(self):
        writes = []
        calls = []
        profile = {"attributes": [{"name": name, "required": {"roles": ["user"]}}
                                  for name in ("firstName", "lastName", "email")]}

        def request(url, method="GET", body=None, **kwargs):
            calls.append(url)
            if url.endswith("/app_access_token/internal"):
                return {"code": 0, "app_access_token": "dummy-app-token"}
            if url.endswith("/realms/master/protocol/openid-connect/token"):
                return {"access_token": "dummy-admin-token"}
            if method != "GET":
                writes.append((url, method, body))
                return None
            if url.endswith("/identity-provider/providers/oauth2"):
                return {"id": "oauth2"}
            if url.endswith("/identity-provider/instances"):
                return [{"alias": "lark"}]
            if url.endswith("/users/profile"):
                return json.loads(json.dumps(profile))
            self.fail("Unexpected API request")

        with tempfile.TemporaryDirectory() as directory, patch.object(feishu, "HERE", Path(directory)), \
                patch.dict(os.environ, {}, clear=True), patch.object(feishu, "request", side_effect=request), \
                patch.object(feishu.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()) as output:
            credential_file = Path(directory) / ".env.feishu"
            credential_file.write_text('FEISHU_APP_ID=cli_dummy\nFEISHU_APP_SECRET="dummy-secret"\n')
            feishu.main()
            self.assertEqual(0o600, credential_file.stat().st_mode & 0o777)
            original_profile = json.loads((Path(directory) / ".runtime/user-profile-before-feishu.json").read_text())
            self.assertEqual(profile, original_profile)
        provider = writes[0][2]
        self.assertEqual("PUT", writes[0][1])
        self.assertEqual("oauth2", provider["providerId"])
        self.assertEqual("data.open_id", provider["config"]["userIDClaim"])
        self.assertEqual("data.name", provider["config"]["givenNameClaim"])
        self.assertEqual("", provider["config"]["defaultScope"])
        self.assertEqual("S256", provider["config"]["pkceMethod"])
        self.assertFalse(provider["trustEmail"])
        self.assertFalse(provider["storeToken"])
        updated_profile = writes[1][2]
        self.assertIn("required", updated_profile["attributes"][0])
        for attribute in updated_profile["attributes"][1:]:
            self.assertNotIn("required", attribute)
        env = run.call_args.kwargs["env"]
        self.assertEqual("http://keycloak.localhost:8081/realms/wxb", env["OIDC_ENDPOINT"])
        self.assertEqual({"kc_idp_hint": "lark"}, json.loads(env["OIDC_EXTRA_REDIRECT_PARMS"]))
        self.assertTrue(all(urlparse(url).hostname in ("open.feishu.cn", "keycloak.localhost") for url in calls))
        self.assertNotIn("dummy-secret", output.getvalue())
        self.assertNotIn("dummy-app-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
