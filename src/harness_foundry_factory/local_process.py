"""Local command receiver using Codex's supported permission-profile interface.

This receiver is not an authorizer or a model client. Its caller must resolve
the current Job leases and authorize the resulting local paths first. No shell,
profile file, global configuration mutation or unsandboxed fallback is used.
"""

from __future__ import annotations

from dataclasses import dataclass
import codecs
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Sequence
from uuid import uuid4


class LocalProcessError(ValueError):
    """Invalid command or unavailable receiver, before workload dispatch."""


def unsupported_isolation_paths(paths) -> list[str]:
    """Current macOS receiver does not enforce readonly protection in shared /tmp.

    Native offline checks observed writes even with explicit read/deny rules.
    Reject that layout instead of treating a successful sandbox launch as proof.
    This restriction does not grant reads/writes or change global Codex settings.
    """
    if sys.platform != "darwin":
        return []
    shared = Path("/tmp").resolve()
    return sorted({str(path) for value in paths if (path := Path(value).resolve()).is_relative_to(shared)})


def _path(value: str | Path, *, directory: bool = False) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise LocalProcessError("local command paths must be absolute, without traversal")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise LocalProcessError(f"local command path is unavailable: {path}") from exc
    if directory and not resolved.is_dir():
        raise LocalProcessError("cwd must be an existing directory")
    if not (resolved.is_file() or resolved.is_dir()):
        raise LocalProcessError("scope must name a regular file or directory")
    return resolved


def _within(path: Path, roots: Sequence[Path]) -> bool:
    return any(path == root or root.is_dir() and path.is_relative_to(root) for root in roots)


@dataclass(frozen=True)
class LocalCommand:
    """Already authorized, hydrated command; writes imply reads.

    Platform runtime reads come from Codex's documented :minimal baseline.
    Additional interpreter/library/model reads must be declared explicitly.
    Writable temp/cache directories are not added implicitly.
    """

    argv: tuple[str, ...]
    cwd: Path
    read_roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]
    timeout_seconds: float = 60

    @classmethod
    def prepare(cls, *, argv: Sequence[str], cwd: str | Path,
                read_roots: Sequence[str | Path], write_roots: Sequence[str | Path],
                timeout_seconds: float = 60) -> LocalCommand:
        if (not isinstance(argv, (list, tuple)) or not argv
                or any(not isinstance(arg, str) or "\x00" in arg for arg in argv)):
            raise LocalProcessError("argv must contain strings, without NUL bytes")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 86400):
            raise LocalProcessError("timeout must be finite, positive and at most one day")
        executable = _path(argv[0])
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise LocalProcessError("argv[0] must be an executable regular file")
        reads = tuple(_path(root) for root in read_roots)
        writes = tuple(_path(root) for root in write_roots)
        workdir = _path(cwd, directory=True)
        if unsupported_isolation_paths([workdir, executable, *reads, *writes]):
            raise LocalProcessError("SHARED_TEMP_ISOLATION_UNSUPPORTED: on macOS use a verified non-shared directory, not /tmp")
        if not _within(workdir, reads + writes) or not _within(executable, reads + writes):
            raise LocalProcessError("cwd and executable must be covered by explicit local reads")
        # Preserve argv[0]: resolving a venv's Python symlink here would change
        # interpreter environment selection even though the binary is the same.
        return cls(tuple(argv), workdir, reads, writes, float(timeout_seconds))

    def permission_profile(self) -> dict[str, Any]:
        filesystem = {":minimal": "read"}
        filesystem.update({str(root): "read" for root in self.read_roots})
        filesystem.update({str(root): "write" for root in self.write_roots})
        # Match the baseline metadata protection when granting an explicit
        # directory rather than using a broad :workspace permission profile.
        for root in self.write_roots:
            if root.is_dir():
                for name in (".git", ".codex", ".agents"):
                    filesystem[str(root / name)] = "read"
        return {"filesystem": filesystem, "network": {"enabled": False}}


def _toml_inline(value: Any) -> str:
    """Serialize the small documented permission-profile table, without a file."""
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + "=" + _toml_inline(item)
                              for key, item in value.items()) + "}"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


