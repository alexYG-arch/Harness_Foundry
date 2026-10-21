"""Read the native client's global model selection before preparing authority.

Only model and reasoning effort are exported. No thread, turn, tool, service
call or configuration write is requested. Codex may initialize its own local
state; this is a host preparation operation, never a model-side read grant.
"""

import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

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


def resolve_codex_defaults(executable, *, timeout_seconds=15) -> dict:
    """Return concrete global model/effort and their native source metadata.

    Missing defaults are not guessed from a catalog or from this chat. The
    caller must persist these values with the prepared scope and dispatch them
    explicitly; later user-config changes do not alter existing authorization.
    """
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
    if config.get("model_provider") not in (None, "openai"):
        raise LocalProcessError("CODEX_DEFAULTS_PROVIDER_UNSUPPORTED: only model and reasoning defaults for "
            "the existing OpenAI receiver can be selected; provider configuration is not imported")
    selected = {}
    for key in ("model", "model_reasoning_effort"):
        value = config.get(key)
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
        "config_scope": "GLOBAL", "model_turns": 0,
    }
    return selected
