"""Finite Codex coding service invocation; not a grant or Workpack Oracle.

The client uses its existing OS-user authentication state. Its model/service
traffic is explicitly external; generated local commands remain scoped and
offline. Callers must obtain current authority before invoking this receiver.
"""

from dataclasses import dataclass, replace
from copy import deepcopy
import json
import os
from pathlib import Path
import tomllib
from uuid import uuid4

from .coding_events import CodingEventObserver, _contract_blocker
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
    reasoning_effort: str | None = None
    model_policy: str = "FIXED"
    model_service: dict | None = None
    model_defaults_source: dict | None = None

    def validate(self):
        from .coding_defaults import validate_model_service
        if self.model_policy not in {"FIXED", "CODEX_GLOBAL_DEFAULTS"}:
            raise LocalProcessError("coding model policy must be FIXED or CODEX_GLOBAL_DEFAULTS")
        if self.model_policy == "CODEX_GLOBAL_DEFAULTS" and self.model_service is None:
            raise LocalProcessError("dynamic model policy requires a bound model service; reprepare the old scope")
        validate_model_service(self.model_service if self.model_service is not None
                               else {"provider": "openai", "config": {}})
        if (len(self.scope.argv) != 1 or not isinstance(self.prompt, str) or not self.prompt
                or "\x00" in self.prompt or self.model is not None
                and (not isinstance(self.model, str) or not self.model or "\x00" in self.model)
                or self.reasoning_effort is not None and (not isinstance(self.reasoning_effort, str)
                    or not self.reasoning_effort.strip() or "\x00" in self.reasoning_effort)):
            raise LocalProcessError("coding needs one executable, a full prompt and optional explicit model/reasoning effort")
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
        from .coding_defaults import validate_model_service
        service = validate_model_service(self.model_service if self.model_service is not None
                                         else {"provider": "openai", "config": {}})
        name = "foundry_coding_" + uuid4().hex
        settings = {
            "default_permissions": name, "permissions." + name: self.scope.permission_profile(),
            "approval_policy": "never", "model_provider": service["provider"], "web_search": "disabled",
            "agents.enabled": False, "shell_environment_policy.inherit": "none",
            "allow_login_shell": False,
            **{"features." + feature: False for feature in DISABLED_FEATURES},
        }
        if service["config"]:
            settings["model_providers." + service["provider"]] = service["config"]
        argv = [self.scope.argv[0], "exec", "--ignore-user-config", "--strict-config", "--ephemeral",
                "--json", "--color", "never", "--skip-git-repo-check", "--cd", str(self.scope.cwd)]
        if self.reasoning_effort is not None:
            settings["model_reasoning_effort"] = self.reasoning_effort
        for key, value in settings.items():
            argv += ["-c", key + "=" + _toml_inline(value)]
        if self.model is not None:
            argv += ["--model", self.model]
        return [*argv, "-"]


class _CodingOutputRedactor:
    """Keep machine facts intact; credentials echoed in payloads remain private."""

    def __init__(self, redactor):
        self.redactor = redactor

    def text(self, value):
        return self.redactor.text(value)

    def stream_for(self, name):
        return _CodingJsonlRedactor(self.redactor) if name == "stdout" else self.redactor.stream()


