"""Local command receiver using Codex's supported permission-profile interface.

This receiver is not an authorizer or a model client. Its caller must resolve
the current Job leases and authorize the resulting local paths first. No shell,
profile file, global configuration mutation or unsandboxed fallback is used.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from typing import Any, Sequence
from uuid import uuid4


class LocalProcessError(ValueError):
    """Invalid command or unavailable receiver, before workload dispatch."""


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

    def __init__(self, executable: str | Path, *, output_limit_bytes: int = 65536):
        self.executable = _path(executable)
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise LocalProcessError("Codex sandbox receiver is not executable")
        if not isinstance(output_limit_bytes, int) or isinstance(output_limit_bytes, bool) or output_limit_bytes < 1:
            raise LocalProcessError("output limit must be a positive integer")
        self.output_limit_bytes = output_limit_bytes

    @staticmethod
    def _environment() -> dict[str, str]:
        # Do not forward API keys, Python startup hooks or inherited proxy URLs.
        # HOME is left to the OS; never redirect Codex's own configuration home.
        return {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}

    def _capture(self, argv: list[str], cwd: Path, timeout: float, *, output_limit: int | None = None) -> dict[str, Any]:
        limit = self.output_limit_bytes if output_limit is None else output_limit
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                           stdout=stdout, stderr=stderr, shell=False,
                                           start_new_session=True, env=self._environment())
            except OSError as exc:
                return {"exit_code": None, "timed_out": False, "stdout": "",
                        "stderr": str(exc), "output_truncated": False}
            timed_out = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # Clean up this command's process group, including on normal
                # exit. Detached daemons/new sessions are not supported by this
                # finite-command receiver. Do not kill by executable name.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            captured = {}
            truncated = False
            for name, stream in (("stdout", stdout), ("stderr", stderr)):
                stream.seek(0)
                data = stream.read(limit + 1)
                truncated |= len(data) > limit
                captured[name] = data[:limit].decode("utf-8", errors="replace")
            return {"exit_code": process.returncode, "timed_out": timed_out,
                    "output_truncated": truncated, **captured}

    def run(self, command: LocalCommand) -> dict[str, Any]:
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
        completed = self._capture(prefix + list(command.argv), command.cwd, command.timeout_seconds)
        reason = ("LOCAL_PROCESS_TIMEOUT" if completed["timed_out"] else
                  "LOCAL_PROCESS_EXIT_ZERO" if completed["exit_code"] == 0 else "LOCAL_PROCESS_NONZERO_EXIT")
        return self._result(completed, reason, workload_started=None)

    @staticmethod
    def _result(result: dict[str, Any], reason: str, *, workload_started: bool | None) -> dict[str, Any]:
        # A nonzero sandbox wrapper exit does not prove the workload launched.
        # Timeout/partial effects require reconciliation, never automatic retry.
        return {**result, "status": "UNKNOWN_SIDE_EFFECT" if result["timed_out"] and workload_started is not False
                else "PASS" if reason == "LOCAL_PROCESS_EXIT_ZERO" else "VALIDATION_FAILED",
                "reason_code": reason, "workload_started": workload_started,
                "receiver": "CODEX_SANDBOX_PERMISSION_PROFILE", "network": "DENY"}
