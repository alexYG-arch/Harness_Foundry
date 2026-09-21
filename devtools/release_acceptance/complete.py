"""Cheap successor after independently accepted observations, not acceptance."""
import json
from pathlib import Path


def main():
    if not Path("scenario/report.json").is_file():
        raise SystemExit("scenario report unavailable")
    Path("completion/result.json").write_text(json.dumps({"scenario_present": True}) + "\n")


if __name__ == "__main__":
    main()
