"""Global-selection tests use explicit local receiver fixtures, never a model."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from tests.python_fixture import python_fixture_header
from unittest.mock import patch

from harness_foundry_factory.coding_defaults import resolve_codex_defaults
from harness_foundry_factory.local_process import LocalProcessError


class CodingDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.executable = self.root / "fake-codex"
        self.executable.write_text("#!/bin/sh\nexit 0\n")
        self.executable.chmod(0o700)
        self.reply = {"config": {"model": "example-model", "model_reasoning_effort": "custom-effort",
            "model_provider": None, "secret": "DO-NOT-EXPORT", "mcp_servers": {"private": {"token": "DO-NOT-EXPORT"}}},
            "origins": {"model": {"name": {"type": "user", "file": "/user/.codex/config.toml", "token": "DO-NOT-EXPORT"},
                "version": "sha256:example", "config": {"secret": "DO-NOT-EXPORT"}}}}

    def resolve(self, reply=None, **kwargs):
        with patch("harness_foundry_factory.coding_defaults._configuration_read", return_value=self.reply if reply is None else reply):
            return resolve_codex_defaults(self.executable, **kwargs)

    def test_exports_only_selection_and_source_and_keeps_unknown_legal_effort(self):
        result = self.resolve()
        self.assertEqual(set(result), {"model", "model_reasoning_effort", "model_defaults_source", "model_service"})
        self.assertEqual(result["model_service"], {"provider": "openai", "config": {}})
        self.assertEqual(result["model"], "example-model")
        self.assertEqual(result["model_reasoning_effort"], "custom-effort")
        self.assertNotIn("DO-NOT-EXPORT", json.dumps(result))
        self.assertEqual(result["model_defaults_source"]["model_turns"], 0)
        self.assertEqual(result["model_defaults_source"]["model_source"]["name"],
            {"type": "user", "file": "/user/.codex/config.toml"})

    def test_missing_default_is_not_guessed(self):
        for key in ("model", "model_reasoning_effort"):
            for value in (None, "", " ", 1, "bad\x00value"):
                with self.subTest(key=key, value=value):
                    reply = {"config": {**self.reply["config"], key: value}}
                    with self.assertRaisesRegex(LocalProcessError, "CODEX_DEFAULTS_NOT_EXPLICIT"):
                        self.resolve(reply)

    def test_custom_provider_is_not_silently_dispatched_to_openai(self):
        self.reply["config"]["model_provider"] = "private-provider"
        with self.assertRaisesRegex(LocalProcessError, "CODEX_DEFAULTS_PROVIDER_DEFINITION_MISSING"):
            self.resolve()

    def test_optional_native_nulls_are_not_invented_or_replaced(self):
        for config in ({}, {"model": None, "model_reasoning_effort": None}):
            result = self.resolve({"config": config}, require_explicit=False)
            self.assertIsNone(result["model"])
            self.assertIsNone(result["model_reasoning_effort"])
            self.assertEqual(result["model_service"], {"provider": "openai", "config": {}})
        for key in ("model", "model_reasoning_effort"):
            for value in ("", " ", 1, True, [], "bad\x00value"):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(LocalProcessError, "CODEX_DEFAULTS_NOT_EXPLICIT"):
                    self.resolve({"config": {key: value}}, require_explicit=False)

    def test_native_custom_provider_and_profile_selection_are_preserved(self):
        self.reply["config"].update(model="profile-model", model_provider="local-proxy",
            model_providers={"local-proxy": {"name": "Local proxy", "base_url": "http://127.0.0.1:15721/v1",
                "wire_api": "responses", "requires_openai_auth": True, "auth": None,
                "http_headers": None, "supports_standalone_web_search": False},
                "unused": {"experimental_bearer_token": "DO-NOT-EXPORT"}})
        self.reply["origins"]["model"] = {"name": {"type": "user", "profile": "selected"}}
        self.reply["origins"]["model_provider"] = {"name": {"type": "user", "profile": "selected"}}
        result = self.resolve()
        self.assertEqual(result["model"], "profile-model")
        self.assertEqual(result["model_service"], {"provider": "local-proxy", "config": {
            "name": "Local proxy", "base_url": "http://127.0.0.1:15721/v1", "wire_api": "responses",
            "requires_openai_auth": True}})
        self.assertEqual(result["model_defaults_source"]["provider_source"]["name"]["profile"], "selected")
        self.assertNotIn("DO-NOT-EXPORT", json.dumps(result))

    def test_invalid_selected_provider_never_falls_back(self):
        for provider, definitions in (("custom", None), ("custom", {}), ("custom", {"custom": None}),
                                      ("custom", {"custom": {}}), (12, {}), ("openai", [])):
            with self.subTest(provider=provider, definitions=definitions), self.assertRaises(LocalProcessError):
                self.resolve({"config": {**self.reply["config"], "model_provider": provider,
                                         "model_providers": definitions}})

    def test_unsupported_selected_auth_reports_no_secret_or_silent_substitution(self):
        self.reply["config"].update(model_provider="custom", model_providers={"custom": {
            "name": "Custom", "experimental_bearer_token": "DO-NOT-EXPORT"}})
        with self.assertRaises(LocalProcessError) as caught:
            self.resolve()
        self.assertNotIn("DO-NOT-EXPORT", str(caught.exception))

    def test_executable_change_during_read_does_not_bind_stale_selection(self):
        def changed(*args):
            self.executable.write_text("#!/bin/sh\nexit 1\n")
            return self.reply
        with patch("harness_foundry_factory.coding_defaults._configuration_read", side_effect=changed):
            with self.assertRaisesRegex(LocalProcessError, "CODEX_DEFAULTS_EXECUTABLE_CHANGED"):
                resolve_codex_defaults(self.executable)

    def fixture(self, mode="normal"):
        self.executable.write_text(python_fixture_header() + """
