import copy
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from webos_locale.client import AgentSession, DEFAULT_MANIFEST, SSAP, private_ipv4, read_key, read_manifest
from webos_locale.locale import LocaleError


class FakeSocket:
    def __init__(self, replies): self.replies, self.sent, self.closed = replies, [], False
    def send(self, text): self.sent.append(json.loads(text))
    def recv(self): return json.dumps(self.replies.pop(0))
    def settimeout(self, value): pass
    def close(self): self.closed = True


class TransportTests(unittest.TestCase):
    def test_private_lan_scope(self):
        self.assertEqual(private_ipv4("10.23.45.67"), "10.23.45.67")
        for host in ("example.com", "127.0.0.1", "8.8.8.8", "::1", "0.0.0.0"):
            with self.assertRaises(LocaleError): private_ipv4(host)

    def test_existing_pairing_and_allowlisted_launch(self):
        ws = FakeSocket([{"type": "registered"}, {"id": "launch-1", "payload": {"returnValue": True}}])
        options = []
        def connect(url, **kwargs): options.append((url, kwargs)); return ws
        client = SSAP("10.23.45.67", "SYNTHETIC_TEST_KEY", DEFAULT_MANIFEST, connect).connect()
        client.launch("com.webos.app.home")
        self.assertFalse(ws.sent[0]["payload"]["forcePairing"])
        self.assertEqual(options[0][1]["redirect_limit"], 0)
        with self.assertRaises(LocaleError): client.launch("SYNTHETIC_OTHER_APP")
        with self.assertRaises(LocaleError): client.launch("com.webos.app.home", "http://example.invalid/")
        client.close(); self.assertTrue(ws.closed)

    def test_new_pairing_is_not_accepted_or_saved(self):
        ws = FakeSocket([{"type": "response", "payload": {"pairingType": "PROMPT"}}])
        client = SSAP("10.23.45.67", "SYNTHETIC_TEST_KEY", DEFAULT_MANIFEST, lambda *a, **k: ws)
        with self.assertRaisesRegex(LocaleError, "EXISTING_PAIRING_REQUIRED"):
            client.connect()
        self.assertTrue(ws.closed)

    def test_registration_cannot_replace_existing_key(self):
        ws = FakeSocket([{"type": "registered", "payload": {"client-key": "SYNTHETIC_DIFFERENT_KEY"}}])
        with self.assertRaisesRegex(LocaleError, "EXISTING_PAIRING_KEY_CHANGED"):
            SSAP("10.23.45.67", "SYNTHETIC_TEST_KEY", DEFAULT_MANIFEST, lambda *a, **k: ws).connect()
        self.assertTrue(ws.closed)

    def test_manifest_cannot_expand_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "synthetic.json"
            manifest = copy.deepcopy(DEFAULT_MANIFEST); manifest["permissions"].append("SYNTHETIC_ADMIN")
            p.write_text(json.dumps(manifest))
            with self.assertRaises(LocaleError): read_manifest(p)
            manifest = copy.deepcopy(DEFAULT_MANIFEST); manifest["signed"] = {"permissions": ["SYNTHETIC_ADMIN"]}
            p.write_text(json.dumps(manifest))
            with self.assertRaises(LocaleError): read_manifest(p)
            p.write_text("bad key\nvalue")
            with self.assertRaises(LocaleError): read_key(p)


class ReceiverTests(unittest.TestCase):
    """Only a loopback test server; no TV or LAN connections."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = AgentSession("10.23.45.67", "SYNTHETIC_TEST_KEY", DEFAULT_MANIFEST, self.temp.name, operation="apply")
        self.session.host = "127.0.0.1"  # test-only peer for the actual HTTP handler
        self.session.page = b"synthetic-bootstrap"
        self.session.server = ThreadingHTTPServer(("127.0.0.1", 0), self.session._handler())
        self.session.thread = threading.Thread(target=self.session.server.serve_forever, daemon=True)
        self.session.thread.start()

    def tearDown(self): self.session.close(); self.temp.cleanup()

    def request(self, method, path, data=None):
        client = http.client.HTTPConnection("127.0.0.1", self.session.server.server_port, timeout=2)
        try:
            body = json.dumps(data) if data is not None else None
            client.request(method, path, body)
            response = client.getresponse()
            return response.status, response.read()
        finally: client.close()

    def test_peer_and_token_restrictions_one_use_bootstrap(self):
        token = self.session.token
        self.assertEqual(self.request("GET", "/bootstrap/wrong")[0], 404)
        self.assertEqual(self.request("GET", "/bootstrap/" + token), (200, b"synthetic-bootstrap"))
        self.assertEqual(self.request("GET", "/bootstrap/" + token)[0], 404)
        self.session.host = "10.23.45.67"
        self.assertEqual(self.request("GET", "/command/" + token)[0], 404)

    def test_event_persisted_before_ack_duplicates_and_sequence(self):
        path = "/event/" + self.session.token
        event = {"seq": 1, "name": "ready", "data": {"synthetic": True}}
        self.assertEqual(self.request("POST", path, event)[0], 200)
        self.assertEqual(json.loads((self.session.run_dir / "event-0001.private.json").read_text()), event)
        self.assertEqual(self.request("POST", path, event)[0], 200)
        self.assertEqual(len(self.session.events), 1)
        self.assertEqual(self.request("POST", path, {**event, "data": {}})[0], 400)
        self.assertEqual(self.request("POST", path, {**event, "seq": 3})[0], 400)
        self.assertEqual(self.request("POST", path, {**event, "seq": 2, "name": "arbitrary-command"})[0], 400)

    def test_single_mutation_requires_recovery_probe(self):
        with self.assertRaises(LocaleError): self.session.command("apply")
        self.session.events.append({"name": "probe-passed"})
        self.session.command("apply")
        with self.assertRaises(LocaleError): self.session.command("apply")
        with self.assertRaises(LocaleError): self.session.command("IN_STOP")

    def test_context_failure_requests_restore_and_cleanup(self):
        self.session.write_sent = True
        self.session.events.append({"name": "ready", "seq": 1})
        calls = []
        self.session.wait = lambda names, *a, **k: calls.append(names)
        self.session.__exit__(RuntimeError, None, None)
        self.assertIn({"rolled-back"}, calls)
        self.assertIn({"finished"}, calls)
        self.assertIsNone(self.session.server)


if __name__ == "__main__": unittest.main()
