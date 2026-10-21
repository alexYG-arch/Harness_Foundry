"""Read the native client's global model selection before preparing authority.

Only model, reasoning effort and a supported service definition are exported.
No thread, turn, tool, service call or configuration write is requested. Codex may initialize its own local
state; this is a host preparation operation, never a model-side read grant.
"""

import hashlib
import json
import os
import re
from pathlib import Path
import selectors
import signal
import subprocess
import time
from urllib.parse import urlsplit

from .coding_process import DISABLED_FEATURES
from .local_process import CodexSandboxRunner, LocalProcessError


def _configuration_read(executable: Path, timeout_seconds: float) -> dict:
    # Start outside any project, and omit config/read.cwd. Do not overwrite
    # model/provider/effort while reading them. Disabled features only affect
    # this short-lived config reader, not the user's saved configuration.
    argv = [str(executable), "app-server", "--stdio", "-c", "analytics.enabled=false"]
    for feature in DISABLED_FEATURES:
        argv.extend(["-c", "features." + feature + "=false"])
    selector = selectors.DefaultSelector()
    process = None
    pending = b""
    deadline = time.monotonic() + timeout_seconds
    total_bytes = 0

    def send(value):
        process.stdin.write((json.dumps(value) + "\n").encode("utf-8"))
        process.stdin.flush()

    def response(identifier):
        nonlocal pending, total_bytes
        while True:
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                value = json.loads(line)
                if isinstance(value, dict) and value.get("id") == identifier:
                    if "error" in value or not isinstance(value.get("result"), dict):
                        raise LocalProcessError("CODEX_DEFAULTS_READ_FAILED: native configuration request failed")
                    return value["result"]
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise LocalProcessError("CODEX_DEFAULTS_READ_FAILED: native configuration read timed out")
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise LocalProcessError("CODEX_DEFAULTS_READ_FAILED: native configuration reader exited before replying")
            total_bytes += len(chunk)
            if total_bytes > 8 * 1024 * 1024:
                raise LocalProcessError("CODEX_DEFAULTS_READ_FAILED: native configuration response exceeded the read limit")
            pending += chunk

    try:
        process = subprocess.Popen(argv, cwd="/", env=CodexSandboxRunner._environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True)
        selector.register(process.stdout, selectors.EVENT_READ)
        send({"id": 0, "method": "initialize", "params": {
            "clientInfo": {"name": "foundry_config_read", "version": "2.9"}}})
        response(0)
        send({"method": "initialized"})
        send({"id": 1, "method": "config/read", "params": {"includeLayers": False}})
        return response(1)
    except LocalProcessError:
        raise
    except (OSError, ValueError) as exc:
        # Native error messages may quote arbitrary configuration or secrets.
        raise LocalProcessError("CODEX_DEFAULTS_READ_FAILED: cannot read native global configuration; "
            "check the bound Codex executable and host access, or prepare explicit model and reasoning values") from exc
    finally:
        selector.close()
        if process is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                # Only our newly-created reader process group, never a saved PID.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            process.stdout.close()


def _selection_origin(value):
    if not isinstance(value, dict):
        return None
    source = value.get("name")
    if not isinstance(source, dict):
        return None
    # Keep only public source identity, never the config/layer contents.
    name = {key: source[key] for key in ("type", "file", "profile")
            if isinstance(source.get(key), str)}
    result = {"name": name}
    if isinstance(value.get("version"), str):
        result["version"] = value["version"]
    return result


