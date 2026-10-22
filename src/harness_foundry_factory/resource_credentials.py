"""Declared test credentials and in-memory filtering, never a secret store.

Only the native verification receiver resolves these references. Declarations
can be persisted; resolved values and redactors must remain process-local.
Known-value filtering does not prevent deliberate encoding or other disclosure.
"""

from copy import deepcopy
import json
import os
import re


_ALIAS = re.compile(r"[A-Z][A-Z0-9_]*")
_REFERENCE = re.compile(r"env:([A-Za-z_][A-Za-z0-9_]*)")
_REPLACEMENT = "[REDACTED]"


def validate_credentials(config):
    """Validate reference-only metadata without consulting the environment."""
    if not isinstance(config, dict):
        raise ValueError("credentials must be an object of named references")
    for alias, declaration in config.items():
        if not isinstance(alias, str) or _ALIAS.fullmatch(alias) is None:
            raise ValueError("credential alias must use uppercase letters, digits and underscores")
        if not isinstance(declaration, dict) or set(declaration) != {"ref", "purpose"}:
            raise ValueError("credential declaration requires only ref and purpose")
        reference = declaration["ref"]
        if not isinstance(reference, str) or _REFERENCE.fullmatch(reference) is None:
            raise ValueError("credential reference must name an explicit env source")
        purpose = declaration["purpose"]
        if not isinstance(purpose, str) or not purpose.strip():
            raise ValueError("credential purpose must be nonempty text")
    return deepcopy(config)


def resolve_credentials(config):
    """Resolve only the declared sources, returning no persistable secret data."""
    declarations = validate_credentials(config)
    environment = {}
    for alias, declaration in declarations.items():
        reference = declaration["ref"]
        value = os.environ.get(reference.removeprefix("env:"))
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError("test credential unavailable for declared reference: " + reference)
        environment["FOUNDRY_CREDENTIAL_" + alias] = value
    return environment, SecretRedactor(environment.values())


def _ranges(value, tokens):
    """Merge all matching intervals, including overlapping/adjacent secrets."""
    matches = []
    for token in tokens:
        start = value.find(token)
        while start != -1:
            matches.append((start, start + len(token)))
            start = value.find(token, start + 1)
    merged = []
    for start, end in sorted(matches):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _replace(value, tokens, replacement):
    pieces, offset = [], 0
    for start, end in _ranges(value, tokens):
        pieces.extend((value[offset:start], replacement))
        offset = end
    pieces.append(value[offset:])
    return value[:0].join(pieces)


class SecretRedactor:
    """Filter exact known values without saving values, fingerprints or files."""

    def __init__(self, values=()):
        if isinstance(values, str):
            values = (values,)
        values = tuple(values)
        if any(not isinstance(value, str) or not value or "\x00" in value for value in values):
            raise ValueError("redaction values must be nonempty text without NUL")
        self._text_tokens = tuple(sorted(set(values), key=lambda value: (-len(value), value)))
        # Match the bytes carried by an environment on this host, including
        # POSIX surrogate-escaped values; ordinary Unicode remains UTF-8 here.
        self._byte_tokens = tuple(os.fsencode(value) for value in self._text_tokens)

    def text(self, value):
        return _replace(value, self._text_tokens, _REPLACEMENT)

    def text_fragment(self, value, start, end):
        """Mask a payload slice, including secrets overlapping its boundaries."""
        pieces, offset = [], start
        for left, right in _ranges(value, self._text_tokens):
            left, right = max(left, start), min(right, end)
            if left < right:
                pieces.extend((value[offset:left], _REPLACEMENT))
                offset = right
        pieces.append(value[offset:end])
        return "".join(pieces)

    def bytes(self, value):
        return _replace(value, self._byte_tokens, _REPLACEMENT.encode("ascii"))

    def json_bytes(self, payload):
        """Filter JSON strings and scalar lexemes while keeping valid JSON."""
        def number(lexeme):
            # Preserve a match before JSON normalizes e.g. 1e2 into 100.0.
            return _REPLACEMENT if self.text(lexeme) != lexeme else json.loads(lexeme)

        try:
            decoded = json.loads(payload, parse_int=number, parse_float=number, parse_constant=number)
        except (ValueError, UnicodeError):
            return self.bytes(payload)
        # An entire attachment may itself be a declared value, including JSON
        # containers or outer whitespace that serialization would normalize.
        stripped = payload.strip(b" \t\n\r")
        if any(token in payload and stripped == token.strip(b" \t\n\r")
               for token in self._byte_tokens):
            return json.dumps(_REPLACEMENT).encode("utf-8")

        def clean(value):
            if isinstance(value, str):
                return self.text(value)
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, dict):
                return {self.text(key): clean(item) for key, item in value.items()}
            # Match booleans/null and any known value introduced by numeric
            # serialization; a string marker keeps the archive parseable.
            serialized = json.dumps(value, ensure_ascii=True)
            return _REPLACEMENT if self.text(serialized) != serialized else value

        archived = json.dumps(clean(decoded), ensure_ascii=True).encode("utf-8")
        # A value can span JSON syntax rather than a single decoded field.
        # Only this remaining match needs whole-attachment masking.
        if self.bytes(archived) != archived:
            return json.dumps(_REPLACEMENT).encode("utf-8")
        return archived

    def stream(self):
        return ByteStreamRedactor(self._byte_tokens)


class ByteStreamRedactor:
    """Keep only a possible secret tail; never expose unfiltered stream bytes.

    A parallel mask preserves overlap information when an already recognized
    secret extends into the retained tail. Redacted runs can span feeds without
    accumulating their original bytes or repeatedly emitting a marker.
    """

    def __init__(self, tokens):
        self._tokens = tuple(tokens)
        self._tail_size = max((len(token) for token in self._tokens), default=1) - 1
        self._pending = b""
        self._masked = bytearray()
        self._redacting = False
        self._finished = False

    def _emit(self, size):
        output = bytearray()
        for value, masked in zip(self._pending[:size], self._masked[:size]):
            if masked:
                if not self._redacting:
                    output.extend(_REPLACEMENT.encode("ascii"))
                self._redacting = True
            else:
                output.append(value)
                self._redacting = False
        self._pending = self._pending[size:]
        del self._masked[:size]
        return bytes(output)

    def feed(self, chunk):
        if self._finished:
            raise ValueError("redaction stream is already finished")
        self._pending += chunk
        self._masked.extend(bytes(len(chunk)))
        for start, end in _ranges(self._pending, self._tokens):
            self._masked[start:end] = b"\x01" * (end - start)
        return self._emit(max(0, len(self._pending) - self._tail_size))

    def finish(self):
        if self._finished:
            return b""
        self._finished = True
        # Interrupted output may contain only a prefix of a secret. Mask that
        # suffix too rather than exposing it when the process/pipe ends.
        for start in range(len(self._pending)):
            suffix = self._pending[start:]
            if any(token.startswith(suffix) for token in self._tokens):
                self._masked[start:] = b"\x01" * len(suffix)
                break
        return self._emit(len(self._pending))
