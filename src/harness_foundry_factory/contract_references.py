"""Resolve a contract's Candidate operands, including strict wildcard fragments."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote


def pointer_values(document: Any, pointer: str) -> list[Any]:
    """Expand collection pointers; a missing member is not an empty collection."""
    if pointer == "":
        return [document]
    if not pointer.startswith("/"):
        raise ValueError("fragment must be a JSON Pointer")
    selected = [document]
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        following = []
        for value in selected:
            if token == "*":
                if not isinstance(value, (list, dict)):
                    raise KeyError(pointer)
                following.extend(value.values() if isinstance(value, dict) else value)
            elif isinstance(value, list):
                if not token.isdigit() or int(token) >= len(value):
                    raise KeyError(pointer)
                following.append(value[int(token)])
            elif isinstance(value, dict) and token in value:
                following.append(value[token])
            else:
                raise KeyError(pointer)
        selected = following
    return selected


def resolve_candidate_operand(root: Path, reference: str) -> list[Any]:
    for prefix in ("candidate://", "harness-resource://candidate/"):
        if reference.startswith(prefix):
            relative, _, fragment = reference[len(prefix):].partition("#")
            break
    else:
        raise ValueError("not a Candidate operand")
    root = root.resolve()
    path = (root / unquote(relative)).resolve()
    if not path.is_relative_to(root):
        raise ValueError("operand escapes Candidate")
    return pointer_values(json.loads(path.read_text(encoding="utf-8")), unquote(fragment))
