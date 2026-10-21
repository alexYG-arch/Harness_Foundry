"""Export project-owned structured notes to Markdown using only the standard library.

Based on the R3 DOC v3 renderer; this is not a document extraction service.
"""

import argparse
import json
from pathlib import Path


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be nonempty text")
    return value


def render(config, notes, sources):
    if not isinstance(config, dict) or not isinstance(config.get("sections"), list):
        raise ValueError("config must declare sections")
    text(config.get("title"), "title")
    for flag in ("show_priority", "include_source_titles"):
        if flag in config and not isinstance(config[flag], bool):
            raise ValueError(flag + " must be boolean")
    sections = {}
    for section in config["sections"]:
        if not isinstance(section, dict):
            raise ValueError("section must be an object")
        ident = text(section.get("id"), "section id")
        text(section.get("title"), "section title")
        if ident in sections:
            raise ValueError("duplicate section id: " + ident)
        sections[ident] = section
    if not sections or not isinstance(notes, list) or not isinstance(sources, list):
        raise ValueError("sections must be nonempty; notes and sources must be lists")
    known = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("source must be an object")
        ident = text(source.get("id"), "source id")
        text(source.get("title"), "source title")
        text(source.get("locator"), "source locator")
        if ident in known:
            raise ValueError("duplicate source id: " + ident)
        known[ident] = source
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError("note must be an object")
        section = text(note.get("section"), "note section")
        source = text(note.get("source"), "note source")
        text(note.get("text"), "note text")
        if section not in sections:
            raise ValueError("unknown note section: " + section)
        if source not in known:
            raise ValueError("unknown note source: " + source)
        if config.get("show_priority"):
            text(note.get("priority"), "note priority")
    lines = ["# " + config["title"], ""]
    for section in config["sections"]:
        lines.extend(["## " + section["title"], ""])
        for note in notes:
            if note["section"] == section["id"]:
                priority = " (" + note["priority"] + ")" if config.get("show_priority") else ""
                lines.append("- " + note["text"] + priority + " [" + note["source"] + "]")
        lines.append("")
    lines.extend(["## Sources", ""])
    for ident in sorted({note["source"] for note in notes}):
        source = known[ident]
        title = source["title"] + " — " if config.get("include_source_titles") else ""
        lines.append("- [" + ident + "] " + title + source["locator"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "notes", "sources", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = render(read_json(args.config), read_json(args.notes), read_json(args.sources))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
