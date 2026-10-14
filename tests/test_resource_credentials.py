"""Synthetic reference and filtering checks; no host credential is read."""

import json
import unittest
from unittest.mock import patch

from harness_foundry_factory.resource_credentials import (
    SecretRedactor, resolve_credentials, validate_credentials,
)


DECLARATION = {"API_TOKEN": {"ref": "env:FOUNDRY_TEST_API_TOKEN", "purpose": "测试服务认证"}}


class CredentialContractTests(unittest.TestCase):
    def test_validation_is_reference_only_and_returns_an_independent_copy(self):
        with patch("harness_foundry_factory.resource_credentials.os.environ", {}) as environment:
            normalized = validate_credentials(DECLARATION)
        self.assertEqual(environment, {})
        self.assertEqual(normalized, DECLARATION)
        normalized["API_TOKEN"]["purpose"] = "changed"
        self.assertEqual(DECLARATION["API_TOKEN"]["purpose"], "测试服务认证")
        self.assertEqual(validate_credentials({}), {})

    def test_invalid_contracts_never_echo_the_supplied_value(self):
        marker = "synthetic-secret-must-not-appear"
        bad = [None, [], {marker: DECLARATION["API_TOKEN"]},
               {"1TOKEN": DECLARATION["API_TOKEN"]}, {"api_token": DECLARATION["API_TOKEN"]},
               {"API_TOKEN": {"ref": marker, "purpose": "test"}},
               {"API_TOKEN": {"ref": "file:/tmp/token", "purpose": "test"}},
               {"API_TOKEN": {"ref": "env:NAME=value", "purpose": "test"}},
               {"API_TOKEN": {"ref": "env:1NAME", "purpose": "test"}},
               {"API_TOKEN": {"ref": "env:NAME\n", "purpose": "test"}},
               {"API_TOKEN": {"ref": "env:NAME", "purpose": " "}},
               {"API_TOKEN": {"ref": "env:NAME", "purpose": marker, "value": marker}},
               {"API_TOKEN": marker}]
        for config in bad:
            with self.subTest(config=config), self.assertRaises(ValueError) as error:
                validate_credentials(config)
            self.assertNotIn(marker, str(error.exception))

    def test_resolve_reads_only_declared_names_and_maps_only_generated_destinations(self):
        class DeclaredOnly:
            def __init__(self):
                self.reads = []

            def get(self, name):
                self.reads.append(name)
                if name != "FOUNDRY_TEST_API_TOKEN":
                    raise AssertionError("undeclared environment access")
                return "synthetic-service-token"

        source = DeclaredOnly()
        with patch("harness_foundry_factory.resource_credentials.os.environ", source):
            environment, redactor = resolve_credentials(DECLARATION)
        self.assertEqual(source.reads, ["FOUNDRY_TEST_API_TOKEN"])
        self.assertEqual(environment, {"FOUNDRY_CREDENTIAL_API_TOKEN": "synthetic-service-token"})
        self.assertEqual(redactor.text("Bearer synthetic-service-token"), "Bearer [REDACTED]")

    def test_optional_empty_config_does_not_read_environment(self):
        with patch("harness_foundry_factory.resource_credentials.os.environ", None):
            environment, redactor = resolve_credentials({})
        self.assertEqual(environment, {})
        self.assertEqual(redactor.bytes(b"unchanged"), b"unchanged")

    def test_missing_empty_and_nul_values_have_fixed_safe_errors(self):
        for value in (None, "", "synthetic-hidden\x00token"):
            with self.subTest(value=value), patch(
                    "harness_foundry_factory.resource_credentials.os.environ",
                    {} if value is None else {"FOUNDRY_TEST_API_TOKEN": value}), \
                    self.assertRaises(ValueError) as error:
                resolve_credentials(DECLARATION)
            self.assertEqual(str(error.exception),
                             "test credential unavailable for declared reference: env:FOUNDRY_TEST_API_TOKEN")
            self.assertNotIn("synthetic-hidden", str(error.exception))

    def test_each_new_resolution_uses_the_current_source_without_changing_declarations(self):
        with patch("harness_foundry_factory.resource_credentials.os.environ",
                   {"FOUNDRY_TEST_API_TOKEN": "first-synthetic-token"}):
            first, first_filter = resolve_credentials(DECLARATION)
        with patch("harness_foundry_factory.resource_credentials.os.environ",
                   {"FOUNDRY_TEST_API_TOKEN": "second-synthetic-token"}):
            second, second_filter = resolve_credentials(DECLARATION)
        self.assertNotEqual(first, second)
        self.assertEqual(first_filter.text("first-synthetic-token"), "[REDACTED]")
        self.assertEqual(second_filter.text("second-synthetic-token"), "[REDACTED]")
        self.assertEqual(DECLARATION["API_TOKEN"]["ref"], "env:FOUNDRY_TEST_API_TOKEN")