_SERVICE_TEXT_FIELDS = {"name", "base_url", "wire_api", "env_key", "env_key_instructions"}
_SERVICE_BOOLEAN_FIELDS = {"requires_openai_auth", "supports_websockets"}
_SERVICE_COUNT_FIELDS = {"request_max_retries", "stream_max_retries", "stream_idle_timeout_ms",
                         "websocket_connect_timeout_ms"}
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def validate_model_service(value) -> dict:
    """Normalize a supported, non-secret provider binding without loading it.

    Credential values and command-backed authentication are never copied into
    authority or command records. Static headers/query parameters are not yet
    supported; headers can instead name explicit environment references.
    """
    def invalid(message):
        raise LocalProcessError("CODEX_MODEL_SERVICE_INVALID: " + message)

    if not isinstance(value, dict) or set(value) != {"provider", "config"}:
        invalid("service must contain provider and config")
    provider, config = value["provider"], value["config"]
    if not isinstance(provider, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", provider):
        invalid("provider must be a supported nonempty identifier")
    if not isinstance(config, dict):
        invalid("provider config must be an object")
    # Native config/read emits unset fields as null, including optional auth
    # methods this receiver deliberately does not execute.
    config = {key: item for key, item in config.items() if item is not None and item != {}}
    for key in ("http_headers", "query_params"):
        if key in config:
            invalid("static headers and query parameters are not supported; use env_http_headers for header values")
    # This default advertises no extra capability and need not be copied into
    # our already web-disabled receiver. A true value needs separate support.
    if config.get("supports_standalone_web_search") is False:
        config.pop("supports_standalone_web_search")
    allowed = _SERVICE_TEXT_FIELDS | _SERVICE_BOOLEAN_FIELDS | _SERVICE_COUNT_FIELDS | {"env_http_headers"}
    if set(config) - allowed:
        invalid("provider has unsupported fields; use native authentication or explicit environment references")
    normalized = {}
    for key, item in config.items():
        if key in _SERVICE_TEXT_FIELDS:
            if not isinstance(item, str) or not item.strip() or any(ord(c) < 32 or ord(c) == 127 for c in item):
                invalid("provider text fields must be nonempty strings without control characters")
        elif key in _SERVICE_BOOLEAN_FIELDS:
            if type(item) is not bool:
                invalid("provider authentication and websocket flags must be booleans")
        elif key in _SERVICE_COUNT_FIELDS:
            if type(item) is not int or item < 0:
                invalid("provider retry and timeout values must be nonnegative integers")
        elif key == "env_http_headers":
            if not isinstance(item, dict) or any(
                not isinstance(header, str) or not _HEADER_NAME.fullmatch(header)
                or not isinstance(name, str) or not _ENVIRONMENT_NAME.fullmatch(name)
                for header, name in item.items()
            ):
                invalid("provider header values must reference environment variable names")
            item = dict(item)
        normalized[key] = item
    if "env_key" in normalized and not _ENVIRONMENT_NAME.fullmatch(normalized["env_key"]):
        invalid("env_key must reference an environment variable name")
    if "base_url" in normalized:
        try:
            url = urlsplit(normalized["base_url"])
            valid = url.scheme in {"https", "http"} and url.hostname and not (
                url.username or url.password or url.query or url.fragment)
            url.port  # Invalid port syntax must fail before any model dispatch.
        except (TypeError, ValueError):
            valid = False
        if not valid:
            invalid("base_url must be HTTP(S) without inline credentials, query parameters or fragments")
    if provider != "openai" and not normalized:
        invalid("custom provider requires a native definition; it cannot fall back to OpenAI")
    return {"provider": provider, "config": normalized}


def model_service_credential_refs(value) -> list[str]:
    """Return only the declared environment names; never read their values."""
    config = validate_model_service(value)["config"]
    references = set(config.get("env_http_headers", {}).values())
    if "env_key" in config:
        references.add(config["env_key"])
    return sorted(references)


def _selected_model_service(config):
    provider = config.get("model_provider")
    if provider is None:
        provider = "openai"  # The native receiver's built-in provider, not a custom fallback.
    providers = config.get("model_providers")
    if providers is None:
        providers = {}
    if not isinstance(providers, dict):
        raise LocalProcessError("CODEX_MODEL_SERVICE_INVALID: native provider definitions must be an object")
    if not isinstance(provider, str):
        raise LocalProcessError("CODEX_MODEL_SERVICE_INVALID: native provider identifier must be a string")
    if provider not in providers and provider != "openai":
        raise LocalProcessError("CODEX_DEFAULTS_PROVIDER_DEFINITION_MISSING: native configuration lacks the "
            "selected provider definition; select a supported service before preparing authority")
    return validate_model_service({"provider": provider, "config": providers.get(provider, {})})


def resolve_codex_defaults(executable, *, timeout_seconds=15, require_explicit=True) -> dict:
    """Read model/effort, the selected service and native source metadata.

    Missing defaults are never guessed. The normal preparation route requires
    concrete values. An explicitly dynamic policy may use require_explicit=False
    to retain native null selections; it must still bind and check the service.
    This helper does not grant authority or contact the model service.
    """
    if type(require_explicit) is not bool:
        raise LocalProcessError("CODEX_DEFAULTS_READ_FAILED: require_explicit must be a boolean")
    path = Path(executable)
    if (os.name != "posix" or not path.is_absolute() or not path.is_file()
            or not os.access(path, os.X_OK)):
        raise LocalProcessError("CODEX_DEFAULTS_READ_FAILED: an absolute executable Codex path on POSIX is required")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 60:
        raise LocalProcessError("CODEX_DEFAULTS_READ_FAILED: configuration read timeout must be positive and at most 60 seconds")
    path = path.resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = _configuration_read(path, timeout_seconds)
    config = result.get("config")
    if not isinstance(config, dict):
        raise LocalProcessError("CODEX_DEFAULTS_READ_FAILED: native reply lacks effective configuration")
    selected = {"model_service": _selected_model_service(config)}
    for key in ("model", "model_reasoning_effort"):
        value = config.get(key)
        if value is None and not require_explicit:
            selected[key] = None
            continue
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise LocalProcessError("CODEX_DEFAULTS_NOT_EXPLICIT: native global configuration has no concrete "
                + key + "; set that Codex default or prepare explicit model and reasoning values")
        selected[key] = value
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise LocalProcessError("CODEX_DEFAULTS_EXECUTABLE_CHANGED: Codex changed during configuration read; prepare again")
    origins = result.get("origins")
    if not isinstance(origins, dict):
        origins = {}
    selected["model_defaults_source"] = {
        "method": "CODEX_CONFIG_READ", "codex_executable": str(path), "codex_sha256": digest,
        "model_source": _selection_origin(origins.get("model")),
        "reasoning_source": _selection_origin(origins.get("model_reasoning_effort")),
        "provider_source": _selection_origin(origins.get("model_provider")),
        "config_scope": "GLOBAL", "model_turns": 0,
    }
    return selected
