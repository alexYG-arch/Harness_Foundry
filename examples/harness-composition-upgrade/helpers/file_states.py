"""Ordinary-file comparison utilities for the isolated R3 examples.

These helpers do not read or write Harness control state or acceptance records.
Only bytes, existence, and the executable bit are part of a file state.
"""

import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
import unicodedata


class PlanError(ValueError):
    pass


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise PlanError("expected a nonempty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise PlanError("path must be relative without dot or empty components: " + value)
    return path


def beneath(root, relative):
    """Reject symlinks/non-directory ancestors inside the declared file root."""
    relative = relative_path(relative)
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise PlanError("symlink is outside the ordinary-file helper scope: " + str(current))
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
            raise PlanError("non-directory ancestor: " + str(current))
        if index == len(relative.parts) - 1 and not stat.S_ISREG(mode):
            raise PlanError("non-regular file: " + str(current))
    return current


def read_current(path):
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(mode):
        raise PlanError("non-regular file: " + str(path))
    return (path.read_bytes(), bool(mode & 0o111))


def load_state(value, root):
    if isinstance(value, dict) and set(value) == {"missing"} and value["missing"] is True:
        return None, None
    if not isinstance(value, dict) or set(value) != {"file", "executable"}:
        raise PlanError("state must be {missing: true} or {file, executable}")
    if type(value["executable"]) is not bool:
        raise PlanError("state executable must be boolean")
    # Read references can legitimately point to sibling fixed input roots.
    # The runtime's declared read scope remains the authority; these helpers
    # do not invent a new global read root. Write paths use relative_path().
    reference = value["file"]
    if not isinstance(reference, str) or not reference or "\\" in reference or Path(reference).is_absolute():
        raise PlanError("payload reference must be a relative file path")
    source = root
    parts = Path(reference).parts
    for index, part in enumerate(parts):
        source = source.parent if part == ".." else source / part
        if part == "..":
            continue
        try:
            mode = source.lstat().st_mode
        except FileNotFoundError:
            raise PlanError("declared payload is missing: " + str(source)) from None
        if stat.S_ISLNK(mode):
            raise PlanError("symlink payload is outside the ordinary-file helper scope: " + str(source))
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise PlanError("non-directory payload ancestor: " + str(source))
    source = source.resolve()
    actual = read_current(source)
    if actual is None:
        raise PlanError("declared payload is missing: " + str(source))
    # The payload supplies bytes; executable is the intended target state.
    return (actual[0], value["executable"]), source


def read_manifest(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise PlanError("manifest must be an ordinary file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PlanError("manifest is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict) or type(data.get("format_version")) is not int or data["format_version"] != 1:
        raise PlanError("expected format_version 1")
    if not isinstance(data.get("files"), list):
        raise PlanError("manifest files must be a list")
    return path, data


def validate_paths(files):
    paths = []
    for item in files:
        if not isinstance(item, dict):
            raise PlanError("file entry must be an object")
        path = relative_path(item.get("path"))
        if any(path == p or path in p.parents or p in path.parents for p in paths):
            raise PlanError("duplicate or overlapping file path: " + str(path))
        paths.append(path)
    return paths


def target_path_keys(root, relative):
    """Identify each existing prefix and any missing suffix without writing."""
    current = parent = root
    details = root.stat()
    key = ("existing", details.st_dev, details.st_ino)
    keys = []
    for part in relative.parts:
        current = current / part
        try:
            details = current.lstat()
        except FileNotFoundError:
            name = os.path.normcase(part)
            if sys.platform == "darwin":
                # Darwin's _PC_CASE_SENSITIVE is 11 (not exposed by Python's
                # pathconf_names). Query the nearest existing directory: no
                # probe writes, and case-sensitive volumes keep distinct names.
                name = unicodedata.normalize("NFD", part)
                if os.pathconf(parent, 11) == 0:
                    name = name.casefold()
            key = ("missing", key, name)
        else:
            key = ("existing", details.st_dev, details.st_ino)
            parent = current
        keys.append(key)
    return keys


def validate_target_paths(root, paths):
    """Reject target aliases, including an endpoint aliasing another ancestor."""
    checked = []
    for path in paths:
        beneath(root, str(path))
        keys = target_path_keys(root, path)
        if any(keys[-1] in earlier or earlier[-1] in keys for earlier in checked):
            raise PlanError("duplicate or overlapping target path: " + str(path))
        checked.append(keys)


def within_existing_root(root, path):
    """Compare actual ancestors; resolve() alone does not canonicalize case."""
    return any(root.samefile(parent) for parent in (path, *path.parents))


def atomic_write(path, data, executable=False, existing_mode=None):
    """One file replacement, not a multi-file transaction or durability claim."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".r3-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        # Retain unrelated permission bits when updating an ordinary file.
        mode = (existing_mode & 0o777) if existing_mode is not None else 0o644
        mode = mode | 0o111 if executable else mode & ~0o111
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