class _CodingJsonlRedactor:
    # The observer already uses this event bound. Oversized/invalid lines stay
    # invalid after filtering rather than shrinking into valid completion proof.
    def __init__(self, redactor, max_event_bytes=8 * 1024 * 1024):
        self.redactor, self.max_event_bytes = redactor, max_event_bytes
        self.pending = bytearray()
        self.overflow = None

    def _invalid(self, payload):
        stream = self.redactor.stream()
        return b"[INVALID JSONL] " + stream.feed(payload) + stream.finish()

    def _line(self, payload):
        if not payload.strip():
            return self._invalid(payload) if self.redactor.bytes(payload) != payload else payload
        try:
            value = json.loads(payload)
            if not isinstance(value, dict) or value.get("type") not in {
                    "thread.started", "turn.started", "turn.completed", "turn.failed", "error",
                    "item.started", "item.updated", "item.completed"}:
                return self._invalid(payload)

            def clean(item, path=()):
                if isinstance(item, str):
                    if (path in {("type",), ("item", "type"), ("item", "status")}
                            or path == ("item", "text", "$report", "foundry_blocker", "failure_kind")
                            and item == "CONTRACT_GAP"):
                        return item  # Preserve protocol facts, not arbitrary blocker text.
                    if path == ("item", "text"):
                        try:
                            report = json.loads(item)
                        except ValueError:
                            report = None
                        if isinstance(report, dict) and "foundry_blocker" in report:
                            # The existing stop report is also protocol. Losing
                            # its envelope must not turn a blocker into success.
                            filtered = clean(report, (*path, "$report"))
                            original = _contract_blocker(item)
                            if original["reason_code"] == "CODEX_BLOCKER_REPORT_INVALID":
                                # Keep the original invalid verdict even if a
                                # whitespace/oversized value becomes valid text
                                # after masking. Retain its filtered diagnostic.
                                filtered = {"foundry_blocker": [filtered]}
                            else:
                                blocker = filtered["foundry_blocker"]
                                for key in ("reason", "owner", "minimum_return_path"):
                                    blocker[key] = blocker[key][:4096]
                                blocker["evidence"] = [text[:4096] for text in blocker["evidence"]]
                            return json.dumps(filtered, ensure_ascii=True)
                    return self.redactor.text(item)
                if isinstance(item, dict):
                    fields = ({"type", "thread_id", "item", "usage", "error", "message"} if not path else
                        {"id", "type", "status", "command", "aggregated_output", "exit_code", "text",
                         "changes", "items", "server", "tool", "arguments", "result", "error", "url"}
                        if path == ("item",) else
                        {"input_tokens", "cached_input_tokens", "output_tokens"} if path == ("usage",) else
                        {"foundry_blocker"} if path == ("item", "text", "$report") else
                        {"failure_kind", "reason", "owner", "evidence", "minimum_return_path"}
                        if path == ("item", "text", "$report", "foundry_blocker") else set())
                    return {key if key in fields else self.redactor.text(key): clean(child, (*path, key))
                            for key, child in item.items()}
                if isinstance(item, list):
                    return [clean(child, (*path, index)) for index, child in enumerate(item)]
                if (len(path) == 2 and path[0] == "usage" and type(item) in {int, float}
                        or path == ("item", "exit_code") and (item is None or type(item) is int)):
                    return item  # Explicit native machine facts, not arbitrary payload scalars.
                return json.loads(self.redactor.json_bytes(json.dumps(item).encode("utf-8")))

            return json.dumps(clean(value), ensure_ascii=False).encode("utf-8", errors="backslashreplace")
        except (ValueError, TypeError, RecursionError):
            return self._invalid(payload)

    def feed(self, chunk):
        output = bytearray()
        parts = chunk.split(b"\n")
        for index, part in enumerate(parts):
            ended = index < len(parts) - 1
            if self.overflow is not None:
                output.extend(self.overflow.feed(part))
            else:
                self.pending.extend(part)
                if len(self.pending) > self.max_event_bytes:
                    self.overflow = self.redactor.stream()
                    output.extend(b"[INVALID JSONL] ")
                    output.extend(self.overflow.feed(bytes(self.pending)))
                    self.pending.clear()
            if ended:
                if self.overflow is not None:
                    output.extend(self.overflow.finish())
                    self.overflow = None
                else:
                    output.extend(self._line(bytes(self.pending)))
                    self.pending.clear()
                output.extend(b"\n")
        return bytes(output)

    def finish(self):
        if self.overflow is not None:
            result = self.overflow.finish()
            self.overflow = None
            return result
        result = self._line(bytes(self.pending)) if self.pending else b""
        self.pending.clear()
        return result


def _dispatch_configuration(command):
    """Resolve once per new dispatch. Recovery never calls this function."""
    from .coding_defaults import resolve_codex_defaults, validate_model_service, model_service_credential_refs
    from .resource_credentials import SecretRedactor
    service = validate_model_service(command.model_service if command.model_service is not None
                                     else {"provider": "openai", "config": {}})
    selected = command
    if command.model_policy == "CODEX_GLOBAL_DEFAULTS":
        defaults = resolve_codex_defaults(command.scope.argv[0], require_explicit=False)
        if defaults["model_service"] != service:
            raise LocalProcessError("CODING_MODEL_SERVICE_CHANGED: global service differs from the approved binding; reprepare the scope")
        selected = replace(command, model=defaults["model"], reasoning_effort=defaults["model_reasoning_effort"],
                           model_defaults_source=defaults["model_defaults_source"])
    selected.validate()
    configuration = {"model_policy": command.model_policy, "model": selected.model,
                     "model_reasoning_effort": selected.reasoning_effort, "model_service": service,
                     "model_defaults_source": selected.model_defaults_source}
    # The receiver does not inherit the host environment. Rename only declared
    # references so a credential named PATH/HOME cannot change client execution.
    environment, aliases = {}, {}
    for index, reference in enumerate(model_service_credential_refs(service), 1):
        value = os.environ.get(reference)
        if not isinstance(value, str) or not value or "\x00" in value:
            raise LocalProcessError("CODING_MODEL_CREDENTIAL_UNAVAILABLE: declared environment reference " + reference)
        alias = "FOUNDRY_MODEL_CREDENTIAL_" + str(index)
        aliases[reference], environment[alias] = alias, value
    private_service = deepcopy(service)
    config = private_service["config"]
    if "env_key" in config:
        config["env_key"] = aliases[config["env_key"]]
    if "env_http_headers" in config:
        config["env_http_headers"] = {header: aliases[reference]
                                      for header, reference in config["env_http_headers"].items()}
    # Native JSONL may quote/escape a known value. Filter those representations
    # before durable storage and parsing without altering JSONL machine facts.
    tokens = set(environment.values())
    for value in environment.values():
        tokens.update(json.dumps(value, ensure_ascii=ascii_only)[1:-1] for ascii_only in (False, True))
    redactor = _CodingOutputRedactor(SecretRedactor(tokens)) if tokens else None
    return replace(selected, model_service=private_service), configuration, environment, redactor


