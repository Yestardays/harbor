"""Exercise the deployment script against a local Harbor API stub."""
import json
import os
from pathlib import Path
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class SetupOIDCTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                cfg = {k: {"value": v} for k, v in requests[-1].items()} if requests else {}
                self.wfile.write(json.dumps(cfg).encode())

            def do_PUT(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("OIDC_", "HARBOR_"))}
        self.env["HARBOR_URL"] = "http://127.0.0.1:" + str(self.server.server_port)

    def run_script(self, **settings):
        return subprocess.run(
            ["bash", str(Path(__file__).with_name("setup-harbor-oidc.sh"))],
            env={**self.env, **settings}, capture_output=True, text=True, timeout=10,
        )

    def test_local_default_does_not_select_lark(self):
        result = self.run_script()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({}, json.loads(self.requests[-1]["oidc_extra_redirect_parms"]))

    def test_company_hint_and_quoted_values(self):
        secret = 'dummy-secret-with-"quotes"-and-\\slashes'
        result = self.run_script(
            OIDC_ENDPOINT="https://id.wangxiaobao.com/realms/wxb",
            OIDC_EXTRA_REDIRECT_PARMS='{"kc_idp_hint":"lark"}',
            OIDC_NAME='Company "SSO"', OIDC_CLIENT_SECRET=secret,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"kc_idp_hint": "lark"}, json.loads(self.requests[-1]["oidc_extra_redirect_parms"]))
        self.assertEqual(secret, self.requests[-1]["oidc_client_secret"])
        self.assertEqual('Company "SSO"', self.requests[-1]["oidc_name"])
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_invalid_settings_are_rejected_before_update(self):
        for settings in (
            {"OIDC_EXTRA_REDIRECT_PARMS": '{"kc_idp_hint":"lark"}'},
            {"OIDC_EXTRA_REDIRECT_PARMS": "invalid-json"},
            {"OIDC_EXTRA_REDIRECT_PARMS": "[]"},
            {"OIDC_EXTRA_REDIRECT_PARMS": '{"kc_idp_hint":123}'},
            {"OIDC_AUTO_ONBOARD": "not-a-boolean"},
        ):
            with self.subTest(settings=settings):
                result = self.run_script(**settings)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], self.requests)


if __name__ == "__main__":
    unittest.main()