import json, os, pathlib, sys, time
root = pathlib.Path(__file__).parent
(root/'pid').write_text(str(os.getpid()))
mode = MODE
with (root/'received.jsonl').open('w') as received:
    received.write(json.dumps({'argv':sys.argv[1:], 'cwd':os.getcwd(),
        'api_key_forwarded':'OPENAI_API_KEY' in os.environ, 'home_forwarded':'CODEX_HOME' in os.environ})+'\\n')
    received.flush()
    for line in sys.stdin:
        request = json.loads(line)
        received.write(json.dumps(request)+'\\n'); received.flush()
        if request.get('method') == 'initialize':
            print(json.dumps({'id':0,'result':{'userAgent':'TEST ONLY'}}),flush=True)
        if request.get('method') == 'config/read':
            if mode == 'timeout':
                time.sleep(30)
            elif mode == 'malformed':
                print('INVALID TEST MESSAGE',flush=True)
            elif mode == 'error':
                print(json.dumps({'id':1,'error':{'code':-1,'message':'DO-NOT-EXPORT'}}),flush=True)
            else:
                print(json.dumps({'id':1,'result':REPLY}),flush=True)
""".replace("MODE", repr(mode)).replace("REPLY", repr(self.reply)))
        self.executable.chmod(0o700)

    def test_real_fixture_handshake_reads_global_config_only_no_turn_or_tools(self):
        self.fixture()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "DO-NOT-EXPORT", "CODEX_HOME": "/do-not-inherit"}):
            result = resolve_codex_defaults(self.executable)
        self.assertEqual(result["model"], "example-model")
        records = [json.loads(line) for line in (self.root / "received.jsonl").read_text().splitlines()]
        self.assertEqual([row["method"] for row in records[1:]], ["initialize", "initialized", "config/read"])
        self.assertEqual(records[-1]["params"], {"includeLayers": False})
        self.assertEqual(records[0]["cwd"], "/")
        self.assertFalse(records[0]["api_key_forwarded"])
        self.assertFalse(records[0]["home_forwarded"])
        self.assertIn("features.hooks=false", records[0]["argv"])
        self.assertIn("features.plugins=false", records[0]["argv"])
        self.assertFalse(any(value.startswith("model=") or value.startswith("model_reasoning_effort=")
            for value in records[0]["argv"]))
        self.assert_dead()

    def assert_dead(self):
        pid = int((self.root / "pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_native_failure_is_redacted_and_reader_cleaned(self):
        for mode in ("malformed", "error", "timeout"):
            with self.subTest(mode=mode):
                self.fixture(mode)
                for name in ("pid", "received.jsonl"):
                    (self.root / name).unlink(missing_ok=True)
                started = time.monotonic()
                with self.assertRaises(LocalProcessError) as caught:
                    # Allow interpreter startup before exercising the chosen
                    # failure; a startup timeout must not impersonate it.
                    resolve_codex_defaults(self.executable, timeout_seconds=2)
                self.assertNotIn("DO-NOT-EXPORT", str(caught.exception))
                self.assertLess(time.monotonic() - started, 5)
                records = [json.loads(line) for line in (self.root / "received.jsonl").read_text().splitlines()]
                self.assertEqual(records[-1]["method"], "config/read")
                self.assert_dead()

    def test_invalid_request_never_starts_native_reader(self):
        with patch("harness_foundry_factory.coding_defaults._configuration_read") as read:
            for value in (True, 0, -1, 61, float("nan")):
                with self.assertRaises(LocalProcessError):
                    resolve_codex_defaults(self.executable, timeout_seconds=value)
            with self.assertRaises(LocalProcessError):
                resolve_codex_defaults("relative-codex")
            for value in (None, 1, "false"):
                with self.assertRaises(LocalProcessError):
                    resolve_codex_defaults(self.executable, require_explicit=value)
            read.assert_not_called()
