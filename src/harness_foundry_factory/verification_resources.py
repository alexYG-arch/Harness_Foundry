"""Command-owned verification files and reports, never another authority store.

The controller persists the returned binding before dispatch. The checker owns
only its scratch/report leaves; the controller collects reports after process
completion and removes successful scratch only after its observation is durable.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from uuid import uuid4

from .build_types import RequestValidationError, SAFE_ID_RE
from .resource_network import normalize_network
from .resource_credentials import validate_credentials


IDENTITY_FIELDS = ("program_id", "prepared_event_id", "attempt_id", "case_id", "command_id")
AREAS = {"scratch", "report-staging"}


def _require(condition, message):
    if not condition:
        raise RequestValidationError(message, details={"reason_code": "BUILD_VERIFICATION_RESOURCES_INVALID"})


def _relative(value):
    _require(isinstance(value, str) and value and "\\" not in value and ":" not in value
             and not any(ord(char) < 32 for char in value), "resource paths must be relative plain paths")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and str(path) == value and value != "." and ".." not in path.parts,
             "resource paths must be canonical relative paths without traversal")
    return path


def _unlinked(path):
    """Refuse links in existing ancestors as well as the named object."""
    path = Path(path)
    _require(path.is_absolute() and ".." not in path.parts, "resource roots must be absolute without traversal")
    for item in (path, *path.parents):
        _require(not item.is_symlink(), "resource paths cannot contain symbolic links")
    return path


def _network(value):
    _require(isinstance(value, dict), "resource network must be an object")
    mode = value.get("mode")
    if mode == "LOCAL_SERVICE" and set(value) == {"mode", "tcp"}:
        try:
            return normalize_network(value)
        except ValueError as exc:
            raise RequestValidationError(str(exc), details={"reason_code": "BUILD_VERIFICATION_RESOURCES_INVALID"}) from exc
    combined = mode == "LOCAL_SERVICE" and set(value) == {"mode", "tcp", "unix_sockets"}
    if combined:
        _require(value["tcp"] == "LOOPBACK", "local TCP selector must be LOOPBACK")
    fields = {"NONE": {"mode"}, "LOCAL_SERVICE": {"mode", "unix_sockets"},
              "REMOTE_SERVICE": {"mode", "allowed_hosts"}}
    _require(combined or isinstance(mode, str) and mode in fields and set(value) == fields[mode], "unsupported resource network contract")
    if mode == "LOCAL_SERVICE":
        sockets = value["unix_sockets"]
        _require(isinstance(sockets, list) and sockets and all(isinstance(item, str) for item in sockets)
                 and len(sockets) == len(set(sockets)),
                 "local service needs unique owned Unix socket references")
        for socket in sockets:
            _require(isinstance(socket, str) and socket.startswith("resource://scratch/"),
                     "local sockets must belong to this command's scratch")
            _relative(socket.removeprefix("resource://scratch/"))
    if mode == "REMOTE_SERVICE":
        try:
            return normalize_network(value)
        except ValueError as exc:
            raise RequestValidationError(str(exc), details={"reason_code": "BUILD_VERIFICATION_RESOURCES_INVALID"}) from exc
    return deepcopy(value)


def _product_copy(value):
    _require(isinstance(value, dict) and set(value) == {"files", "writable_paths"},
             "product copy requires explicit files and writable_paths")
    paths = {}
    for field in ("files", "writable_paths"):
        values = value[field]
        _require(isinstance(values, list) and values and all(isinstance(item, str) for item in values)
                 and len(values) == len(set(values)), "product copy paths must be nonempty unique relative paths")
        paths[field] = [_relative(item) for item in values]
    files = paths["files"]
    _require(not any(a in b.parents or b in a.parents for i, a in enumerate(files) for b in files[i + 1:]),
             "product input files cannot overlap as files and directories")
    _require(not any(a == b or a in b.parents or b in a.parents
                     for a in files for b in paths["writable_paths"]),
             "product generated directories cannot overlap declared inputs")
    return deepcopy(value)


def validate_resources(config, plan, protected_paths=()):
    """Validate an opt-in scope; never create directories or launch processes."""
    references = [check.get("resource_profile_ref") for task in plan["workpacks"]
                  for check in task["verification"] if "resource_profile_ref" in check]
    if config is None:
        _require(not references, "resource profile reference needs verification_resources scope")
        # Older Plans treated this newly reserved prefix as an ordinary argv
        # string. Only the resource-aware Plan version interprets it.
        if plan["schema_version"] == "1.2":
            validate_resource_references(None, plan)
        return None
    _require(plan["schema_version"] == "1.2", "verification resources require Plan 1.2")
    _require(isinstance(config, dict) and set(config) in ({"schema_version", "root", "profiles"},
             {"schema_version", "root", "profiles", "checker_files"})
             and config["schema_version"] == "1.0", "unsupported verification resources fields or version")
    _require(isinstance(config["root"], str) and not any(ord(char) < 32 for char in config["root"]),
             "resource root must be a plain path")
    source_root = Path(config["root"])
    _require(source_root.is_absolute() and ".." not in source_root.parts, "resource root must be absolute without traversal")
    root = source_root.resolve()
    _require(not source_root.is_symlink(), "resource root itself cannot be a symbolic link")
    _unlinked(root)
    _require(root != Path(root.anchor), "resource root cannot be filesystem root")
    for protected in protected_paths:
        protected = Path(protected).resolve()
        _require(not (root.is_relative_to(protected) or protected.is_relative_to(root)),
                 "resource root must not overlap product, checker, control or implementation write roots")
    if root.exists():
        _require(root.is_dir(), "resource root must be a directory")
    profiles = config["profiles"]
    _require(isinstance(profiles, dict) and profiles, "verification resources need named profiles")
    required = {"writable_areas", "network", "services", "result_protocol", "required_checks", "report_files", "retention"}
    for name, profile in profiles.items():
        _require(isinstance(name, str) and SAFE_ID_RE.fullmatch(name), "invalid resource profile reference")
        _require(isinstance(profile, dict) and required <= set(profile) <= required | {"credentials", "product_copy"},
                 "resource profile fields are incomplete or unknown")
        if "product_copy" in profile:
            _product_copy(profile["product_copy"])
        if "credentials" in profile:
            try:
                validate_credentials(profile["credentials"])
            except ValueError as exc:
                raise RequestValidationError(str(exc), details={"reason_code": "BUILD_VERIFICATION_RESOURCES_INVALID"}) from exc
        _require(isinstance(profile["writable_areas"], list) and len(profile["writable_areas"]) == 2
                 and all(isinstance(item, str) for item in profile["writable_areas"])
                 and set(profile["writable_areas"]) == AREAS, "STRUCTURED_V1 uses scratch and report-staging leaves")
        _network(profile["network"])
        _require(profile["services"] == [], "services are owned by the finite checker; cross-command sidecars are unsupported")
        _require(profile["result_protocol"] == "STRUCTURED_V1", "unsupported resource result protocol")
        checks = profile["required_checks"]
        _require(isinstance(checks, list) and checks and all(isinstance(item, str) and SAFE_ID_RE.fullmatch(item)
                 for item in checks) and len(checks) == len(set(checks)), "required_checks must contain unique obligation IDs")
        files = profile["report_files"]
        _require(isinstance(files, list) and all(isinstance(item, str) for item in files)
                 and "summary.json" in files and len(files) == len(set(files)),
                 "report_files must declare summary.json and unique relative file paths")
        paths = [_relative(item) for item in files]
        _require(not any(a in b.parents or b in a.parents for i, a in enumerate(paths) for b in paths[i + 1:]),
                 "report file paths cannot overlap as files and directories")
        retention = profile["retention"]
        _require(isinstance(retention, dict) and set(retention) == {"success", "failure_days"}
                 and retention["success"] == "REPORTS_ONLY" and type(retention["failure_days"]) is int
                 and retention["failure_days"] >= 0, "retention must state REPORTS_ONLY and nonnegative failure_days")
    _require(set(references) <= profiles.keys(), "verification references an unknown resource profile")
    if "checker_files" in config:
        files = config["checker_files"]
        _require(isinstance(files, list) and all(isinstance(item, str) for item in files)
                 and len(files) == len(set(files)), "checker_files must contain unique relative paths")
        for item in files:
            _relative(item)
    normalized = deepcopy(config)
    normalized["root"] = str(root)
    for profile in normalized["profiles"].values():
        profile["network"] = _network(profile["network"])
    validate_resource_references(normalized, plan)
    return normalized


def validate_resource_references(config, plan):
    """Check reserved argv references during prepare, without allocating leaves."""
    for task in plan["workpacks"]:
        _require(not any(argument.startswith("resource://") for argument in task.get("local_argv", [])),
                 "implementation argv cannot use verification-only resource references")
        for check in task["verification"]:
            for argument in check["argv"]:
                if not argument.startswith("resource://"):
                    continue
                profile_ref = check.get("resource_profile_ref")
                _require(config is not None and profile_ref in config["profiles"],
                         "resource argv requires a declared resource profile")
                ref = argument.removeprefix("resource://")
                area, separator, relative = ref.partition("/")
                _require(area in config["profiles"][profile_ref]["writable_areas"],
                         "resource argv references an undeclared writable area")
                if separator:
                    _relative(relative)


def allocate_resources(config, profile_ref, binding):
    """Allocate empty leaves once; logical recovery must reuse its stored binding."""
    identity = {}
    for field in IDENTITY_FIELDS:
        value = binding.get(field)
        _require(isinstance(value, str) and SAFE_ID_RE.fullmatch(value), f"resource binding needs valid {field}")
        identity[field] = value
    profile = deepcopy(config["profiles"][profile_ref])
    root = _unlinked(config["root"])
    root.mkdir(parents=True, exist_ok=True)
    command_root = root / uuid4().hex[:12]
    command_root.mkdir()  # Caller must persist this allocation before dispatch.
    # Short leaves avoid making Unix service endpoints depend on verbose IDs.
    # All identities remain in the persisted binding, not encoded in path names.
    areas = {}
    for name in sorted(AREAS):
        directory = command_root / name
        directory.mkdir()
        areas[name] = str(directory)
    cache = Path(areas["scratch"]) / "cache"
    cache.mkdir()
    env = {"TMPDIR": areas["scratch"], "TMP": areas["scratch"], "TEMP": areas["scratch"],
           "XDG_CACHE_HOME": str(cache), "FOUNDRY_SCRATCH_DIR": areas["scratch"],
           "FOUNDRY_REPORT_DIR": areas["report-staging"],
           **{f"FOUNDRY_{key.upper()}": value for key, value in identity.items()}}
    result = {"schema_version": "1.0", **identity, "profile_ref": profile_ref, "profile": profile,
              "root": str(command_root), "areas": areas, "env": env,
              "write_roots": list(areas.values()), "required_checks": profile["required_checks"],
              "report_files": profile["report_files"], "network": deepcopy(profile["network"])}
    if "unix_sockets" in result["network"]:
        result["network"]["unix_sockets"] = resolve_resource_argv(result["network"]["unix_sockets"], result)
        for socket in result["network"]["unix_sockets"]:
            Path(socket).parent.mkdir(parents=True, exist_ok=True)
    return result


def resolve_resource_argv(argv, binding):
    """Hydrate explicit resource tokens only; no shell or ambient substitution."""
    result = []
    for argument in argv:
        if not argument.startswith("resource://"):
            result.append(argument)
            continue
        ref = argument.removeprefix("resource://")
        area, separator, relative = ref.partition("/")
        _require(area in binding["areas"], "resource reference names an undeclared writable area")
        path = Path(binding["areas"][area])
        if separator:
            path = path / _relative(relative)
        _unlinked(path)
        result.append(str(path))
    return result


def _read_regular(root, relative, *, with_mode=False, allow_hardlinks=False):
    """Open components via dirfd; reports/copies reject links and hardlinks.

    Source inputs may be ordinary hardlinked files: reading their bytes into a
    fresh file never preserves the source link relationship.
    """
    parts = _relative(relative).parts
    directory = os.open(_unlinked(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = following
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (not allow_hardlinks and info.st_nlink != 1):
                raise ValueError("report must be a regular file with one link")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                payload = stream.read()
                return (payload, info.st_mode) if with_mode else payload
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def _file_fingerprint(payload):
    return {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def materialize_product_copy(binding, workspace_root):
    """Copy declared current inputs once before dispatch; never rebuild recovery.

    The sandbox reads this root but writes only the separately declared output
    directories. The root is deliberately not a scratch or report area.
    """
    declaration = binding["profile"].get("product_copy")
    if declaration is None:
        return binding
    declaration = _product_copy(declaration)
    if "product_copy" in binding:
        _require(validate_product_copy(binding)["status"] == "UNCHANGED",
                 "an existing product copy cannot be silently rebuilt")
        return binding
    try:
        command_root = _unlinked(binding["root"])
        source_root = Path(workspace_root).resolve()
        _require(not Path(workspace_root).is_symlink(), "product source root cannot be a symbolic link")
        _unlinked(source_root)
        _require(source_root.is_dir(), "product source root must be a directory")
        root = command_root / "product"
        root.mkdir()  # A preexisting, unbound leaf is never a reusable snapshot.
        files = []
        for relative in declaration["files"]:
            payload, mode = _read_regular(source_root, relative, with_mode=True, allow_hardlinks=True)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            execute_bits = mode & 0o111
            target.chmod(0o444 | execute_bits)
            copied = _read_regular(root, relative)
            files.append({"path": relative, "source": _file_fingerprint(payload),
                          "copy": _file_fingerprint(copied), "execute_bits": execute_bits})
        write_roots = []
        for relative in declaration["writable_paths"]:
            target = root / relative
            target.mkdir(parents=True, exist_ok=True)
            write_roots.append(str(target))
        copied = {"schema_version": "1.0", "identity": {key: binding[key] for key in IDENTITY_FIELDS},
                  "root": str(root), "source_root": str(source_root), "files": files,
                  "writable_paths": declaration["writable_paths"], "write_roots": write_roots}
    except (OSError, ValueError, RequestValidationError) as exc:
        raise RequestValidationError("product runtime copy could not be materialized",
                                     details={"reason_code": "BUILD_VERIFICATION_RESOURCES_INVALID"}) from exc
    binding["product_copy"] = copied
    binding["env"]["FOUNDRY_PRODUCT_ROOT"] = str(root)
    binding["write_roots"].extend(write_roots)
    return binding


def validate_product_copy(binding):
    """Check bound input bytes/execution bits; generated output is not an input.

    The controller separately checks current source versions before using these
    results. Exceptions yield fixed diagnostics, never arbitrary filesystem paths.
    """
    declaration = binding["profile"].get("product_copy")
    copied = binding.get("product_copy")
    if declaration is None and copied is None:
        return {"status": "NOT_REQUESTED", "reason": "PRODUCT_COPY_NOT_REQUESTED"}
    unavailable = {"status": "UNAVAILABLE", "reason": "PRODUCT_COPY_BINDING_UNAVAILABLE"}
    try:
        declaration = _product_copy(declaration)
        _require(isinstance(copied, dict) and copied.get("schema_version") == "1.0",
                 "product copy binding is missing or invalid")
        root = _unlinked(copied["root"])
        _require(root == Path(binding["root"]) / "product"
                 and copied["identity"] == {key: binding[key] for key in IDENTITY_FIELDS},
                 "product copy belongs to another command")
        _require([row["path"] for row in copied["files"]] == declaration["files"]
                 and copied["writable_paths"] == declaration["writable_paths"]
                 and copied["write_roots"] == [str(root / relative) for relative in declaration["writable_paths"]]
                 and binding["env"]["FOUNDRY_PRODUCT_ROOT"] == str(root)
                 and str(root) not in binding["write_roots"]
                 and all(path in binding["write_roots"] for path in copied["write_roots"]),
                 "product copy does not match its declared scope")
        for row in copied["files"]:
            if row["source"] != row["copy"]:
                return {"status": "CHANGED", "reason": "PRODUCT_COPY_INPUT_CHANGED"}
            payload, mode = _read_regular(root, row["path"], with_mode=True)
            if _file_fingerprint(payload) != row["copy"] or mode & 0o111 != row["execute_bits"]:
                return {"status": "CHANGED", "reason": "PRODUCT_COPY_INPUT_CHANGED"}
        return {"status": "UNCHANGED", "reason": "PRODUCT_COPY_INPUTS_UNCHANGED", "files_checked": len(copied["files"])}
    except (KeyError, TypeError, OSError, ValueError, RequestValidationError):
        return unavailable


def validate_product_copy_sources(binding, workspace_root):
    """Check result applicability to declared source inputs, even after cleanup.

    This never reads the disposable copy, changes its historical result, or scans
    undeclared files. Ordinary hardlinked sources retain their copy-time meaning.
    """
    try:
        copied = binding["product_copy"]
        declaration = binding["profile"]["product_copy"]
        source_root = _unlinked(workspace_root)
        _require(copied["source_root"] == str(source_root)
                 and [row["path"] for row in copied["files"]] == declaration["files"],
                 "product copy source binding differs from its declared workspace inputs")
        for row in copied["files"]:
            payload, mode = _read_regular(source_root, row["path"], with_mode=True, allow_hardlinks=True)
            if _file_fingerprint(payload) != row["source"] or mode & 0o111 != row["execute_bits"]:
                return {"status": "CHANGED", "reason": "PRODUCT_COPY_SOURCE_CHANGED"}
        return {"status": "UNCHANGED", "reason": "PRODUCT_COPY_SOURCES_UNCHANGED"}
    except (KeyError, TypeError, OSError, ValueError, RequestValidationError):
        return {"status": "UNAVAILABLE", "reason": "PRODUCT_COPY_SOURCE_UNAVAILABLE"}


def collect_resource_reports(binding, observation_root, *, redactor=None):
    """Copy declared checker output to host attachments; safe to repeat on recovery.

    An existing host copy takes precedence over a now-cleaned staging leaf. It
    belongs to this command's protected observation directory, not product data.
    """
    destination = Path(observation_root) / "reports"
    destination.mkdir(exist_ok=True)
    reports, errors = [], []
    verdict = None
    for relative in binding["report_files"]:
        target = destination / _relative(relative)
        try:
            if redactor is not None and target.exists():
                raise ValueError("credential report already archived without its completion capture")
            if not target.exists():
                payload = _read_regular(binding["areas"]["report-staging"], relative)
                if redactor is not None:
                    if relative == "summary.json":
                        # Judge the original in memory, never a redacted status
                        # or obligation identifier. Only safe bytes are stored.
                        verdict = json.loads(payload.decode("utf-8"))
                    payload = redactor.json_bytes(payload)
                target.parent.mkdir(parents=True, exist_ok=True)
                # Keep temporary files outside the declared report namespace:
                # a valid attachment may itself be named "summary.json.pending".
                # The sibling directory keeps replace on the same filesystem.
                with tempfile.TemporaryDirectory(prefix=".report-pending-", dir=observation_root) as temporary:
                    pending = Path(temporary) / "report"
                    with pending.open("wb") as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(pending, target)
                directory = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            payload = _read_regular(destination, relative)
            reports.append({"name": relative, "path": str(target), "size_bytes": len(payload),
                            "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        except (OSError, ValueError, UnicodeError, RequestValidationError) as exc:
            errors.append({"name": relative, "error": redactor.text(str(exc)) if redactor else str(exc)})
    if not errors and redactor is None:
        try:
            verdict = json.loads(_read_regular(destination, "summary.json").decode("utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append({"name": "summary.json", "error": str(exc)})
    return {"reports": reports, "report_errors": errors, "verdict": verdict, "result": verdict}


def validate_structured_result(verdict, binding, exit_code):
    """Only complete bound checks can pass or trigger native assertion repair."""
    invalid = {"status": "VALIDATION_FAILED", "automatic_retry_allowed": False,
               "failure_domain": "VERIFIER_INFRASTRUCTURE_OR_UNCLASSIFIED"}
    def fail(reason):
        return {**invalid, "resource_result_reason": reason}
    mode = binding["network"]["mode"]
    if mode == "REMOTE_SERVICE" and (
            not isinstance(verdict, dict) or verdict.get("schema_version") != "1.0"
            or any(verdict.get(key) != binding[key] for key in ("case_id", "command_id"))
            or verdict.get("external_effects") not in ("NONE", "CONFIRMED")):
        return {"status": "UNKNOWN_SIDE_EFFECT", "automatic_retry_allowed": False,
                "failure_domain": "UNKNOWN_EXTERNAL_EFFECTS",
                "resource_result_reason": "remote effects require a bound accounting report before another invocation"}
    if not isinstance(verdict, dict):
        return fail("structured verification report is missing or invalid")
    required = {"schema_version", "case_id", "command_id", "status", "checks", "errors"}
    if not required <= verdict.keys() or verdict["schema_version"] != "1.0":
        return fail("unsupported structured verification report fields or version")
    if any(verdict.get(key) != binding[key] for key in ("case_id", "command_id")):
        return fail("structured report does not belong to this command and Case")
    if mode == "LOCAL_SERVICE" and verdict.get("services_stopped") is not True:
        return fail("local verifier must report owned services stopped")
    checks = verdict["checks"]
    if not isinstance(checks, list) or not checks or not isinstance(verdict["errors"], list):
        return fail("structured report needs executed checks and an errors list")
    if any(not isinstance(check, dict) or not isinstance(check.get("id"), str)
           or not isinstance(check.get("status"), str)
           or check["status"] not in {"PASS", "FAIL", "ERROR", "SKIP"} for check in checks):
        return fail("structured check entry is invalid")
    ids = [check["id"] for check in checks]
    if len(ids) != len(set(ids)) or set(ids) != set(binding["required_checks"]):
        return fail("structured checks do not exactly cover the declared obligations")
    statuses = [check["status"] for check in checks]
    counts = {status: statuses.count(status) for status in ("PASS", "FAIL", "ERROR", "SKIP")}
    if verdict["errors"] or counts["ERROR"] or counts["SKIP"]:
        return {**fail("required checks contain errors or skips"), "resource_check_counts": counts}
    if verdict["status"] == "CHECKS_PASS" and exit_code == 0 and not counts["FAIL"] and not verdict.get("failure_kind"):
        return {"status": "PASS", "automatic_retry_allowed": False, "resource_check_counts": counts,
                "resource_result_reason": "complete bound obligations passed"}
    if verdict["status"] == "CHECKS_FAILED" and exit_code == 1:
        kind = verdict.get("failure_kind")
        if kind == "ASSERTION" and counts["FAIL"]:
            repair = verdict.get("repair_artifact_ids")
            if repair is not None and (not isinstance(repair, list) or not repair
                    or not all(isinstance(item, str) and item for item in repair) or len(repair) != len(set(repair))):
                return fail("repair_artifact_ids is invalid")
            return {"status": "VALIDATION_FAILED", "automatic_retry_allowed": True,
                    "failure_domain": "BUSINESS_ASSERTION", "resource_check_counts": counts,
                    **({"repair_artifact_ids": repair} if repair is not None else {})}
        if kind == "CONTRACT_GAP":
            return {**invalid, "failure_domain": "ACCEPTANCE_CONTRACT_GAP", "resource_check_counts": counts}
    return {**fail("report verdict contradicts exit status or check facts"), "resource_check_counts": counts}


def cleanup_error_details(binding, exc):
    """Cleanup runs after live credentials; never save its arbitrary paths."""
    if not binding["profile"].get("credentials"):
        return {"reason": str(exc)}
    return {"reason": "RESOURCE_CLEANUP_FAILED", "error_type": type(exc).__name__,
            **({"errno": exc.errno} if isinstance(exc, OSError) and type(exc.errno) is int else {})}


def cleanup_resources(binding, success):
    """Call only after durable host collection; failure evidence stays available.

    failure_days is retention metadata for owner-led cleanup, not a background
    sweeper or authorization to delete resources belonging to another command.
    """
    if not success:
        return {"status": "RETAINED", "failure_days": binding["profile"]["retention"]["failure_days"],
                "root": binding["root"]}
    try:
        root = _unlinked(binding["root"])
        leaves = list(binding["areas"].values())
        if "product_copy" in binding:
            product_root = _unlinked(binding["product_copy"]["root"])
            _require(product_root == root / "product", "cleanup may remove only this command's product copy")
            leaves.append(str(product_root))
        for area in leaves:
            path = _unlinked(area)
            _require(path.parent == root, "cleanup may remove only this command's resource leaves")
            if path.exists():
                shutil.rmtree(path)
        return {"status": "CLEANED", "root": str(root)}
    except (OSError, RequestValidationError) as exc:
        return {"status": "CLEANUP_WARNING", "root": binding["root"], **cleanup_error_details(binding, exc)}
