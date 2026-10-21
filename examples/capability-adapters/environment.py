"""Resolve selected local dependencies; never install or execute them.

An executable's bare name uses PATH; ``./name`` and other relative paths use
the explicit project root. Executable aliases are kept for invocation (notably
venv Python); their real paths are separate facts. Versions are caller reports,
not receiver observations. Numeric bounds compare numeric release versions
only: pre-release/vendor strings remain unconfirmed, never silently truncated.

CLI: environment.py --requirements FILE --bindings FILE --project-root DIR
The JSON result is preparation material, not authority or runtime acceptance.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil


def _numeric_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value):
        return None
    parts = tuple(int(part) for part in value.split("."))
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def _version_check(requirement, binding, report):
    bounds = {}
    for field in ("version_min", "version_max_exclusive"):
        if field in requirement:
            bounds[field] = _numeric_version(requirement[field])
            if bounds[field] is None:
                report("INVALID_VERSION_RANGE", field + " must be a numeric release version")
                return False
    if (len(bounds) == 2 and bounds["version_min"] >= bounds["version_max_exclusive"]):
        report("INVALID_VERSION_RANGE", "version_min must be less than version_max_exclusive")
        return False
    observed = binding.get("observed_version")
    if observed is None:
        report("VERSION_UNKNOWN", "No version was supplied; no version probe was executed",
               "ERROR" if bounds else "INFO")
        return not bounds
    if not isinstance(observed, str) or not observed.strip():
        report("INVALID_VERSION_REPORT", "observed_version must be a nonempty string or null")
        return False
    if not bounds:
        return True
    version = _numeric_version(observed)
    if version is None:
        report("VERSION_NOT_COMPARABLE", "Reported version is not a numeric release; pre-release/vendor text is not a final release")
        return False
    if ("version_min" in bounds and version < bounds["version_min"]
            or "version_max_exclusive" in bounds and version >= bounds["version_max_exclusive"]):
        report("VERSION_INCOMPATIBLE", "Reported version is outside the declared numeric range")
        return False
    return True


def resolve_environment(requirements, bindings, *, project_root):
    """Return path facts, a partial scope fragment and explicit local diagnostics.

    Only individually resolved requirements enter the fragment. READY means
    material preparation only; even a matching supplied version is not proof
    that the selected tool works in a receiver. Unselected bindings are ignored.
    """
    result = {"status": "READY", "bindings": {},
              "scope_fragment": {"executables": {}, "source_read_roots": []},
              "diagnostics": [], "receiver_verified": False, "probes_executed": False}

    def report(identity, code, message, severity="ERROR"):
        result["diagnostics"].append({"id": identity, "code": code,
                                      "message": message, "severity": severity})
        if severity == "ERROR":
            result["status"] = "INCOMPLETE"

    try:
        root = Path(project_root)
        if not root.is_absolute():
            raise ValueError("project_root must be explicit and absolute")
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("project_root must be an existing directory")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        report(None, "PROJECT_ROOT_INVALID", str(exc))
        return result
    result["project_root"] = str(root)
    if not isinstance(requirements, list) or not isinstance(bindings, dict):
        report(None, "INVALID_INPUT", "requirements must be a list and bindings must be an object")
        return result
    ids = [item.get("id") for item in requirements if isinstance(item, dict)]
    seen = set()
    for requirement in requirements:
        if not isinstance(requirement, dict):
            report(None, "INVALID_REQUIREMENT", "each requirement must be an object")
            continue
        identity = requirement.get("id")
        if not isinstance(identity, str) or not identity.strip():
            report(None, "INVALID_REQUIREMENT", "each requirement needs a nonempty id")
            continue
        if identity in seen:
            continue
        seen.add(identity)
        if ids.count(identity) != 1:
            report(identity, "DUPLICATE_REQUIREMENT", "a dependency id must have one unambiguous requirement")
            continue
        kind = requirement.get("kind")
        if kind not in ("executable", "directory", "file"):
            report(identity, "INVALID_REQUIREMENT", "kind must be executable, directory or file")
            continue
        if set(requirement) - {"id", "kind", "version_min", "version_max_exclusive"}:
            report(identity, "INVALID_REQUIREMENT", "requirement has unsupported fields")
            continue
        binding = bindings.get(identity)
        if not isinstance(binding, dict) or "path" not in binding:
            report(identity, "BINDING_MISSING", "supply a binding with a path for this dependency")
            continue
        supplied = binding["path"]
        if not isinstance(supplied, str) or not supplied or any(ord(char) < 32 for char in supplied):
            report(identity, "INVALID_PATH", "path must be a nonempty string without control characters")
            continue
        facts = {"kind": kind, "path": supplied, "absolute_path": None,
                 "resolved_path": None, "resolution": "PROJECT_PATH",
                 "observed_version": binding.get("observed_version"),
                 "version_source": "SUPPLIED_BINDING" if binding.get("observed_version") is not None else "NOT_SUPPLIED",
                 "receiver_verified": False}
        result["bindings"][identity] = facts
        diagnostic = lambda code, message, severity="ERROR": report(identity, code, message, severity)
        version_ok = _version_check(requirement, binding, diagnostic)
        bare_name = kind == "executable" and supplied not in (".", "..") and not Path(supplied).is_absolute() and not any(
            separator in supplied for separator in (os.sep, os.altsep) if separator)
        if bare_name:
            # Relative PATH entries also use the explicit project root, not cwd.
            search = os.pathsep.join(str(Path(item) if Path(item).is_absolute() else root / item)
                                     for item in os.environ.get("PATH", os.defpath).split(os.pathsep))
            found = shutil.which(supplied, path=search)
            facts["resolution"] = "PATH_NAME"
            if found is None:
                report(identity, "EXECUTABLE_NOT_FOUND", "selected executable name was not found as executable on PATH")
                continue
            path = Path(found)
        else:
            path = Path(supplied) if Path(supplied).is_absolute() else root / supplied
        facts["absolute_path"] = str(path)
        try:
            # Resolve parents before eliminating '..': lexical normalization
            # across a symlink could otherwise select a different dependency.
            # Keep the final executable alias, including a venv's Python link.
            if ".." in path.parts:
                path = path.parent.resolve(strict=True) / path.name
                facts["absolute_path"] = str(path)
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            linked = any(part.is_symlink() for part in (path, *path.parents))
            report(identity, "BROKEN_SYMLINK" if linked else "PATH_MISSING",
                   "selected path does not resolve to an existing dependency")
            continue
        except (OSError, RuntimeError) as exc:
            report(identity, "PATH_UNRESOLVABLE", "selected path cannot be resolved: " + type(exc).__name__)
            continue
        facts["resolved_path"] = str(resolved)
        if not (resolved.is_dir() if kind == "directory" else resolved.is_file()):
            report(identity, "PATH_KIND_MISMATCH", "resolved dependency is not the declared kind")
            continue
        if kind == "executable" and not os.access(path, os.X_OK):
            report(identity, "NOT_EXECUTABLE", "selected file has no execute permission for this host")
            continue
        if kind != "executable" and not os.access(resolved, os.R_OK | (os.X_OK if kind == "directory" else 0)):
            report(identity, "NOT_READABLE", "selected dependency is not readable/searchable for this host")
            continue
        if version_ok:
            if kind == "executable":
                result["scope_fragment"]["executables"][identity] = str(path)
            elif str(resolved) not in result["scope_fragment"]["source_read_roots"]:
                result["scope_fragment"]["source_read_roots"].append(str(resolved))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    try:
        result = resolve_environment(json.loads(Path(args.requirements).read_text(encoding="utf-8")),
                                     json.loads(Path(args.bindings).read_text(encoding="utf-8")),
                                     project_root=args.project_root)
    except (OSError, ValueError) as exc:
        result = {"status": "INCOMPLETE", "diagnostics": [
            {"id": None, "code": "INPUT_UNREADABLE", "message": str(exc), "severity": "ERROR"}],
            "receiver_verified": False, "probes_executed": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
