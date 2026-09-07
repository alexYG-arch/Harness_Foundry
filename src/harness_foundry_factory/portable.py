"""Portable local packaging and diagnostic-only self-checks for v2.9."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from .constants import (
    FACTORY_ID,
    FACTORY_VERSION,
    HF28_PACKAGE_ID,
    TARGET_PROTOCOL_VERSION,
    project_root,
)


PORTABLE_MANIFEST_NAME = "PORTABLE_LOCAL_PACKAGE_MANIFEST.json"
PACKAGE_ROOT_URI = "harness-resource://package"
ASSURANCE_PROFILE = "SELF_USE_LOCAL_TRUSTED_OPERATOR"
ALLOWED_TOP_LEVEL_FILES = (
    "AGENTS.md",
    "FACTORY_MANIFEST.json",
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/CHAT_USAGE.md",
    "pyproject.toml",
)
ALLOWED_TREES = (
    (".agents", {".md", ".yaml", ".yml", ".json"}),
    ("schemas", {".json"}),
    ("spec_lock", {".json"}),
    ("src/harness_foundry_factory", {".py"}),
    ("tools", {".py"}),
)
# One route declaration feeds both import discovery and the portable manifest.
# Package names equal import names for these three explicitly supported extras.
OPTIONAL_PYTHON_DEPENDENCIES = (
    {
        "dependency_id": "cryptography",
        "version_constraint": ">=45,<49",
        "extra": "security",
        "profile": "OPTIONAL_SECURITY_HARDENING_AND_LEGACY_CANDIDATE_VALIDATION",
        "required_for_commands": ["candidate-authoring", "validate-candidate"],
    },
    {
        "dependency_id": "jsonschema",
        "version_constraint": ">=4.18,<5",
        "extra": "runtime-audit",
        "profile": "OPTIONAL_WORKPACK_SCHEMA_AUDIT",
        "required_for_commands": ["audit-completion"],
    },
    {
        "dependency_id": "referencing",
        "version_constraint": ">=0.28,<1",
        "extra": "runtime-audit",
        "profile": "OPTIONAL_WORKPACK_SCHEMA_AUDIT",
        "required_for_commands": ["audit-completion"],
    },
)
EXCLUDED_SURFACES = (
    ".git",
    "AUTHORITY_TRUST_ROOT.json",
    "historical and review docs except docs/ARCHITECTURE.md and docs/CHAT_USAGE.md",
    "runs",
    "tests",
    "__pycache__",
    "*.pyc",
    "Candidate roots",
    "Execution roots",
    "Factory SQLite and Event Ledger",
    "credentials and local machine bindings",
)
LOCAL_IDENTITY_RE = re.compile(
    r"(?:/Users|/home)/[A-Za-z0-9._-]+/|"
    r"[A-Za-z]:\\\\Users\\\\[^\\\s]+\\\\|"
    r"file:///(?:Users|home)/"
)
LOCAL_MACHINE_BINDING_RE = re.compile(
    r"/(?:opt/homebrew|usr/local/(?:Cellar|Homebrew)|Applications|"
    r"(?:private/)?var/folders)/"
)
CREDENTIAL_PATTERNS = (
    re.compile("-----BEGIN " + "PRIVATE KEY-----"),
    re.compile("-----BEGIN " + "RSA PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{16,}"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:]+:[^\s/@]+@"),
)


class PortablePackageError(RuntimeError):
    """Fail-closed portable package error with one stable reason code."""

    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def package_local(
    output_root: str | Path | None,
    *,
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    """Preflight and optionally atomically publish one local portable package."""

    source = _physical_directory(source_root or project_root(), "SOURCE_ROOT_INVALID")
    files = _collect_source_files(source)
    scan = _scan_source(source, files)
    manifest = _build_manifest(source, files, scan)
    if output_root is None:
        return {
            "schema_version": "2.9",
            "status": "PREFLIGHT_PASS",
            "factory_id": FACTORY_ID,
            "manifest": manifest,
            "writes_performed": False,
            "startup_smoke": None,
            "security_authority": False,
            "certification_claimed": False,
        }

    target = _new_output_path(output_root, source)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)
    )
    published = False
    try:
        for relative in files:
            source_file = source / relative
            target_file = staging / relative
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file, follow_symlinks=False)
        _write_json(staging / PORTABLE_MANIFEST_NAME, manifest)
        diagnostic = self_check_diagnostic(staging)
        if diagnostic["status"] != "PASS":
            raise PortablePackageError(
                "PACKAGE_SELF_CHECK_FAILED",
                "Staged portable package did not pass its diagnostic self-check",
                details={"findings": diagnostic["findings"]},
            )
        smoke = _startup_smoke(staging)
        if target.exists() or target.is_symlink():
            raise PortablePackageError(
                "OUTPUT_COLLISION", "Portable output appeared before publication"
            )
        staging.rename(target)
        published = True
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)

    return {
        "schema_version": "2.9",
        "status": "PASS",
        "factory_id": FACTORY_ID,
        "package_root": str(target),
        "package_root_local_only": True,
        "manifest_sha256": manifest["manifest_sha256"],
        "file_count": len(manifest["files"]) + 1,
        "startup_smoke": smoke,
        "writes_performed": True,
        "security_authority": False,
        "certification_claimed": False,
    }


def self_check_diagnostic(package_root: str | Path) -> dict[str, Any]:
    """Diagnose package integrity and portability without creating authority."""

    findings: list[dict[str, Any]] = []
    try:
        root = _physical_directory(package_root, "PACKAGE_ROOT_INVALID")
    except PortablePackageError as exc:
        findings.append({"code": exc.code, "message": exc.message})
        return _diagnostic_result(None, findings, None)

    manifest_path = root / PORTABLE_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        findings.append(
            {"code": "PORTABLE_MANIFEST_INVALID", "message": str(exc)}
        )
        return _diagnostic_result(root, findings, None)
    if not isinstance(manifest, dict):
        findings.append(
            {
                "code": "PORTABLE_MANIFEST_INVALID",
                "message": "manifest must contain one JSON object",
            }
        )
        return _diagnostic_result(root, findings, None)

    claimed_manifest_sha256 = manifest.get("manifest_sha256")
    manifest_material = dict(manifest)
    manifest_material.pop("manifest_sha256", None)
    if claimed_manifest_sha256 != _content_sha256(manifest_material):
        findings.append(
            {
                "code": "PORTABLE_MANIFEST_HASH_MISMATCH",
                "message": "diagnostic manifest Hash does not verify",
            }
        )
    if (
        manifest.get("factory_id") != FACTORY_ID
        or manifest.get("assurance_profile") != ASSURANCE_PROFILE
        or manifest.get("security_authority") is not False
        or manifest.get("certification_claimed") is not False
        or manifest.get("logical_roots") != {"package": PACKAGE_ROOT_URI}
    ):
        findings.append(
            {
                "code": "PORTABLE_MANIFEST_IDENTITY_INVALID",
                "message": "manifest identity or diagnostic boundary is invalid",
            }
        )

    declared_files = manifest.get("files")
    if not isinstance(declared_files, dict):
        findings.append(
            {
                "code": "PORTABLE_INVENTORY_INVALID",
                "message": "manifest files must be an object",
            }
        )
        declared_files = {}
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    expected_files = set(declared_files) | {PORTABLE_MANIFEST_NAME}
    if actual_files != expected_files:
        findings.append(
            {
                "code": "PORTABLE_INVENTORY_MISMATCH",
                "message": "package files differ from the declared inventory",
                "missing": sorted(expected_files - actual_files),
                "unexpected": sorted(actual_files - expected_files),
            }
        )
    verified_relatives: list[str] = []
    for relative, declaration in declared_files.items():
        if not isinstance(relative, str):
            findings.append(
                {
                    "code": "PORTABLE_INVENTORY_INVALID",
                    "message": "file inventory keys must be strings",
                }
            )
            continue
        try:
            path = resolve_logical_resource_uri(
                root, f"{PACKAGE_ROOT_URI}/{relative}", require_file=True
            )
        except PortablePackageError as exc:
            findings.append(
                {"code": exc.code, "message": exc.message, "path": relative}
            )
            continue
        verified_relatives.append(relative)
        if not isinstance(declaration, Mapping):
            findings.append(
                {
                    "code": "PORTABLE_INVENTORY_INVALID",
                    "message": "file declaration must be an object",
                    "path": relative,
                }
            )
            continue
        if (
            declaration.get("sha256") != _file_sha256(path)
            or declaration.get("size") != path.stat().st_size
        ):
            findings.append(
                {
                    "code": "PORTABLE_FILE_HASH_MISMATCH",
                    "message": "file content differs from the manifest",
                    "path": relative,
                }
            )

    if verified_relatives:
        try:
            scan = _scan_source(root, sorted(verified_relatives))
            if manifest.get("dependency_discovery") != scan:
                findings.append(
                    {
                        "code": "DEPENDENCY_DISCOVERY_MISMATCH",
                        "message": "declared dependency discovery is stale",
                    }
                )
            if manifest.get("dependencies") != _declared_dependencies(root):
                findings.append(
                    {
                        "code": "DEPENDENCY_DECLARATION_MISMATCH",
                        "message": "portable dependencies differ from the source route declarations",
                    }
                )
        except PortablePackageError as exc:
            findings.append(
                {"code": exc.code, "message": exc.message, **exc.details}
            )
    dependencies = _dependency_availability(manifest.get("dependencies"))
    return _diagnostic_result(root, findings, dependencies)


def resolve_logical_resource_uri(
    package_root: str | Path,
    uri: str,
    *,
    require_file: bool = False,
) -> Path:
    """Resolve the one package logical root with traversal and symlink guards."""

    root = _physical_directory(package_root, "PACKAGE_ROOT_INVALID")
    parsed = urlsplit(uri)
    decoded_path = unquote(parsed.path)
    segments = decoded_path[1:].split("/") if decoded_path.startswith("/") else []
    if (
        parsed.scheme != "harness-resource"
        or parsed.netloc != "package"
        or parsed.query
        or parsed.fragment
        or decoded_path != parsed.path
        or "\\" in decoded_path
        or decoded_path.startswith("//")
        or (decoded_path and not decoded_path.startswith("/"))
        or any(segment in {"", ".", ".."} for segment in segments)
    ):
        raise PortablePackageError(
            "LOGICAL_RESOURCE_URI_INVALID", "Resource URI is not canonical"
        )
    parts = tuple(segments)
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise PortablePackageError(
                "EXTERNAL_SYMLINK",
                "Resource URI crosses a symbolic link",
                details={"path": current.relative_to(root).as_posix()},
            )
    resolved = candidate.resolve(strict=require_file)
    if not resolved.is_relative_to(root):
        raise PortablePackageError(
            "PATH_CONTAINMENT_FAILED", "Resource URI resolves outside package"
        )
    if require_file and not resolved.is_file():
        raise PortablePackageError(
            "PORTABLE_FILE_MISSING", "Resource URI does not resolve to a file"
        )
    return resolved


def _collect_source_files(root: Path) -> list[str]:
    files: set[str] = set()
    for relative in ALLOWED_TOP_LEVEL_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise PortablePackageError(
                "PORTABLE_REQUIRED_FILE_MISSING",
                "Required portable product file is missing or linked",
                details={"path": relative},
            )
        files.add(relative)
    for tree, suffixes in ALLOWED_TREES:
        tree_root = root / tree
        if not tree_root.is_dir() or tree_root.is_symlink():
            raise PortablePackageError(
                "PORTABLE_REQUIRED_TREE_MISSING",
                "Required portable product tree is missing or linked",
                details={"path": tree},
            )
        for path in tree_root.rglob("*"):
            if path.is_symlink():
                raise PortablePackageError(
                    "EXTERNAL_SYMLINK",
                    "Portable package cannot include symbolic links",
                    details={"path": path.relative_to(root).as_posix()},
                )
            if path.is_file() and path.suffix in suffixes:
                files.add(path.relative_to(root).as_posix())
    return sorted(files)


def _scan_source(root: Path, files: list[str]) -> dict[str, Any]:
    python_files = [relative for relative in files if relative.endswith(".py")]
    local_modules = _local_module_names(python_files)
    external_imports: set[str] = set()
    local_imports: set[str] = set()
    for relative in files:
        path = root / relative
        if path.is_symlink():
            raise PortablePackageError(
                "EXTERNAL_SYMLINK",
                "Portable package cannot include symbolic links",
                details={"path": relative},
            )
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise PortablePackageError(
                "PORTABLE_TEXT_INVALID",
                "Portable text file is not UTF-8",
                details={"path": relative, "error": str(exc)},
            ) from exc
        if LOCAL_IDENTITY_RE.search(text):
            raise PortablePackageError(
                "LOCAL_IDENTITY_EXPORT",
                "Portable source contains a resolved user-machine identity",
                details={"path": relative},
            )
        if LOCAL_MACHINE_BINDING_RE.search(text):
            raise PortablePackageError(
                "LOCAL_MACHINE_BINDING_EXPORT",
                "Portable source contains a resolved machine-local path",
                details={"path": relative},
            )
        if any(pattern.search(text) for pattern in CREDENTIAL_PATTERNS):
            raise PortablePackageError(
                "CREDENTIAL_DISCLOSURE",
                "Portable source contains credential-like material",
                details={"path": relative},
            )
        if not relative.endswith(".py"):
            continue
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError as exc:
            raise PortablePackageError(
                "PORTABLE_PYTHON_INVALID",
                "Portable Python source does not parse",
                details={"path": relative, "error": str(exc)},
            ) from exc
        current_module = _module_name(relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _classify_import(
                        alias.name.split(".", 1)[0],
                        local_modules,
                        local_imports,
                        external_imports,
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    targets = _relative_import_targets(
                        current_module, relative, node
                    )
                    if not targets or not any(
                        target in local_modules for target in targets
                    ):
                        raise PortablePackageError(
                            "LOCAL_DEPENDENCY_MISSING",
                            "Relative Python dependency is outside the package inventory",
                            details={"path": relative, "module": node.module},
                        )
                    local_imports.update(targets & local_modules)
                elif node.module:
                    _classify_import(
                        node.module.split(".", 1)[0],
                        local_modules,
                        local_imports,
                        external_imports,
                    )
    declared = {item["dependency_id"] for item in _optional_python_dependencies(root)}
    undeclared = external_imports - declared
    if undeclared:
        raise PortablePackageError(
            "UNDECLARED_RUNTIME_DEPENDENCY",
            "Python source imports an undeclared external package",
            details={"imports": sorted(undeclared)},
        )
    return {
        "python_file_count": len(python_files),
        "stdlib_imports_only_for_core_startup": True,
        "local_module_count": len(local_modules),
        "local_imports": sorted(local_imports),
        "external_imports": sorted(external_imports),
        "undeclared_external_imports": [],
    }


def _optional_python_dependencies(root: Path) -> list[dict[str, Any]]:
    """Verify that every portable optional route is installable via its extra."""
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        extras = project["project"]["optional-dependencies"]
        if not isinstance(extras, dict):
            raise ValueError("optional-dependencies must be a table")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PortablePackageError(
            "OPTIONAL_DEPENDENCY_DECLARATION_INVALID", "Cannot read optional dependency extras"
        ) from exc
    result = []
    for item in OPTIONAL_PYTHON_DEPENDENCIES:
        requirement = item["dependency_id"] + item["version_constraint"]
        declarations = extras.get(item["extra"], [])
        if not isinstance(declarations, list) or requirement not in declarations:
            raise PortablePackageError(
                "OPTIONAL_DEPENDENCY_DECLARATION_INVALID",
                "Portable dependency must match its pyproject optional extra",
                details={"extra": item["extra"], "requirement": requirement},
            )
        result.append({**item, "kind": "OPTIONAL_PYTHON_PACKAGE",
                       "required_for_core_startup": False,
                       "discovery": "importlib.util.find_spec"})
    return result


def _declared_dependencies(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "dependency_id": "python", "kind": "RUNTIME",
            "version_constraint": ">=3.11,<4", "required_for_core_startup": True,
            "discovery": "sys.version_info",
        },
        *_optional_python_dependencies(root),
        {
            "dependency_id": HF28_PACKAGE_ID,
            "kind": "OPTIONAL_PHYSICAL_SIBLING_PACKAGE",
            "physical_sibling_name": "Harness_Foundry_v2_8_Start_Package",
            "required_for_core_startup": False,
            "required_for_commands": ["verify-spec", "candidate-authoring"],
            "discovery": "package_root.parent / physical_sibling_name",
        },
    ]


def _build_manifest(
    root: Path, files: list[str], dependency_discovery: Mapping[str, Any]
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": "2.9",
        "manifest_kind": "PORTABLE_LOCAL_PACKAGE_DIAGNOSTIC_MANIFEST",
        "factory_id": FACTORY_ID,
        "target_protocol_version": TARGET_PROTOCOL_VERSION,
        "implementation_version": FACTORY_VERSION,
        "assurance_profile": ASSURANCE_PROFILE,
        "logical_roots": {"package": PACKAGE_ROOT_URI},
        "files": {
            relative: {
                "sha256": _file_sha256(root / relative),
                "size": (root / relative).stat().st_size,
            }
            for relative in files
        },
        "dependencies": _declared_dependencies(root),
        "dependency_discovery": dict(dependency_discovery),
        "entrypoints": [
            {
                "command": ["python3", "tools/hffactory.py", "version", "--json"],
                "authority": "PRODUCT_IDENTITY_ONLY",
            },
            {
                "command": [
                    "python3",
                    "tools/hffactory.py",
                    "self-check-diagnostic",
                    "--package-root",
                    ".",
                    "--json",
                ],
                "authority": "DIAGNOSTIC_ONLY_NOT_SECURITY_AUTHORITY",
            },
        ],
        "exclusions": list(EXCLUDED_SURFACES),
        "security_authority": False,
        "certification_claimed": False,
        "candidate_self_proof_claimed": False,
        "writes_outside_package_output": False,
    }
    manifest["manifest_sha256"] = _content_sha256(manifest)
    return manifest


def _startup_smoke(root: Path) -> dict[str, Any]:
    commands = (
        [sys.executable, "-B", "tools/hffactory.py", "version", "--json"],
        [
            sys.executable,
            "-B",
            "tools/hffactory.py",
            "self-check-diagnostic",
            "--package-root",
            ".",
            "--json",
        ],
    )
    results: list[dict[str, Any]] = []
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("PYTHONPATH", None)
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        try:
            output = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise PortablePackageError(
                "LOCAL_STARTUP_SMOKE_FAILED",
                "Packaged CLI did not emit JSON",
                details={"stderr": completed.stderr, "error": str(exc)},
            ) from exc
        if completed.returncode != 0 or output.get("status") != "PASS":
            raise PortablePackageError(
                "LOCAL_STARTUP_SMOKE_FAILED",
                "Packaged CLI startup smoke failed",
                details={
                    "returncode": completed.returncode,
                    "output": output,
                    "stderr": completed.stderr,
                },
            )
        results.append(
            {
                "entrypoint": command[3],
                "status": "PASS",
                "writes_performed": output.get("writes_performed", False),
            }
        )
    return {
        "status": "PASS",
        "relocated_package": True,
        "editable_install_used": False,
        "network_used": False,
        "checks": results,
    }


def _dependency_availability(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, Any]] = []
    for dependency in value:
        if not isinstance(dependency, Mapping):
            continue
        dependency_id = dependency.get("dependency_id")
        available: bool | None
        if dependency_id == "python":
            available = sys.version_info >= (3, 11) and sys.version_info < (4, 0)
        elif dependency.get("kind") == "OPTIONAL_PYTHON_PACKAGE":
            available = importlib.util.find_spec(str(dependency_id)) is not None
        else:
            available = None
        results.append(
            {
                "dependency_id": dependency_id,
                "required_for_core_startup": bool(
                    dependency.get("required_for_core_startup")
                ),
                "available": available,
            }
        )
    return results


def _diagnostic_result(
    root: Path | None,
    findings: list[dict[str, Any]],
    dependencies: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    required_missing = any(
        item.get("required_for_core_startup") and item.get("available") is False
        for item in dependencies or []
    )
    if required_missing:
        findings.append(
            {
                "code": "REQUIRED_RUNTIME_DEPENDENCY_MISSING",
                "message": "A core startup dependency is unavailable",
            }
        )
    return {
        "schema_version": "2.9",
        "status": "PASS" if not findings else "FAIL",
        "check_kind": "DIAGNOSTIC_ONLY_NOT_SECURITY_AUTHORITY",
        "factory_id": FACTORY_ID,
        "package_root": str(root) if root is not None else None,
        "package_root_local_only": True,
        "findings": findings,
        "dependencies": dependencies or [],
        "writes_performed": False,
        "security_authority": False,
        "certification_claimed": False,
        "candidate_self_proof_claimed": False,
    }


def _new_output_path(output_root: str | Path, source: Path) -> Path:
    raw = Path(output_root).expanduser()
    if raw.name in {"", ".", ".."}:
        raise PortablePackageError("OUTPUT_PATH_INVALID", "Output path is invalid")
    try:
        parent = raw.parent.resolve(strict=True)
    except OSError as exc:
        raise PortablePackageError(
            "OUTPUT_PARENT_MISSING", "Output parent must already exist"
        ) from exc
    target = parent / raw.name
    if target.exists() or target.is_symlink():
        raise PortablePackageError(
            "OUTPUT_COLLISION", "Portable output must not already exist"
        )
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise PortablePackageError(
            "OUTPUT_OVERLAP", "Portable output must be disjoint from source"
        )
    return target


def _physical_directory(value: str | Path, code: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise PortablePackageError(code, "Directory root cannot be a symbolic link")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PortablePackageError(code, "Directory root does not exist") from exc
    if not resolved.is_dir():
        raise PortablePackageError(code, "Directory root is not a directory")
    return resolved


def _module_name(relative: str) -> str:
    path = PurePosixPath(relative)
    parts = list(path.with_suffix("").parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _local_module_names(python_files: list[str]) -> set[str]:
    names: set[str] = set()
    for relative in python_files:
        module = _module_name(relative)
        if module:
            names.add(module)
            parts = module.split(".")
            for index in range(1, len(parts)):
                names.add(".".join(parts[:index]))
    return names


def _relative_import_targets(
    current_module: str, relative: str, node: ast.ImportFrom
) -> set[str]:
    current_parts = current_module.split(".")
    package_parts = (
        current_parts
        if PurePosixPath(relative).name == "__init__.py"
        else current_parts[:-1]
    )
    ascents = node.level - 1
    if ascents > len(package_parts):
        return set()
    base = package_parts[: len(package_parts) - ascents]
    if node.module:
        return {".".join(base + node.module.split("."))}
    return {".".join(base + [alias.name]) for alias in node.names}


def _classify_import(
    root_name: str,
    local_modules: set[str],
    local_imports: set[str],
    external_imports: set[str],
) -> None:
    if root_name in sys.stdlib_module_names:
        return
    if root_name in {name.split(".", 1)[0] for name in local_modules}:
        local_imports.add(root_name)
        return
    external_imports.add(root_name)


def _content_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
