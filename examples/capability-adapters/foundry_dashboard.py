#!/usr/bin/env python3
"""Host-owned Foundry observer; only explicit Program/prepared sources are read.

The selected public dashboard owns HTTP/SSE and its own lifecycle. This adapter
never grants authority, advances work, recovers reports or starts business tools.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import signal
import sys
import threading


# This is a source/release host entrypoint, not a target Harness dependency.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from harness_foundry_factory.build_observation import read_foundry_projection


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observer_from_config(config_path, **options):
    """Use the existing capability binding check before loading its entrypoint."""
    config_path = Path(config_path).absolute()
    config = json.loads(config_path.read_text(encoding="utf-8"))

    def path(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("INVALID_FOUNDRY_OBSERVER_PATH")
        result = Path(value)
        return result if result.is_absolute() else config_path.parent / result

    consume = _load(Path(__file__).with_name("consume.py"), "foundry_dashboard_consume")
    materials = json.loads(path(config["materials"]).read_text(encoding="utf-8"))
    call = consume.prepare_call(materials, "local-dashboard")
    # Loading Observer in-process must retain the selected virtual environment.
    # Resolving the executable itself would conflate separate venv symlinks.
    if consume._prepare._call_path(sys.executable) != consume._prepare._call_path(call["argv"][0]):
        raise ValueError("FOUNDRY_OBSERVER_INTERPRETER_MISMATCH")
    dashboard = _load(call["argv"][-1], "foundry_dashboard_selected_component")
    runs = config["runs"]
    if not isinstance(runs, list) or not runs:
        raise ValueError("NO_EXPLICIT_FOUNDRY_SOURCES")
    sources = {}
    for run in runs:
        local_id = run["id"]
        if not isinstance(local_id, str) or not local_id.strip() or local_id in sources:
            raise ValueError("INVALID_FOUNDRY_OBSERVER_ID")
        selection = dict(run["selection"])
        if selection.get("kind") != "foundry_build":
            raise ValueError("EXPECTED_FOUNDRY_SELECTION")
        database = path(run["control_db"])
        sources[local_id] = {
            "selection": selection,
            "reader": lambda database=database, selection=selection:
                read_foundry_projection(database, selection, **({"include_workflow": True}
                    if getattr(dashboard, "SUPPORTS_WORK_PROGRESS", False) else {})),
        }
    if "theme" in config:
        if not hasattr(dashboard, "validate_theme"):
            raise ValueError("SELECTED_DASHBOARD_THEME_UNSUPPORTED")
        options["theme"] = dashboard.validate_theme(config["theme"])
    return dashboard.Observer(sources, **options)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--idle-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    observer = None
    previous = {}
    interrupted = threading.Event()
    try:
        observer = observer_from_config(args.config, port=args.port,
            poll_seconds=args.poll_seconds, idle_seconds=args.idle_seconds)

        def stop(_signum, _frame):
            interrupted.set()

        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
        observer.start()
        launch = {"url": observer.url, "component": observer.component,
                  "session_id": observer.session_id}
        # Older selected components keep their original launch response.
        if hasattr(observer, "view_urls"):
            launch["view_urls"] = observer.view_urls
        print(json.dumps(launch), flush=True)
        while not observer.wait(0.1):
            if interrupted.is_set():
                observer.stop()
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        # Do not copy DB paths, private config or source exceptions into logs.
        print(json.dumps({"error": "FOUNDRY_OBSERVER_START_FAILED"}), flush=True)
        return 2
    finally:
        if observer is not None:
            observer.stop()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
