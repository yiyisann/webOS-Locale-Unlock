"""Minimal SSAP launcher and a scoped HBC reverse-callback transport.

WebSocket framing belongs to websocket-client, not a vendored Root/SSAP project.
"""
from __future__ import annotations

import importlib.resources
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .locale import CONFIG_NAMES, LocaleError, validate_tag
from .storage import private_directory, write_json

PERMISSIONS = {"LAUNCH", "CLOSE", "READ_APP_STATUS", "READ_INSTALLED_APPS", "READ_RUNNING_APPS"}
DEFAULT_MANIFEST = {"manifestVersion": 1, "appVersion": "0.1.0", "appId": "org.webos.localeunlock",
                    "vendorId": "webOS Locale Unlock", "localizedAppNames": {"": "webOS Locale Unlock"},
                    "permissions": ["LAUNCH"]}
ACTIONS = {"probe", "apply", "rollback", "accept", "finish"}
EVENTS = {"audit", "ready", "probe-started", "probe-exited", "probe-passed", "recovery-write",
          "recovery-error", "rolled-back", "write-request", "write-response", "immediate-read",
          "delayed-read", "decision", "verified", "accepted", "finished", "error", "worker-error", "invariant-failed"}


def private_ipv4(host):
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        raise LocaleError("A_PRIVATE_IPV4_ADDRESS_IS_REQUIRED") from None
    networks = [ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if not any(address in n for n in networks):
        raise LocaleError("ONLY_PRIVATE_LAN_TARGETS_ARE_ALLOWED")
    return str(address)


def read_key(path):
    try:
        key = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        raise LocaleError("PAIRING_KEY_FILE_UNREADABLE") from None
    if not key or len(key) > 4096 or any(c.isspace() for c in key):
        raise LocaleError("INVALID_PAIRING_KEY_FILE")
    return key


def read_manifest(path=None):
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8")) if path else DEFAULT_MANIFEST.copy()
        permissions = manifest["permissions"]
        if not isinstance(manifest, dict) or set(manifest) - set(DEFAULT_MANIFEST):
            raise LocaleError("PAIRING_MANIFEST_FIELDS_REJECTED")
        if not isinstance(permissions, list) or not set(permissions) <= PERMISSIONS or "LAUNCH" not in permissions:
            raise LocaleError("PAIRING_MANIFEST_PERMISSION_SCOPE_REJECTED")
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        raise LocaleError("INVALID_PAIRING_MANIFEST") from None


class SSAP:
    def __init__(self, host, key, manifest, connection_factory=None):
        self.host, self.key, self.manifest = private_ipv4(host), key, manifest
        self.factory, self.ws, self.sequence = connection_factory, None, 0

    def connect(self):
        if self.factory is None:
            try:
                import websocket
            except ImportError:
                raise LocaleError("WEBSOCKET_CLIENT_DEPENDENCY_MISSING") from None
            self.factory = websocket.create_connection
        try:
            self.ws = self.factory("wss://" + self.host + ":3001", timeout=8, suppress_origin=True,
                sslopt={"cert_reqs": ssl.CERT_NONE, "check_hostname": False},
                http_no_proxy=[self.host], redirect_limit=0)
            self._send({"id": "register", "type": "register", "payload": {
                "client-key": self.key, "forcePairing": False, "pairingType": "PROMPT", "manifest": self.manifest}})
            until = time.monotonic() + 12
            while time.monotonic() < until:
                reply = self._receive(until)
                if reply.get("type") == "registered":
                    returned = reply.get("payload", {}).get("client-key", self.key)
                    if returned != self.key:
                        raise LocaleError("EXISTING_PAIRING_KEY_CHANGED")
                    return self
                if reply.get("type") == "error" or reply.get("payload", {}).get("pairingType"):
                    raise LocaleError("EXISTING_PAIRING_REQUIRED_NO_NEW_PAIRING_ACCEPTED")
            raise LocaleError("PAIRING_TIMEOUT")
        except LocaleError:
            self.close()
            raise
        except Exception:
            self.close()
            raise LocaleError("SSAP_CONNECTION_FAILED") from None

    def _send(self, data):
        self.ws.send(json.dumps(data, ensure_ascii=True))

    def _receive(self, until):
        self.ws.settimeout(max(.1, until - time.monotonic()))
        message = self.ws.recv()
        if not isinstance(message, str) or len(message) > 1000000:
            raise LocaleError("INVALID_SSAP_RESPONSE")
        result = json.loads(message)
        if not isinstance(result, dict):
            raise LocaleError("INVALID_SSAP_RESPONSE")
        return result

    def launch(self, app, url=None):
        if app not in {"com.webos.app.tinybrowser", "com.webos.app.home", "com.webos.app.quicksettings", "com.palm.app.settings"}:
            raise LocaleError("APP_NOT_ALLOWLISTED")
        self.sequence += 1
        identifier = "launch-" + str(self.sequence)
        payload = {"id": app}
        if url is not None:
            if app != "com.webos.app.tinybrowser":
                raise LocaleError("URL_ONLY_ALLOWED_FOR_BOOTSTRAP")
            payload["params"] = {"contentTarget": url}
        try:
            self._send({"id": identifier, "type": "request", "uri": "ssap://system.launcher/launch", "payload": payload})
            until = time.monotonic() + 10
            while time.monotonic() < until:
                reply = self._receive(until)
                if reply.get("id") == identifier:
                    if reply.get("type") == "error" or reply.get("payload", {}).get("returnValue") is not True:
                        raise LocaleError("APP_LAUNCH_REJECTED")
                    return
            raise LocaleError("APP_LAUNCH_TIMEOUT")
        except LocaleError:
            raise
        except Exception:
            raise LocaleError("APP_LAUNCH_FAILED") from None

    def close(self):
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None


class AgentSession:
    """A temporary LAN receiver. It serves one fixed program, never arbitrary commands."""
    def __init__(self, host, key, manifest, state_dir, *, operation="audit", target="zh-Hans-CN",
                 baseline=None, restore_locale=None, allow_stt=False, visual_seconds=600, ssap_factory=SSAP):
        if operation not in {"audit", "apply", "restore"} or not 30 <= visual_seconds <= 900:
            raise LocaleError("INVALID_OPERATION_OR_TIMEOUT")
        self.host, self.key, self.manifest = private_ipv4(host), key, manifest
        self.state_dir = private_directory(state_dir)
        self.run_dir = self.state_dir / ("session-" + secrets.token_hex(8))
        self.run_dir.mkdir(mode=0o700)
        self.operation, self.target = operation, validate_tag(target)
        self.baseline, self.restore_locale, self.allow_stt = baseline, restore_locale, allow_stt
        self.visual_seconds, self.ssap_factory = visual_seconds, ssap_factory
        self.condition = threading.Condition()
        self.events, self.command_value = [], {"id": 0, "action": "idle"}
        self.served, self.write_sent = False, False
        self.server = self.thread = self.ssap = None
        self.token = secrets.token_urlsafe(32)

    def __enter__(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect((self.host, 3001))
                local = private_ipv4(route.getsockname()[0])
            self.server = ThreadingHTTPServer((local, 0), self._handler())
            self.server.daemon_threads = True
            config = {"host": local, "port": self.server.server_port, "token": self.token,
                "operation": self.operation, "target": self.target, "baseline": self.baseline,
                "restoreLocale": self.restore_locale, "allowSTT": self.allow_stt,
                "visualSeconds": self.visual_seconds, "configNames": CONFIG_NAMES}
            source = importlib.resources.files("webos_locale").joinpath("runtime.js").read_text(encoding="utf-8")
            native = source.replace("__CONFIG__", json.dumps(config, ensure_ascii=True))
            # Config values are JSON strings, not interpolated shell fragments.
            shell = "/usr/bin/setsid /usr/bin/node - <<'WEBOS_LOCALE_MEMORY_AGENT' >/dev/null 2>&1 &\n" + native + "\nWEBOS_LOCALE_MEMORY_AGENT\n"
            encoded = json.dumps(shell, ensure_ascii=True).replace("<", "\\u003c")
            self.page = ("<!doctype html><meta charset='utf-8'><title>webOS Locale Unlock</title><body>Language audit and recovery<script>"
                "var B=window.webOSServiceBridge||window.PalmServiceBridge,b=new B();b.onservicecallback=function(){};"
                "b.call('luna://org.webosbrew.hbchannel.service/exec',JSON.stringify({command:" + encoded + "}));</script>").encode()
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.ssap = self.ssap_factory(self.host, self.key, self.manifest).connect()
            self.ssap.launch("com.webos.app.tinybrowser", f"http://{local}:{self.server.server_port}/bootstrap/{self.token}")
            return self
        except Exception:
            self.close()
            raise

    def _handler(self):
        session = self
        class Handler(BaseHTTPRequestHandler):
            def reply(self, status, data, kind="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (OSError, BrokenPipeError):
                    pass

            def do_GET(self):
                if self.client_address[0] != session.host:
                    self.reply(404, b"{}"); return
                with session.condition:
                    if self.path == "/command/" + session.token:
                        self.reply(200, json.dumps(session.command_value).encode()); return
                    if self.path == "/bootstrap/" + session.token and not session.served:
                        session.served = True
                        self.reply(200, session.page, "text/html; charset=utf-8"); return
                self.reply(404, b"{}")

            def do_POST(self):
                if self.client_address[0] != session.host or self.path != "/event/" + session.token:
                    self.reply(404, b"{}"); return
                try:
                    self.connection.settimeout(4)
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1500000:
                        raise ValueError()
                    event = json.loads(self.rfile.read(length))
                    sequence = event["seq"]
                    if type(sequence) is not int or not 1 <= sequence <= 10000 or event["name"] not in EVENTS or not isinstance(event["data"], dict):
                        raise ValueError()
                    with session.condition:
                        path = session.run_dir / f"event-{sequence:04d}.private.json"
                        if path.exists():
                            if json.loads(path.read_text(encoding="utf-8")) != event:
                                raise ValueError()
                        else:
                            if sequence != len(session.events) + 1:
                                raise ValueError()
                            write_json(path, event)
                            session.events.append(event)
                            session.condition.notify_all()
                    self.reply(200, b'{"persisted":true}')
                except (ValueError, KeyError, TypeError, OSError, LocaleError):
                    self.reply(400, b"{}")

            def log_message(self, *_):
                pass
        return Handler

    def command(self, action):
        if action not in ACTIONS or self.operation == "audit":
            raise LocaleError("INVALID_AGENT_COMMAND")
        with self.condition:
            if action == "apply":
                if self.write_sent or not any(e["name"] == "probe-passed" for e in self.events):
                    raise LocaleError("WRITE_GATE_REJECTED")
                write_json(self.run_dir / "mutation-sent.private.json", {"sent": True})
                self.write_sent = True
            self.command_value = {"id": self.command_value["id"] + 1, "action": action}

    def wait(self, names, timeout=25, *, after=0, ignore_errors=False):
        end = time.monotonic() + timeout
        with self.condition:
            while True:
                for e in self.events:
                    if e["seq"] <= after:
                        continue
                    if e["name"] in names:
                        return e
                    if not ignore_errors and e["name"] in {"error", "recovery-error", "worker-error", "invariant-failed"}:
                        raise LocaleError("AGENT_REPORTED_FAILURE")
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise LocaleError("AGENT_RESPONSE_TIMEOUT")
                self.condition.wait(min(remaining, 1))

    def launch(self, app):
        self.ssap.launch(app)

    def close(self):
        if self.ssap:
            try:
                self.ssap.launch("com.webos.app.home")
            except Exception:
                pass
            self.ssap.close()
            self.ssap = None
        if self.server:
            if self.thread:
                self.server.shutdown()
            self.server.server_close()
            if self.thread:
                self.thread.join(2)
            self.server = None

    def __exit__(self, *_):
        try:
            if self.operation != "audit" and self.events:
                names = {e["name"] for e in self.events}
                if self.write_sent and not names & {"accepted", "rolled-back"}:
                    self.command("rollback")
                    self.wait({"rolled-back"}, 40, ignore_errors=True)
                elif "probe-started" in names and "probe-passed" not in names:
                    self.wait({"probe-passed"}, 20, ignore_errors=True)
                self.command("finish")
                self.wait({"finished"}, 12, ignore_errors=True)
        finally:
            self.close()
