#!/usr/bin/env python3
"""Package one explicitly selected Foundry reference capability; never install it.

The candidate is host-side source, including declared checker code. It is not a
producer delivery or a project-private expectation bundle. Use prepare/consume
and the original delivery boundary after extraction on the receiving machine.
"""

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_archive = _load("capability_candidate_archive", ROOT / "devtools/package_generic_release.py")
_prepare = _load("capability_candidate_paths", ROOT / "examples/capability-adapters/prepare.py")
MANIFEST = "CAPABILITY_PACKAGE_MANIFEST.json"


def collect_capability(directory, version):
    root = Path(directory).resolve(strict=True)
    descriptor = _prepare._file(root, "capability.json").read_bytes()
    package = json.loads(descriptor)
    name = _prepare._id(package["name"])
    if not isinstance(version, str) or not version or package["version"] != version:
        raise ValueError("selected version differs from capability.json: " + name)
    declared = {"capability.json", *package.get("materials", []), *package.get("runtime_files", []),
                *(tool["path"] for tool in package.get("tools", [])),
                *(row if isinstance(row, str) else row["path"] for row in package.get("verification_files", []))}
    if MANIFEST in declared:
        raise ValueError("candidate manifest conflicts with a declared capability file")
    files = {relative: descriptor if relative == "capability.json" else
             _prepare._file(root, relative).read_bytes() for relative in sorted(declared)}
    files.setdefault("LICENSE", (ROOT / "LICENSE").read_bytes())
    for relative, raw in files.items():
        text = raw.decode("utf-8", errors="ignore")
        if (_archive.LOCAL_IDENTITY_RE.search(text) or _archive.LOCAL_MACHINE_BINDING_RE.search(text)
                or any(pattern.search(text) for pattern in _archive.CREDENTIAL_PATTERNS)):
            raise ValueError("private identity or credential in capability resource: " + relative)
    manifest = {"schema_version": "1.0", "package_kind": "FOUNDRY_REFERENCE_CAPABILITY_CANDIDATE",
                "name": name, "version": version, "target_protocol_version": "2.9",
                "source_mode": "EXPLICIT_DIRECTORY_SNAPSHOT", "files": sorted([*files, MANIFEST]),
                "verification_files": package.get("verification_files", []),
                "environment": package.get("environment", []),
                "acceptance_claimed": False, "execution_authority_granted": False,
                "runtime_verified": False}
    files[MANIFEST] = _prepare._json(manifest)
    return files


def package_capability(directory, version, output=None):
    files = collect_capability(directory, version)
    manifest = json.loads(files[MANIFEST])
    result = {"status": "CAPABILITY_CANDIDATE_PREFLIGHT_PASS", "name": manifest["name"],
              "version": version, "file_count": len(files), "files": sorted(files),
              "writes_performed": False, "release_accepted": False,
              "execution_authority_granted": False, "runtime_verified": False}
    if output is None:
        return result
    return {**result, **_archive.write_archive(files, output), "status": "CAPABILITY_CANDIDATE_CREATED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = package_capability(args.directory, args.version, args.output)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        result = {"status": "FAIL", "error": str(exc), "release_accepted": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
