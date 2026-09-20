#!/usr/bin/env python3
"""Assemble a generic archive from an explicit Git commit, not the working tree.

This is a development tool, not release approval or a target Harness builder.
The selected commit's own assembler runs in an isolated tracked-file snapshot.
No checkout, commit, tag, remote operation or extra content hash is performed.
"""

import argparse
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def git(repository, *args, stdout=subprocess.PIPE):
    result = subprocess.run(["git", "-C", str(repository), *args], stdout=stdout,
                            stderr=subprocess.PIPE, check=False, timeout=60)
    if result.returncode:
        raise ValueError("Git source selection failed: " + result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def package_revision(revision, output=None, *, repository=ROOT):
    repository = Path(repository).resolve(strict=True)
    if not isinstance(revision, str) or not revision.strip() or revision.startswith("-"):
        raise ValueError("an explicit Git commit/ref is required")
    commit = git(repository, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode().strip()
    if output is not None:
        output = Path(output)
        if not output.is_absolute() or output.exists() or output.is_symlink() or not output.parent.is_dir():
            raise ValueError("output must be an absent absolute archive in an existing directory")
    with tempfile.TemporaryDirectory(prefix="foundry-committed-source-") as temporary:
        stage = Path(temporary)
        source = stage / "source"
        source.mkdir()
        with tempfile.TemporaryFile() as stream:
            git(repository, "archive", "--format=zip", commit, stdout=stream)
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                # Only build inputs, not Git metadata, private authoring/runs or
                # arbitrary tracked root files. The inner assembler has the
                # narrower final distribution inventory.
                for item in archive.infolist():
                    path = PurePosixPath(item.filename)
                    if path.parts[0] not in {"src", "devtools", "resources", "docs", "examples",
                                             "LICENSE", "pyproject.toml", "FACTORY_MANIFEST.json"}:
                        continue
                    if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(item.external_attr >> 16):
                        raise ValueError("committed build inputs must be contained regular files/directories")
                    archive.extract(item, source)
        builder = source / "devtools/package_generic_release.py"
        if not builder.is_file():
            raise ValueError("selected commit does not contain the generic assembler")
        argv = [sys.executable, "-I", "-S", "-B", str(builder)]
        if output is not None:
            argv += ["--output", str(output)]
        completed = subprocess.run(argv, cwd=source, text=True, capture_output=True,
                                   check=False, timeout=120)
        try:
            result = json.loads(completed.stdout)
        except ValueError as exc:
            raise ValueError("committed assembler returned no readable result: " + completed.stderr[-2000:]) from exc
        expected = "GENERIC_PACKAGE_PREFLIGHT_PASS" if output is None else "GENERIC_ENGINEERING_ARCHIVE_CREATED"
        if completed.returncode or not isinstance(result, dict) or result.get("status") != expected:
            raise ValueError("committed assembler failed: " + json.dumps(result, ensure_ascii=False))
        return {**result, "status": "COMMITTED_SOURCE_PREFLIGHT_PASS" if output is None else "COMMITTED_SOURCE_ARCHIVE_CREATED",
                "source_revision": commit, "source_worktree_used": False,
                "writes_performed": True, "temporary_source_materialized": True,
                "persistent_writes_performed": output is not None,
                "release_accepted": False, "execution_authority_granted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Explicit local Git commit/ref; resolved once before reading.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = package_revision(args.revision, args.output)
    except (OSError, ValueError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        result = {"status": "FAIL", "error": str(exc), "release_accepted": False}
        if args.output is not None:
            result["output_exists"] = args.output.exists()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
