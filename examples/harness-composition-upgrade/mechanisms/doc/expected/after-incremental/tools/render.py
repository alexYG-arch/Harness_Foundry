"""Offline synthetic document tool, component 3."""
import argparse
import json
from pathlib import Path


def render(config, notes, sources):
    known = {s["id"]: s for s in sources}
    lines = ["# " + config["title"], ""]
    for section in config["sections"]:
        lines.extend(["## " + section["title"], ""])
        for note in notes:
            if note["section"] == section["id"]:
                suffix = " (" + note["priority"] + ")" if config.get("show_priority") else ""
                lines.append("- " + note["text"] + suffix + " [" + note["source"] + "]")
        lines.append("")
    lines.extend(["## Sources", ""])
    for ident in sorted({n["source"] for n in notes}):
        source = known[ident]
        title = source["title"] + " — " if config.get("include_source_titles") else ""
        lines.append("- [" + ident + "] " + title + source["locator"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    read = lambda name: json.loads((args.root / name).read_text(encoding="utf-8"))
    result = render(read("config.json"), read("data/notes.json"), read("data/sources.json"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
