"""Explicitly thaw read-only Candidate fixtures for adversarial tests only."""

from pathlib import Path


def make_path_writable(path: Path) -> None:
    if path.exists() and not path.is_symlink():
        path.chmod(path.stat().st_mode | (0o700 if path.is_dir() else 0o600))
    parent = path.parent
    if parent.exists() and not parent.is_symlink():
        parent.chmod(parent.stat().st_mode | 0o700)


def make_tree_writable(root: Path) -> None:
    if not root.exists():
        return
    for path in (root, *root.rglob("*")):
        if path.is_symlink():
            continue
        path.chmod(path.stat().st_mode | (0o700 if path.is_dir() else 0o600))
