#!/usr/bin/env python3
"""Build an isolated generic engineering archive, not a release acceptance receipt."""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# Reuse only the existing source disclosure checks, not its legacy inventory or hashing.
from harness_foundry_factory.portable import LOCAL_IDENTITY_RE, LOCAL_MACHINE_BINDING_RE, CREDENTIAL_PATTERNS


MODULES = (
    "identity", "build_types", "build_cli", "build_authoring", "build_plan", "build_review",
    "build_runtime", "build_replan", "build_entrypoint", "source_intake", "acceptance_contract", "revision_store",
    "local_process", "coding_process", "coding_events", "process_observation", "legacy_history", "test_execution",
)
DOCS = ("GENERIC_BUILD_PLAN", "GENERIC_BUILD_CLI", "GENERIC_BUILD_RUNTIME",
        "GENERIC_SOURCE_INTAKE", "ACCEPTANCE_CONTRACT_ALIGNMENT")
EXAMPLES = ("task-cli/PRD.md", "csv-increment/PROJECT_BRIEF.md",
            "csv-increment/starter/csv_tool.py", "csv-increment/starter/test_summary.py",
            "csv-increment/starter/USER_NOTES.md")


def literal_assignment(content, name, *, frozen_set=False):
    for node in ast.parse(content).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            value = node.value
            if frozen_set:
                if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                        and value.func.id == "frozenset" and len(value.args) == 1 and not value.keywords):
                    raise ValueError(f"nonliteral release declaration: {name}")
                value = value.args[0]
            result = ast.literal_eval(value)
            if frozen_set and isinstance(result, set) and all(isinstance(item, str) for item in result):
                return sorted(result)
            if not frozen_set and isinstance(result, str) and result:
                return result
    raise ValueError(f"missing or invalid release declaration: {name}")


def collect_files(source_root=ROOT):
    root = Path(source_root).resolve(strict=True)
    sources = {f"src/harness_foundry_factory/{name}.py": f"src/harness_foundry_factory/{name}.py" for name in MODULES}
    sources.update({f"docs/{name}.md": f"docs/{name}.md" for name in DOCS})
    sources.update({f"examples/{name}": f"examples/{name}" for name in EXAMPLES})
    sources.update({"LICENSE": "LICENSE", "AGENTS.md": "resources/generic_release/AGENTS.md",
                    "README.md": "resources/generic_release/README.md",
                    "tools/hffactory.py": "resources/generic_release/hffactory.py",
                    "src/harness_foundry_factory/__init__.py": "resources/generic_release/__init__.py",
                    ".agents/skills/harness-foundry-build/SKILL.md": "resources/generic_release/SKILL.md"})
    files = {}
    for destination, relative in sources.items():
        path = root / relative
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root) or not path.is_file():
            raise ValueError(f"required product resource is not a contained regular file: {relative}")
        content = path.read_bytes()
        text = content.decode("utf-8")
        if (LOCAL_IDENTITY_RE.search(text) or LOCAL_MACHINE_BINDING_RE.search(text)
                or any(pattern.search(text) for pattern in CREDENTIAL_PATTERNS)):
            raise ValueError(f"private identity or credential in release resource: {relative}")
        if destination.endswith(".py") and not destination.startswith("examples/"):
            for node in ast.walk(ast.parse(text, filename=destination)):
                if isinstance(node, ast.ImportFrom) and node.level:
                    if node.level != 1 or node.module not in MODULES:
                        raise ValueError(f"unpackaged local dependency: {relative}: {node.module}")
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module]
                    if any(name.split(".")[0] not in sys.stdlib_module_names | {"harness_foundry_factory"} for name in names):
                        raise ValueError(f"undeclared external Python dependency: {relative}")
                    for name in names:
                        if name.startswith("harness_foundry_factory.") and name.split(".", 1)[1] not in MODULES:
                            raise ValueError(f"unpackaged local dependency: {relative}: {name}")
                    if isinstance(node, ast.ImportFrom) and node.module == "harness_foundry_factory":
                        if any(alias.name not in MODULES for alias in node.names):
                            raise ValueError(f"undeclared package export dependency: {relative}")
        files[destination] = content
    identity = files["src/harness_foundry_factory/identity.py"]
    version = literal_assignment(identity, "FACTORY_VERSION")
    protocol = literal_assignment(identity, "TARGET_PROTOCOL_VERSION")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("project", {})
    product = json.loads((root / "FACTORY_MANIFEST.json").read_text(encoding="utf-8"))
    if project.get("version") != version or product.get("version") != version:
        raise ValueError("product version differs between identity, pyproject and Factory manifest")
    if product.get("target_protocol_version") != protocol:
        raise ValueError("protocol version differs between identity and Factory manifest")
    if project.get("license") != "MIT" or project.get("license-files") != ["LICENSE"]:
        raise ValueError("the selected source does not declare the approved MIT distribution license")
    commands = literal_assignment(files["src/harness_foundry_factory/build_cli.py"], "BUILD_COMMANDS", frozen_set=True)
    manifest = {"schema_version": "1.0", "package_kind": "GENERIC_FOUNDRY_RUNTIME",
                "implementation_version": version,
                "target_protocol_version": protocol,
                "commands": ["version", *commands], "storage_format": "REVISION_V1",
                "python_requires": ">=3.11", "third_party_python_dependencies": [],
                "native_receiver": "USER_PROVIDED_CODEX_WITH_EXPLICIT_SCOPE",
                "license": "MIT", "repository": "https://github.com/alexYG-arch/Harness_Foundry",
                "files": sorted([*files, "PACKAGE_MANIFEST.json"]),
                "acceptance_claimed": False, "execution_authority_granted": False}
    files["PACKAGE_MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    return files


def package(output=None, *, source_root=ROOT):
    files = collect_files(source_root)
    result = {"status": "GENERIC_PACKAGE_PREFLIGHT_PASS", "file_count": len(files),
              "files": sorted(files), "writes_performed": False, "release_accepted": False}
    if output is None:
        return result
    output = Path(output)
    if not output.is_absolute() or output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("output must be an absent absolute archive in an existing directory")
    # Atomic no-overwrite publication on the same filesystem; only the final
    # archive gets H1 identity. No per-file digests or nested receipt hashes.
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".foundry-package-") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative, content in sorted(files.items()):
                info = zipfile.ZipInfo(relative)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, content)
        stream.flush()
        os.fsync(stream.fileno())
        os.link(stream.name, output)
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {**result, "status": "GENERIC_ENGINEERING_ARCHIVE_CREATED", "archive": str(output),
            "archive_sha256": digest, "writes_performed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = package(args.output)
    except (OSError, ValueError) as exc:
        result = {"status": "FAIL", "error": str(exc), "release_accepted": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