class CodexSandboxRunner:
    """Run offline local tools through Codex, not `codex exec` / a model.

    The flat `codex sandbox -P ...` CLI is checked, not assumed from an older
    `sandbox macos` example. Hosts that cannot apply it return a failure before
    the workload. Temporary output files belong to this receiver, not the Job.
    """

    def __init__(self, executable: str | Path, *, output_limit_bytes: int = 65536,
                 stream_limit_bytes: int = 128 * 1024 * 1024):
        self.executable = _path(executable)
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise LocalProcessError("Codex sandbox receiver is not executable")
        if not isinstance(output_limit_bytes, int) or isinstance(output_limit_bytes, bool) or output_limit_bytes < 1:
            raise LocalProcessError("output limit must be a positive integer")
        self.output_limit_bytes = output_limit_bytes
        if type(stream_limit_bytes) is not int or stream_limit_bytes < 1:
            raise LocalProcessError("stream limit must be a positive integer")
        self.stream_limit_bytes = stream_limit_bytes

    @staticmethod
    def _environment() -> dict[str, str]:
        # Do not forward API keys, Python startup hooks or inherited proxy URLs.
        # HOME is left to the OS; never redirect Codex's own configuration home.
        return {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}

    def _capture(self, argv: list[str], cwd: Path, timeout: float, *, output_limit: int | None = None,
                 stdin_bytes: bytes | None = None, on_stdout=None, on_started=None,
                 stream_sink=None, on_capture=None, cancellation_reason=None) -> dict[str, Any]:
        limit = self.output_limit_bytes if output_limit is None else output_limit
        previews = {name: bytearray() for name in ("stdout", "stderr")}
        counts = dict.fromkeys(previews, 0)
        capture_error = None
        with tempfile.TemporaryFile() as source, selectors.DefaultSelector() as selector:
            if stdin_bytes is not None:
                source.write(stdin_bytes)
                source.seek(0)
            try:
                process = subprocess.Popen(argv, cwd=cwd, stdin=source if stdin_bytes is not None else subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                           start_new_session=True, env=self._environment())
            except OSError as exc:
                return {"exit_code": None, "timed_out": False, "stdout": "",
                        "stderr": str(exc), "output_truncated": False, "process_started": False}
            timed_out = False
            cancelled = None
            next_authority_check = 0
            deadline = time.monotonic() + timeout
            killed_at = None

            def kill_group():
                nonlocal killed_at
                if killed_at is None:
                    killed_at = time.monotonic()
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            try:
                for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                if on_started is not None:
                    on_started(process.pid)
                # A command may close both output streams and keep working.
                # Continue polling authority and timeout until the process ends.
                while selector.get_map() or process.poll() is None:
                    now = time.monotonic()
                    if process.poll() is not None:
                        kill_group()  # Finite commands cannot leave background writers.
                    elif now >= deadline:
                        timed_out = True
                        kill_group()
                    elif killed_at is None and cancellation_reason is not None and now >= next_authority_check:
                        next_authority_check = now + 0.25
                        try:
                            cancelled = cancellation_reason()
                        except Exception as exc:
                            cancelled = "AUTHORIZATION_MONITOR_FAILED"
                            capture_error = cancelled + ": " + str(exc)[:1000]
                        if cancelled:
                            # Only this live Popen's owned group, never a PID
                            # reconstructed from a previous host's records.
                            kill_group()
                    if killed_at is not None and now - killed_at > 1:
                        capture_error = capture_error or "OUTPUT_PIPE_DID_NOT_CLOSE"
                        break
                    for key, _ in selector.select(timeout=0.05):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        name = key.data
                        counts[name] += len(chunk)
                        previews[name].extend(chunk[:max(0, limit - len(previews[name]))])
                        if sum(counts.values()) > self.stream_limit_bytes:
                            capture_error = "PROCESS_STREAM_LIMIT_EXCEEDED"
                            kill_group()
                        if capture_error is None:
                            if stream_sink is not None:
                                stream_sink(name, chunk)
                            if name == "stdout" and on_stdout is not None:
                                on_stdout(chunk)
            except Exception as exc:
                capture_error = "PROCESS_CAPTURE_FAILED: " + str(exc)[:1000]
            finally:
                # Clean up this command's process group, including on normal
                # exit. Detached daemons/new sessions are not supported by this
                # finite-command receiver. Do not kill by executable name.
                kill_group()
                process.wait()
                process.stdout.close()
                process.stderr.close()
            captured = {}
            encoding_error = False
            for name, data in previews.items():
                clipped = counts[name] > limit
                captured[name + "_truncated"] = clipped
                try:
                    captured[name] = codecs.getincrementaldecoder("utf-8")().decode(bytes(data), final=not clipped)
                except UnicodeDecodeError:
                    encoding_error = True
                    captured[name] = bytes(data).decode("utf-8", errors="replace")
            result = {"exit_code": process.returncode, "timed_out": timed_out,
                    "output_truncated": any(counts[name] > limit for name in counts),
                    "stream_bytes": counts, "capture_error": capture_error,
                    **({"cancellation_reason": cancelled} if cancelled else {}),
                    **({"encoding_error": True} if encoding_error else {}), **captured}
            if on_capture is not None:
                try:
                    on_capture(result)
                except Exception as exc:
                    result["capture_error"] = "CAPTURE_PERSISTENCE_FAILED: " + str(exc)[:1000]
            return result

    def run(self, command: LocalCommand, *, before_dispatch: Callable[[], None] | None = None,
            observation=None, cancellation_reason=None) -> dict[str, Any]:
        if os.name != "posix":
            raise LocalProcessError("this receiver currently supports POSIX process groups only")
        # Revalidate paths at dispatch, even when preparation occurred earlier.
        prepared = LocalCommand.prepare(argv=command.argv, cwd=command.cwd,
                                        read_roots=command.read_roots, write_roots=command.write_roots,
                                        timeout_seconds=command.timeout_seconds)
        if prepared != command:
            raise LocalProcessError("local command paths changed since preparation")
        help_result = self._capture([str(self.executable), "sandbox", "--help"], command.cwd, 15,
                                    output_limit=65536)
        help_text = help_result["stdout"] + help_result["stderr"]
        if (help_result["exit_code"] != 0 or help_result["timed_out"]
                or "--permission-profile" not in help_text
                or "--include-managed-config" not in help_text
                or "--cd" not in help_text
                or "[COMMAND]" not in help_text):
            return self._result(help_result, "SANDBOX_INTERFACE_UNAVAILABLE", workload_started=False)
        # A fresh profile avoids accidentally extending a user's named profile.
        # Managed restrictions still apply; never retry without the profile.
        name = "foundry_" + uuid4().hex
        prefix = [str(self.executable), "sandbox", "--permission-profile", name,
                  "--include-managed-config", "-c", "permissions." + name + "=" +
                  _toml_inline(command.permission_profile()), "--cd", str(command.cwd), "--"]
        # Check the exact receiver policy before dispatching a side effect. This
        # is capability evidence only; the workload's exit status is separate.
        probe = self._capture(prefix + ["/usr/bin/true"], command.cwd, 15)
        if probe["exit_code"] != 0 or probe["timed_out"]:
            return self._result(probe, "SANDBOX_UNAVAILABLE", workload_started=False)
        if before_dispatch is not None:
            before_dispatch()
        hooks = ({"on_started": observation.started, "stream_sink": observation.write,
                  "on_capture": observation.captured} if observation is not None else {})
        if cancellation_reason is not None:
            hooks["cancellation_reason"] = cancellation_reason
        completed = self._capture(prefix + list(command.argv), command.cwd, command.timeout_seconds, **hooks)
        return classify_local_capture(completed)

    @staticmethod
    def _result(result: dict[str, Any], reason: str, *, workload_started: bool | None) -> dict[str, Any]:
        # A nonzero sandbox wrapper exit does not prove the workload launched.
        # Timeout/partial effects require reconciliation, never automatic retry.
        return {**result, "status": "UNKNOWN_SIDE_EFFECT" if (result["timed_out"] or result.get("capture_error")
                or result.get("cancellation_reason")) and workload_started is not False
                else "PASS" if reason == "LOCAL_PROCESS_EXIT_ZERO" else "VALIDATION_FAILED",
                "reason_code": reason, "workload_started": workload_started,
                "receiver": "CODEX_SANDBOX_PERMISSION_PROFILE", "network": "DENY"}


def classify_local_capture(capture):
    if capture.get("process_started") is False:
        return CodexSandboxRunner._result(capture, "LOCAL_PROCESS_START_FAILED", workload_started=False)
    reason = ("LOCAL_PROCESS_CANCELLED" if capture.get("cancellation_reason") else
              "LOCAL_CAPTURE_FAILED" if capture.get("capture_error") else
              "LOCAL_PROCESS_TIMEOUT" if capture["timed_out"] else
              "LOCAL_PROCESS_EXIT_ZERO" if capture["exit_code"] == 0 else "LOCAL_PROCESS_NONZERO_EXIT")
    return CodexSandboxRunner._result(capture, reason, workload_started=None)
