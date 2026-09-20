"""Finite Codex coding service invocation; not a grant or Workpack Oracle.

The client uses its existing OS-user authentication state. Its model/service
traffic is explicitly external; generated local commands remain scoped and
offline. Callers must obtain current authority before invoking this receiver.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib
from uuid import uuid4

from .coding_protocol import CodingEventObserver
from .local_process import CodexSandboxRunner, LocalCommand, LocalProcessError, _toml_inline, _within


DISABLED_FEATURES = (
    "apps", "hooks", "plugins", "remote_plugin", "multi_agent", "multi_agent_v2", "memories",
    "browser_use", "browser_use_external", "browser_use_full_cdp_access", "in_app_browser",
    "computer_use", "image_generation", "goals", "skill_mcp_dependency_install", "shell_snapshot",
    "unbounded_connection_retries",
)


def client_state_root() -> Path:
    # Match a fresh child environment without HOME/CODEX_HOME overrides.
    if os.name != "posix":
        raise LocalProcessError("coding receiver currently supports POSIX hosts only")
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".codex"


def check_configuration_sources(cwd: Path) -> None:
    """Reject additional configuration whose effects this route has not bound.

    --ignore-user-config excludes the user's config, not system or project
    layers. Until effective-config hydration exists, do not let these layers
    replace the explicit permission profile or initialize unapproved MCPs.
    This does not edit configuration or ignore managed requirements/rules.
    """
    paths = [Path("/etc/codex/config.toml"), *(parent / ".codex/config.toml" for parent in (cwd, *cwd.parents))]
    for path in paths:
        if path == client_state_root() / "config.toml":
            continue  # The explicitly excluded user layer, not a project override.
        if path.exists():
            try:
                with path.open("rb") as stream:
                    value = tomllib.load(stream)
            except tomllib.TOMLDecodeError as exc:
                raise LocalProcessError(f"invalid Codex configuration: {path}") from exc
            if value:
                raise LocalProcessError(f"additional Codex configuration requires explicit hydration: {path}")


def instruction_read_preflight(cwd: Path, read_roots, write_roots=()) -> dict:
    """Check default instruction discovery against declared reads; never grant them.

    User config is excluded and additional project config is rejected by this
    receiver. This checks the default global/Git-root-to-cwd instruction chain,
    not all managed configuration or real Codex session readiness. Empty files
    also require a read before the client can decide to skip them.
    """
    cwd = Path(cwd).resolve()
    lineage = [cwd, *cwd.parents]
    root = next((path for path in lineage if (path / ".git").exists()), cwd)
    directories = [client_state_root(), *reversed(lineage[:lineage.index(root) + 1])]
    files = []
    for directory in directories:
        for name in ("AGENTS.override.md", "AGENTS.md"):
            path = directory / name
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            if not path.is_file():
                raise LocalProcessError(f"instruction source is not a regular file: {path}")
            files.append(path.resolve())
            if size:
                break
    roots = tuple(Path(path).resolve() for path in (*read_roots, *write_roots))
    missing = [str(path) for path in files if not _within(path, roots)]
    return {"status": "READ_SCOPE_MISSING" if missing else "READ_SCOPE_COVERED",
            "instruction_files": [str(path) for path in files], "missing_read_paths": missing,
            "session_readiness_verified": False, "permissions_added": False}


@dataclass(frozen=True)
class CodingCommand:
    scope: LocalCommand
    prompt: str
    model: str | None = None

    def validate(self):
        if (len(self.scope.argv) != 1 or not isinstance(self.prompt, str) or not self.prompt
                or "\x00" in self.prompt or self.model is not None
                and (not isinstance(self.model, str) or not self.model or "\x00" in self.model)):
            raise LocalProcessError("coding needs one executable, a full prompt and an optional explicit model")
        current = LocalCommand.prepare(argv=self.scope.argv, cwd=self.scope.cwd,
            read_roots=self.scope.read_roots, write_roots=self.scope.write_roots, timeout_seconds=self.scope.timeout_seconds)
        if current != self.scope:
            raise LocalProcessError("coding scope changed before dispatch")
        state = client_state_root().resolve()
        # Explicit, exact instruction-file reads do not expose credentials or
        # the whole client directory. Resolved symlinks to auth/state still fail.
        instruction_files = {state / name for name in ("AGENTS.md", "AGENTS.override.md")}
        if (any(root == state or state.is_relative_to(root) or root.is_relative_to(state)
                for root in self.scope.write_roots)
                or any((root == state or state.is_relative_to(root) or root.is_relative_to(state))
                       and not (root in instruction_files and root.is_file()) for root in self.scope.read_roots)):
            raise LocalProcessError("model tools cannot access the client's authentication/state directory")
        check_configuration_sources(self.scope.cwd)

    def instruction_preflight(self):
        return instruction_read_preflight(self.scope.cwd, self.scope.read_roots, self.scope.write_roots)

    def argv(self):
        name = "foundry_coding_" + uuid4().hex
        settings = {
            "default_permissions": name, "permissions." + name: self.scope.permission_profile(),
            "approval_policy": "never", "model_provider": "openai", "web_search": "disabled",
            "agents.enabled": False, "shell_environment_policy.inherit": "none",
            "allow_login_shell": False,
            **{"features." + feature: False for feature in DISABLED_FEATURES},
        }
        argv = [self.scope.argv[0], "exec", "--ignore-user-config", "--strict-config", "--ephemeral",
                "--json", "--color", "never", "--skip-git-repo-check", "--cd", str(self.scope.cwd)]
        for key, value in settings.items():
            argv += ["-c", key + "=" + _toml_inline(value)]
        if self.model is not None:
            argv += ["--model", self.model]
        return [*argv, "-"]


class CodexCodingRunner(CodexSandboxRunner):
    """No automatic retry, resume, user config rewrite or sandbox fallback."""

    def run(self, command: CodingCommand, *, before_dispatch, observation=None):
        command.validate()
        instruction_check = command.instruction_preflight()
        if instruction_check["missing_read_paths"]:
            return self._instruction_stop(instruction_check)
        if Path(command.scope.argv[0]).resolve() != self.executable:
            raise LocalProcessError("coding command and receiver executable differ")
        help_result = self._capture([str(self.executable), "exec", "--help"], command.scope.cwd, 15)
        required = ("--ignore-user-config", "--strict-config", "--ephemeral", "--json", "--cd", "stdin")
        text = help_result["stdout"] + help_result["stderr"]
        if help_result["exit_code"] != 0 or help_result["timed_out"] or not all(flag in text for flag in required):
            return {"status": "VALIDATION_FAILED", "reason_code": "CODING_CLI_INTERFACE_UNAVAILABLE",
                    "model_process_started": False, "capture": help_result, "workpack_accepted": False,
                    "automatic_retry_allowed": False}
        # Test the actual local command sandbox before contacting a model. This
        # proves only local command capability, not instruction discovery,
        # real session readiness, a model turn or Workpack success.
        scope = command.scope
        probe = LocalCommand.prepare(argv=["/usr/bin/true"], cwd=scope.cwd,
            read_roots=[*scope.read_roots, "/usr/bin/true"], write_roots=scope.write_roots, timeout_seconds=15)
        capability = CodexSandboxRunner(self.executable).run(probe)
        if capability["status"] != "PASS":
            return {"status": "VALIDATION_FAILED", "reason_code": "CODING_SANDBOX_UNAVAILABLE",
                    "model_process_started": False, "capture": capability, "workpack_accepted": False,
                    "automatic_retry_allowed": False}
        command.validate()
        instruction_check = command.instruction_preflight()
        if instruction_check["missing_read_paths"]:
            return self._instruction_stop(instruction_check)
        try:
            before_dispatch()  # Recheck current authority now, not just before probes.
        except Exception as exc:
            return {"status": "VALIDATION_FAILED", "reason_code": "CODING_DISPATCH_REVALIDATION_FAILED",
                    "model_process_started": False, "diagnostic": str(exc), "workpack_accepted": False,
                    "automatic_retry_allowed": False}
        observer = CodingEventObserver()
        hooks = ({"on_started": observation.started, "stream_sink": observation.write,
                  "on_capture": observation.captured} if observation is not None else {})
        capture = self._capture(command.argv(), scope.cwd, scope.timeout_seconds,
                                stdin_bytes=command.prompt.encode("utf-8"), on_stdout=observer.feed, **hooks)
        return {**classify_coding_capture(capture, observer), "instruction_preflight": instruction_check}

    @staticmethod
    def _instruction_stop(check):
        return {"status": "VALIDATION_FAILED", "reason_code": "CODING_INSTRUCTION_READS_REQUIRED",
                "model_process_started": False, "automatic_retry_allowed": False,
                "workpack_accepted": False, "instruction_preflight": check}


def classify_coding_capture(capture, observer):
    observed = observer.finish(exit_code=capture["exit_code"], timed_out=capture["timed_out"],
                               output_truncated=bool(capture.get("capture_error")))
    if capture.get("capture_error"):
        observed.update(status="UNKNOWN_SIDE_EFFECT", reason_code="CODING_CAPTURE_FAILED")
    if capture.get("process_started") is False:
        return {**observed, "capture": capture, "status": "VALIDATION_FAILED",
                "reason_code": "CODING_PROCESS_START_FAILED", "model_process_started": False}
    return {**observed, "capture": capture, "model_process_started": None,
            "client_network": "CODEX_SERVICE_TRAFFIC", "local_command_network": "DENY"}
