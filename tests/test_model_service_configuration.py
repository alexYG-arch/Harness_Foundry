"""Provider bindings are validated locally; these tests never contact a model."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from harness_foundry_factory.coding_defaults import (
    model_service_credential_refs, validate_model_service,
)
from harness_foundry_factory.local_process import LocalProcessError


class ModelServiceConfigurationTests(unittest.TestCase):
    def service(self, **config):
        return {"provider": "local-proxy", "config": {"name": "Local proxy", **config}}

    def test_native_default_nulls_are_ignored_without_changing_input(self):
        value = self.service(base_url="http://127.0.0.1:15721/v1", wire_api="responses",
            requires_openai_auth=True, supports_websockets=False, model_catalog_url=None,
            env_key=None, env_key_instructions=None, experimental_bearer_token=None,
            auth=None, gateway_oauth=None, aws=None, capabilities=None, query_params=None,
            http_headers=None, env_http_headers=None, request_max_retries=None,
            stream_max_retries=None, stream_idle_timeout_ms=None,
            websocket_connect_timeout_ms=None, supports_standalone_web_search=False)
        original = deepcopy(value)
        result = validate_model_service(value)
        self.assertEqual(result, self.service(base_url="http://127.0.0.1:15721/v1", wire_api="responses",
            requires_openai_auth=True, supports_websockets=False))
        self.assertEqual(value, original)
        self.assertEqual(validate_model_service(result), result)

    def test_empty_native_optional_maps_are_unset(self):
        self.assertEqual(validate_model_service(self.service(http_headers={}, query_params={},
            env_http_headers={}, auth={})), self.service())
        self.assertEqual(validate_model_service({"provider": "openai", "config": {}}),
                         {"provider": "openai", "config": {}})

    def test_environment_references_are_deduplicated_without_reading_values(self):
        service = self.service(env_key="PROVIDER_TOKEN", env_http_headers={
            "X-Route": "ROUTE_CONFIG", "Authorization": "PROVIDER_TOKEN"})
        with patch.dict("os.environ", {"PROVIDER_TOKEN": "arbitrary-secret-content", "ROUTE_CONFIG": "other-secret"}):
            self.assertEqual(model_service_credential_refs(service), ["PROVIDER_TOKEN", "ROUTE_CONFIG"])
            self.assertNotIn("secret", json.dumps(validate_model_service(service)))
        normalized = validate_model_service(service)
        normalized["config"]["env_http_headers"]["X-Route"] = "CHANGED"
        self.assertEqual(service["config"]["env_http_headers"]["X-Route"], "ROUTE_CONFIG")

    def test_provider_runtime_values_preserved(self):
        value = self.service(base_url="https://gateway.example.test/deployments/a", wire_api="responses",
            env_key="TOKEN", env_key_instructions="Set TOKEN in the host environment",
            request_max_retries=0, stream_max_retries=4, stream_idle_timeout_ms=9000,
            websocket_connect_timeout_ms=0, requires_openai_auth=False, supports_websockets=True)
        self.assertEqual(validate_model_service(value), value)

    def test_static_headers_and_queries_have_explicit_secret_free_diagnostic(self):
        for config in ({"http_headers": {"Authorization": "DO-NOT-EXPORT"}},
                       {"query_params": {"key": "DO-NOT-EXPORT"}},
                       {"http_headers": {"X-Route": "public-but-not-yet-supported"}}):
            with self.subTest(config=config), self.assertRaisesRegex(LocalProcessError, "static headers and query") as caught:
                validate_model_service(self.service(**config))
            self.assertNotIn("DO-NOT-EXPORT", str(caught.exception))

    def test_unsupported_auth_and_tools_are_not_imported(self):
        for key, value in (("experimental_bearer_token", "DO-NOT-EXPORT"),
                           ("auth", {"command": "/do-not-execute"}),
                           ("aws", {"profile": "private"}),
                           ("gateway_oauth", {"client_id": "unknown"}),
                           ("model_catalog_url", "https://catalog.example.test"),
                           ("supports_standalone_web_search", True),
                           ("mcp_servers", {"private": {"token": "DO-NOT-EXPORT"}})):
            with self.subTest(key=key), self.assertRaises(LocalProcessError) as caught:
                validate_model_service(self.service(**{key: value}))
            self.assertNotIn("DO-NOT-EXPORT", str(caught.exception))

    def test_inline_url_credentials_and_invalid_urls_rejected_without_echo(self):
        for value in ("https://user:DO-NOT-EXPORT@example.test/v1", "https://example.test/v1?token=DO-NOT-EXPORT",
                      "https://example.test/v1#DO-NOT-EXPORT", "file:///tmp/provider", "https://",
                      "http://example.test:bad/v1", "https://example.test/\nDO-NOT-EXPORT"):
            with self.subTest(value=value), self.assertRaises(LocalProcessError) as caught:
                validate_model_service(self.service(base_url=value))
            self.assertNotIn("DO-NOT-EXPORT", str(caught.exception))

    def test_env_reference_shapes_and_runtime_types_are_checked(self):
        for config in ({"env_key": "BAD-NAME"}, {"env_key": 1},
                       {"env_http_headers": {"bad\nheader": "KEY"}},
                       {"env_http_headers": {"X-Route": "DO-NOT-EXPORT secret"}},
                       {"env_http_headers": []}, {"requires_openai_auth": 1},
                       {"supports_websockets": "true"}, {"request_max_retries": True},
                       {"stream_max_retries": -1}, {"stream_idle_timeout_ms": 2.5},
                       {"wire_api": ""}, {"name": "\x00"}):
            with self.subTest(config=config), self.assertRaises(LocalProcessError):
                validate_model_service(self.service(**config))

    def test_service_shape_and_empty_custom_definition_are_rejected(self):
        for value in (None, {}, {"provider": "openai"}, {"provider": "custom", "config": {}},
                      {"provider": "", "config": {}}, {"provider": "a.b", "config": {}},
                      {"provider": "openai", "config": [], "extra": True}):
            with self.subTest(value=value), self.assertRaises(LocalProcessError):
                validate_model_service(value)