class CodexCodingRunner(CodexSandboxRunner):
    """No automatic retry, resume, user config rewrite or sandbox fallback."""

    def run(self, command: CodingCommand, *, before_dispatch, observation=None, cancellation_reason=None):
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
            selected, configuration, environment, redactor = _dispatch_configuration(command)
        except LocalProcessError as exc:
            reason = str(exc).split(":", 1)[0]
            if reason not in {"CODING_MODEL_SERVICE_CHANGED", "CODING_MODEL_CREDENTIAL_UNAVAILABLE"}:
                reason = "CODING_MODEL_CONFIGURATION_UNAVAILABLE"
            return {"status": "VALIDATION_FAILED", "reason_code": reason,
                    "model_process_started": False, "diagnostic": str(exc), "workpack_accepted": False,
                    "automatic_retry_allowed": False}
        if observation is not None:
            observation.model_configuration(configuration)
        observer = CodingEventObserver()

        def captured(value):
            value["model_configuration"] = configuration
            if observation is not None:
                observation.captured(value)

        hooks = {"on_capture": captured, "environment": environment, "redactor": redactor}
        if observation is not None:
            hooks.update(on_started=observation.started, stream_sink=observation.write)
        if cancellation_reason is not None:
            hooks["cancellation_reason"] = cancellation_reason
        argv = selected.argv()
        try:
            before_dispatch()  # Current authority after selection, immediately before launch.
        except Exception as exc:
            return {"status": "VALIDATION_FAILED", "reason_code": "CODING_DISPATCH_REVALIDATION_FAILED",
                    "model_process_started": False, "diagnostic": redactor.text(str(exc)) if redactor else str(exc),
                    "model_configuration": configuration, "workpack_accepted": False,
                    "automatic_retry_allowed": False}
        capture = self._capture(argv, scope.cwd, scope.timeout_seconds,
                                stdin_bytes=command.prompt.encode("utf-8"), on_stdout=observer.feed, **hooks)
        # Popen failures return without on_capture; still report the selection,
        # but never call them a consumed model turn or a completed command.
        capture["model_configuration"] = configuration
        return {**classify_coding_capture(capture, observer), "instruction_preflight": instruction_check}

    @staticmethod
    def _instruction_stop(check):
        return {"status": "VALIDATION_FAILED", "reason_code": "CODING_INSTRUCTION_READS_REQUIRED",
                "model_process_started": False, "automatic_retry_allowed": False,
                "workpack_accepted": False, "instruction_preflight": check}


def classify_coding_capture(capture, observer):
    observed = observer.finish(exit_code=capture["exit_code"], timed_out=capture["timed_out"],
                               output_truncated=bool(capture.get("capture_error")))
    if "model_configuration" in capture:
        observed["model_configuration"] = capture["model_configuration"]
    if capture.get("capture_error"):
        observed.update(status="UNKNOWN_SIDE_EFFECT", reason_code="CODING_CAPTURE_FAILED")
    if capture.get("cancellation_reason"):
        observed.update(status="UNKNOWN_SIDE_EFFECT", reason_code="CODING_PROCESS_CANCELLED",
                        cancellation_reason=capture["cancellation_reason"])
    if capture.get("process_started") is False:
        return {**observed, "capture": capture, "status": "VALIDATION_FAILED",
                "reason_code": "CODING_PROCESS_START_FAILED", "model_process_started": False}
    return {**observed, "capture": capture, "model_process_started": None,
            "client_network": "CODEX_SERVICE_TRAFFIC", "local_command_network": "DENY"}