class SecretRedactorTests(unittest.TestCase):
    @staticmethod
    def streamed(redactor, chunks):
        stream = redactor.stream()
        return b"".join([*(stream.feed(chunk) for chunk in chunks), stream.finish()])

    def test_complete_values_overlap_without_leaving_a_matching_secret(self):
        redactor = SecretRedactor(["abc", "bcde", "abc", "xy"])
        self.assertEqual(redactor.text("left abcde xy right"), "left [REDACTED] [REDACTED] right")
        self.assertEqual(redactor.bytes(b"abcde"), b"[REDACTED]")
        self.assertEqual(redactor.text("ab"), "ab")  # Complete text is not a truncated stream.

    def test_stream_masks_every_possible_chunk_boundary(self):
        redactor = SecretRedactor(["synthetic-token"])
        payload = b"before synthetic-token after"
        for boundary in range(len(payload) + 1):
            with self.subTest(boundary=boundary):
                self.assertEqual(self.streamed(redactor, [payload[:boundary], payload[boundary:]]),
                                 b"before [REDACTED] after")

    def test_stream_masks_overlapping_and_adjacent_tokens_across_every_boundary(self):
        redactor = SecretRedactor(["abc", "bcde", "xy"])
        payload = b"left abcdexy right"
        for boundary in range(len(payload) + 1):
            with self.subTest(boundary=boundary):
                self.assertEqual(self.streamed(redactor, [payload[:boundary], payload[boundary:]]),
                                 b"left [REDACTED] right")
        self.assertEqual(self.streamed(redactor, [bytes([byte]) for byte in payload]),
                         b"left [REDACTED] right")

    def test_stream_tail_does_not_accumulate_long_overlapping_runs(self):
        stream = SecretRedactor(["aaa"]).stream()
        output = bytearray()
        for _ in range(100):
            output.extend(stream.feed(b"a" * 4096))
            self.assertLessEqual(len(stream._pending), 2)
        output.extend(stream.finish())
        self.assertEqual(output, b"[REDACTED]")

    def test_finish_masks_partial_prefix_even_when_output_stops_mid_token(self):
        token = b"synthetic-token"
        redactor = SecretRedactor([token.decode()])
        for size in range(1, len(token)):
            with self.subTest(size=size):
                self.assertEqual(self.streamed(redactor, [b"before ", token[:size]]),
                                 b"before [REDACTED]")
        self.assertEqual(self.streamed(redactor, [b"before unrelated"]), b"before unrelated")

    def test_utf8_secret_and_unrelated_text_survive_bytewise_chunking(self):
        redactor = SecretRedactor(["合成令牌🌱"])
        payload = "开始 合成令牌🌱 结束".encode()
        self.assertEqual(self.streamed(redactor, [bytes([byte]) for byte in payload]),
                         "开始 [REDACTED] 结束".encode())
        self.assertEqual(redactor.text("合成令牌🌱"), "[REDACTED]")

    def test_streams_keep_separate_tails_and_finish_is_idempotent(self):
        redactor = SecretRedactor(["synthetic-token"])
        first, second = redactor.stream(), redactor.stream()
        output = first.feed(b"synthetic-")
        self.assertEqual(second.feed(b"plain\n") + second.finish(), b"plain\n")
        self.assertEqual(output + first.feed(b"token") + first.finish(), b"[REDACTED]")
        self.assertEqual(first.finish(), b"")
        with self.assertRaisesRegex(ValueError, "already finished"):
            first.feed(b"later")

    def test_one_byte_secret_and_no_secret_do_not_hold_output(self):
        one = SecretRedactor(["x"]).stream()
        self.assertEqual(one.feed(b"axb"), b"a[REDACTED]b")
        self.assertEqual(one.finish(), b"")
        empty = SecretRedactor().stream()
        self.assertEqual(empty.feed(b"unchanged"), b"unchanged")
        self.assertEqual(empty.finish(), b"")

    def test_json_escape_sequences_keys_and_nested_values_are_filtered(self):
        token = '合成"token\\with\nnewline'
        redactor = SecretRedactor([token])
        payload = json.dumps({token: ["Bearer " + token, {"nested": token}], "count": 3,
                              "enabled": True, "nothing": None}, ensure_ascii=True).encode()
        cleaned = redactor.json_bytes(payload)
        self.assertIsInstance(cleaned, bytes)
        self.assertEqual(json.loads(cleaned), {"[REDACTED]": ["Bearer [REDACTED]", {"nested": "[REDACTED]"}],
                                               "count": 3, "enabled": True, "nothing": None})
        self.assertNotIn(token.encode(), cleaned)

    def test_json_top_level_string_is_filtered_and_other_scalars_remain_values(self):
        redactor = SecretRedactor(["synthetic-token"])
        self.assertEqual(json.loads(redactor.json_bytes(b'"synthetic-\\u0074oken"')), "[REDACTED]")
        for payload in (b"null", b"true", b"42", b"[1, 2]"):
            self.assertEqual(json.loads(redactor.json_bytes(payload)), json.loads(payload))

    def test_plain_attachments_that_are_json_scalars_are_filtered(self):
        for token in ("123456", "-123456", "123.456", "true", "false", "null"):
            with self.subTest(token=token):
                cleaned = SecretRedactor([token]).json_bytes((token + "\n").encode())
                self.assertEqual(json.loads(cleaned), "[REDACTED]")
                self.assertNotIn(token.encode(), cleaned)

    def test_numeric_lexemes_are_filtered_before_json_normalizes_them(self):
        for token in ("1.23456e+5", "-0", "123456789012345678901234567890", "NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                payload = ('{"value": [' + token + '], "count": 7}').encode()
                self.assertEqual(json.loads(SecretRedactor([token]).json_bytes(payload)),
                                 {"value": ["[REDACTED]"], "count": 7})

    def test_numeric_serialization_cannot_reintroduce_a_known_value(self):
        cases = (("123456.0", "1.23456e5"), ("0", "-0"), ("Infinity", "1e999"),
                 ("234", "123456"), ("234", "1.23456e5"))
        for token, lexeme in cases:
            with self.subTest(token=token, lexeme=lexeme):
                cleaned = SecretRedactor([token]).json_bytes(lexeme.encode())
                self.assertEqual(json.loads(cleaned), "[REDACTED]")
                self.assertNotIn(token.encode(), cleaned)

    def test_matching_nested_scalars_do_not_change_other_json_value_types(self):
        payload = b'{"values": [123456, true, null, false, 7, 1.5], "status": "PASS"}'
        cleaned = SecretRedactor(["123456", "true", "null"]).json_bytes(payload)
        self.assertEqual(json.loads(cleaned),
                         {"values": ["[REDACTED]", "[REDACTED]", "[REDACTED]", False, 7, 1.5],
                          "status": "PASS"})

    def test_complete_json_container_credentials_are_masked_even_before_formatting(self):
        for token in ("[123]", "{}", '{"key":true}', " [123] ", '\n{"key":true}\t'):
            with self.subTest(token=token):
                cleaned = SecretRedactor([token]).json_bytes(token.encode())
                self.assertEqual(json.loads(cleaned), "[REDACTED]")

    def test_json_container_plain_attachments_with_outer_newline_are_filtered(self):
        for token in ('{"key":true}', ' {"key":true}\t'):
            for payload in (token + "\n", "\r\n" + token + "\n"):
                with self.subTest(token=token, payload=payload):
                    cleaned = SecretRedactor([token]).json_bytes(payload.encode())
                    self.assertEqual(json.loads(cleaned), "[REDACTED]")

    def test_json_structure_matches_remaining_after_serialization_mask_the_attachment(self):
        for token, payload in (("[123]", b'{"data":[123]}'),
                               ("{}", b'{"data":{}}'),
                               ("1, 2", b'{"data":[1,2]}'),
                               ('"count": 7', b'{"count":7,"status":"PASS"}')):
            with self.subTest(token=token):
                cleaned = SecretRedactor([token]).json_bytes(payload)
                self.assertEqual(json.loads(cleaned), "[REDACTED]")
                self.assertNotIn(token.encode(), cleaned)

    def test_ordinary_string_tokens_keep_the_rest_of_the_report(self):
        payload = b'{"diagnostic":"synthetic-token","count":7,"status":"PASS"}'
        self.assertEqual(json.loads(SecretRedactor(["synthetic-token"]).json_bytes(payload)),
                         {"diagnostic": "[REDACTED]", "count": 7, "status": "PASS"})

    def test_invalid_json_or_binary_attachments_use_exact_byte_filtering(self):
        redactor = SecretRedactor(["synthetic-token"])
        for payload in (b'{"broken":synthetic-token', b"\xffsynthetic-token\x00"):
            with self.subTest(payload=payload):
                self.assertEqual(redactor.json_bytes(payload), payload.replace(b"synthetic-token", b"[REDACTED]"))

    def test_invalid_redaction_values_do_not_echo_secret_material(self):
        for value in ("", "synthetic-hidden\x00tail", None):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                SecretRedactor([value])
            self.assertNotIn("synthetic-hidden", str(error.exception))


if __name__ == "__main__":
    unittest.main()
