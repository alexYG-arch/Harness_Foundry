#!/usr/bin/env python3
"""Optional read-only loopback observation service; never a business controller.

Adapters supply already sanitized display strings. This module filters the display
shape, keeps one cache per explicit run, and never invokes business commands or
opens evidence references. It does not attempt to redact arbitrary prose.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import secrets
import signal
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit


def validate_theme(value):
    if not isinstance(value, str) or value not in ("system", "light", "dark"):
        raise ValueError("INVALID_OBSERVER_THEME")
    return value


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value, *, nonempty=False):
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ValueError("INVALID_DISPLAY_TEXT")
    return value


def _number(value, *, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            or value < 0 or (positive and value == 0)):
        raise ValueError("INVALID_DISPLAY_NUMBER")
    return value


def _selection(value):
    if not isinstance(value, dict):
        raise ValueError("INVALID_SELECTION")
    names = ["kind", "project_id", "project_version", "run_id"]
    if value.get("kind") == "foundry_build":
        names += ["program_id", "prepared_event_id"]
    result = {name: _text(value.get(name), nonempty=True) for name in names}
    return result


def _strings(value):
    if not isinstance(value, list):
        raise ValueError("INVALID_DISPLAY_LIST")
    return [_text(item) for item in value]


def _revision(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return _number(value)
    if isinstance(value, dict):
        result = {key: _revision(value[key]) for key in ("stream_revision", "revision") if key in value}
        if result and all(not isinstance(item, dict) for item in result.values()):
            return result
    raise ValueError("INVALID_SOURCE_REVISION")


def normalize_projection(raw, selection):
    """Validate and copy the optional component's allowlisted display contract."""
    expected = _selection(selection)
    if not isinstance(raw, dict) or _selection(raw.get("selection")) != expected:
        raise ValueError("SOURCE_IDENTITY_MISMATCH")
    source = raw.get("business")
    if not isinstance(source, dict):
        raise ValueError("INVALID_BUSINESS_PROJECTION")
    business = {}
    for key in ("title", "current", "scope_ref", "proposal_ref"):
        if key in source:
            business[key] = _text(source[key])
    if "source_revision" in source:
        business["source_revision"] = _revision(source["source_revision"])
    items = source.get("items", [])
    if not isinstance(items, list):
        raise ValueError("INVALID_ITEMS")
    business["items"] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("INVALID_ITEM")
        identity = _text(item.get("item_id"), nonempty=True)
        if identity in seen:
            raise ValueError("DUPLICATE_ITEM_ID")
        seen.add(identity)
        row = {"item_id": identity, "state": _text(item.get("state"), nonempty=True)}
        if "label" in item:
            row["label"] = _text(item["label"])
        if "evidence_refs" in item:
            row["evidence_refs"] = _strings(item["evidence_refs"])
        business["items"].append(row)
    if "steps" in source:
        if not isinstance(source["steps"], list):
            raise ValueError("INVALID_STEPS")
        steps, step_ids = [], set()
        for step in source["steps"]:
            if not isinstance(step, dict):
                raise ValueError("INVALID_STEP")
            identity = _text(step.get("step_id"), nonempty=True)
            if identity in step_ids:
                raise ValueError("DUPLICATE_STEP_ID")
            step_ids.add(identity)
            row = {"step_id": identity, "state": _text(step.get("state"), nonempty=True)}
            for key in ("label", "detail"):
                if key in step:
                    row[key] = _text(step[key])
            if "depends_on" in step:
                row["depends_on"] = _strings(step["depends_on"])
            steps.append(row)
        for step in steps:
            dependencies = step.get("depends_on", [])
            if (len(dependencies) != len(set(dependencies)) or step["step_id"] in dependencies
                    or not set(dependencies) <= step_ids):
                raise ValueError("INVALID_STEP_DEPENDENCIES")
        business["steps"] = steps
    if "current_step_id" in source:
        current = source["current_step_id"]
        if current is not None:
            current = _text(current, nonempty=True)
            if current not in {step["step_id"] for step in business.get("steps", [])}:
                raise ValueError("INVALID_CURRENT_STEP")
        business["current_step_id"] = current
    completion = source.get("completion")
    business["completion"] = None
    if completion is not None:
        if not isinstance(completion, dict):
            raise ValueError("INVALID_COMPLETION")
        completed = _number(completion.get("completed"))
        total = _number(completion.get("total"), positive=True)
        if completed > total:
            raise ValueError("INVALID_COMPLETION")
        business["completion"] = {"completed": completed, "total": total,
                                  "label": _text(completion.get("label"), nonempty=True)}
    for key in ("pending", "recent"):
        if key in source:
            business[key] = _strings(source[key])
    if "budget" in source:
        if not isinstance(source["budget"], dict):
            raise ValueError("INVALID_BUDGET")
        business["budget"] = {key: _number(source["budget"][key])
                              for key in ("attempts_consumed", "attempts_remaining")
                              if key in source["budget"]}
    observed = raw.get("observation", {})
    if not isinstance(observed, dict):
        raise ValueError("INVALID_OBSERVATION")
    activity = observed.get("activity", {})
    if not isinstance(activity, dict):
        raise ValueError("INVALID_ACTIVITY")
    last_output = activity.get("last_output_at")
    if last_output is not None:
        last_output = _text(last_output)
    observation = {"activity": {"last_output_at": last_output},
                   "gaps": _strings(observed.get("gaps", []))}
    return {"selection": expected, "business": business, "observation": observation}


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, *args, **kwargs):
        self._owned_lock = threading.Lock()
        self._owned_connections = set()
        self._owned_handlers = set()
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        with self._owned_lock:
            self._owned_connections.add(connection)
        return connection, address

    def close_request(self, request):
        with self._owned_lock:
            self._owned_connections.discard(request)
        super().close_request(request)

    def process_request(self, request, address):
        thread = threading.Thread(target=self.process_request_thread, args=(request, address),
                                  name="observer-client", daemon=True)
        with self._owned_lock:
            self._owned_handlers.add(thread)
        try:
            thread.start()
        except RuntimeError:
            with self._owned_lock:
                self._owned_handlers.discard(thread)
            raise

    def process_request_thread(self, request, address):
        current = threading.current_thread()
        try:
            super().process_request_thread(request, address)
        finally:
            with self._owned_lock:
                self._owned_handlers.discard(current)

    def close_observers(self):
        with self._owned_lock:
            connections = list(self._owned_connections)
            handlers = list(self._owned_handlers)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        for thread in handlers:
            if thread is not threading.current_thread():
                thread.join(timeout=2.0)

    def handle_error(self, request, client_address):
        # Request/adapter contents and local paths must not enter host stderr.
        pass


class Observer:
    """Host-owned optional observer. Each reader must be a bounded read-only call.

    ``sources`` maps local selection ids to ``{selection, reader}``. A reader is
    called once at startup and thereafter only by that selection's poller. Views
    read immutable copies of its cache; attaching a view cannot rerun the reader.
    """

    def __init__(self, sources, *, port=0, poll_seconds=1.0, idle_seconds=300.0,
                 heartbeat_seconds=5.0, asset_dir=None, theme="system"):
        if not isinstance(sources, dict) or not sources:
            raise ValueError("NO_EXPLICIT_SOURCES")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("INVALID_PORT")
        self.presentation = {"theme": validate_theme(theme)}
        self.poll_seconds = _number(poll_seconds, positive=True)
        self.idle_seconds = _number(idle_seconds)
        self.heartbeat_seconds = _number(heartbeat_seconds, positive=True)
        self._sources = {}
        selections = set()
        for local_id, entry in sources.items():
            _text(local_id, nonempty=True)
            if not isinstance(entry, dict) or not callable(entry.get("reader")):
                raise ValueError("INVALID_SOURCE_READER")
            selection = _selection(entry.get("selection"))
            identity = json.dumps(selection, sort_keys=True)
            if identity in selections:
                raise ValueError("DUPLICATE_SELECTION")
            selections.add(identity)
            self._sources[local_id] = {"selection": selection, "reader": entry["reader"]}
        try:
            descriptor = json.loads(Path(__file__).with_name("capability.json").read_text(encoding="utf-8"))
            self.component = {"id": _text(descriptor["name"], nonempty=True),
                              "version": _text(descriptor["version"], nonempty=True)}
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("COMPONENT_DESCRIPTOR_UNAVAILABLE") from None
        self._port = port
        self._asset_dir = Path(asset_dir) if asset_dir is not None else Path(__file__).with_name("web")
        self._token = secrets.token_urlsafe(32)
        self.session_id = secrets.token_urlsafe(18)
        self._condition = threading.Condition(threading.RLock())
        self._stop_requested = threading.Event()
        self._stopped = threading.Event()
        self._threads = []
        self._server = None
        self._serving_thread = None
        self._started = False
        self._stopping = False
        self._cache = {}
        self._active_sse = 0
        self._last_activity = time.monotonic()
        for local_id, entry in self._sources.items():
            self._cache[local_id] = {"selection": entry["selection"], "component": self.component,
                "presentation": self.presentation,
                "business": {"items": [], "completion": None},
                "observation": {"observed_at": None, "activity": {"last_output_at": None},
                                "gaps": ["SOURCE_UNAVAILABLE"]},
                "transport": {"session_id": self.session_id, "sequence": 0}}

    @property
    def bound_port(self):
        return self._server.server_port if self._server else None

    @property
    def url(self):
        if self._server is None:
            return None
        return f"http://127.0.0.1:{self.bound_port}/{self._token}/"

    @property
    def running(self):
        return self._started and not self._stop_requested.is_set()

    def snapshot(self, run_id):
        with self._condition:
            return copy.deepcopy(self._cache[run_id])

    def _collect(self, local_id):
        entry = self._sources[local_id]
        try:
            value = normalize_projection(entry["reader"](), entry["selection"])
            value["component"] = self.component
            value["presentation"] = self.presentation
            value["observation"]["observed_at"] = _now()
        except Exception:
            # No raw adapter exception, path, environment or input reaches HTTP.
            with self._condition:
                value = copy.deepcopy(self._cache[local_id])
            if "SOURCE_UNAVAILABLE" not in value["observation"]["gaps"]:
                value["observation"]["gaps"].append("SOURCE_UNAVAILABLE")
        with self._condition:
            if self._stop_requested.is_set():
                return
            value["transport"] = {"session_id": self.session_id,
                "sequence": self._cache[local_id]["transport"]["sequence"] + 1}
            self._cache[local_id] = value
            self._condition.notify_all()

    def _poll(self, local_id):
        while not self._stop_requested.wait(self.poll_seconds):
            self._collect(local_id)

    def _idle(self):
        interval = min(0.25, max(0.01, self.idle_seconds / 4))
        while not self._stop_requested.wait(interval):
            with self._condition:
                expired = (self._active_sse == 0 and
                           time.monotonic() - self._last_activity >= self.idle_seconds)
            if expired:
                self._stop(only_if_idle=True)
                if self._stop_requested.is_set():
                    return

    def _touch(self):
        with self._condition:
            self._last_activity = time.monotonic()

    def _handler(self):
        observer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "LocalObserver"
            sys_version = ""

            def log_message(self, *_args):
                pass

            def _headers(self, code, content_type, length=None):
                self.close_connection = True
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Connection", "close")
                if length is not None:
                    self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; img-src 'self'; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
                self.end_headers()

            def _json(self, code, value):
                body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self._headers(code, "application/json; charset=utf-8", len(body))
                self.wfile.write(body)

            def _route(self):
                port = observer.bound_port
                hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
                if port == 80:
                    hosts.update({"127.0.0.1", "localhost"})
                if self.headers.get("Host") not in hosts:
                    self._json(403, {"error": "LOCAL_ORIGIN_REQUIRED"})
                    return None
                origin = self.headers.get("Origin")
                if origin is not None and origin not in {f"http://{host}" for host in hosts}:
                    self._json(403, {"error": "LOCAL_ORIGIN_REQUIRED"})
                    return None
                try:
                    parsed = urlsplit(self.path)
                except ValueError:
                    self._json(400, {"error": "INVALID_REQUEST"})
                    return None
                prefix = f"/{observer._token}/"
                if parsed.scheme or parsed.netloc or not parsed.path.startswith(prefix):
                    self._json(404, {"error": "NOT_FOUND"})
                    return None
                return parsed.path[len(prefix):], parse_qs(parsed.query, keep_blank_values=True)

            def do_GET(self):
                try:
                    route = self._route()
                    if route is None:
                        return
                    path, query = route
                    if path == "api/runs":
                        observer._touch()
                        self._json(200, {"runs": [{"id": local_id, "selection": entry["selection"]}
                            for local_id, entry in observer._sources.items()], "presentation": observer.presentation})
                        return
                    if path in ("api/snapshot", "api/events"):
                        ids = query.get("run", [])
                        if len(ids) != 1 or ids[0] not in observer._sources:
                            self._json(404, {"error": "UNKNOWN_RUN"})
                            return
                        observer._touch()
                        if path == "api/snapshot":
                            self._json(200, observer.snapshot(ids[0]))
                        else:
                            self._events(ids[0])
                        return
                    assets = {"": ("index.html", "text/html; charset=utf-8"),
                              "index.html": ("index.html", "text/html; charset=utf-8"),
                              "app.js": ("app.js", "text/javascript; charset=utf-8"),
                              "style.css": ("style.css", "text/css; charset=utf-8")}
                    if path in assets:
                        name, content_type = assets[path]
                        try:
                            body = (observer._asset_dir / name).read_bytes()
                        except OSError:
                            self._json(503, {"error": "VIEW_UNAVAILABLE"})
                            return
                        observer._touch()
                        self._headers(200, content_type, len(body))
                        self.wfile.write(body)
                        return
                    self._json(404, {"error": "NOT_FOUND"})
                except (BrokenPipeError, ConnectionError, TimeoutError):
                    self.close_connection = True

            def _events(self, local_id):
                self.connection.settimeout(max(1.0, observer.heartbeat_seconds + 1.0))
                self._headers(200, "text/event-stream; charset=utf-8")
                self.close_connection = True
                last_sequence = None
                with observer._condition:
                    observer._active_sse += 1
                try:
                    while not observer._stop_requested.is_set():
                        with observer._condition:
                            current = observer._cache[local_id]
                            if current["transport"]["sequence"] == last_sequence:
                                observer._condition.wait_for(
                                    lambda: observer._stop_requested.is_set() or
                                        observer._cache[local_id]["transport"]["sequence"] != last_sequence,
                                    timeout=observer.heartbeat_seconds)
                            if observer._stop_requested.is_set():
                                return
                            current = copy.deepcopy(observer._cache[local_id])
                        sequence = current["transport"]["sequence"]
                        if sequence != last_sequence:
                            payload = json.dumps(current, ensure_ascii=False, allow_nan=False)
                            block = f"id: {observer.session_id}:{sequence}\nevent: snapshot\ndata: {payload}\n\n"
                            last_sequence = sequence
                        else:
                            block = ": heartbeat\n\n"
                        self.wfile.write(block.encode("utf-8"))
                        self.wfile.flush()
                finally:
                    with observer._condition:
                        observer._active_sse -= 1
                        observer._last_activity = time.monotonic()

            def do_POST(self):
                self.close_connection = True
                self._json(405, {"error": "READ_ONLY"})

            do_PUT = do_POST
            do_DELETE = do_POST
            do_PATCH = do_POST

        return Handler

    def start(self):
        with self._condition:
            if self._started or self._stop_requested.is_set():
                raise RuntimeError("OBSERVER_ALREADY_STARTED_OR_STOPPED")
            self._server = _HTTPServer(("127.0.0.1", self._port), self._handler())
            self._started = True
            self._last_activity = time.monotonic()
            serving = threading.Thread(target=self._server.serve_forever,
                kwargs={"poll_interval": 0.05}, name=f"observer-http-{self.session_id}", daemon=True)
            self._serving_thread = serving
            self._threads.append(serving)
            serving.start()
        for local_id in self._sources:
            if self._stop_requested.is_set():
                return self
            self._collect(local_id)
        with self._condition:
            if not self._stop_requested.is_set():
                self._last_activity = time.monotonic()
                for local_id in self._sources:
                    thread = threading.Thread(target=self._poll, args=(local_id,),
                        name=f"observer-source-{self.session_id}-{local_id}", daemon=True)
                    self._threads.append(thread)
                    thread.start()
                if self.idle_seconds:
                    thread = threading.Thread(target=self._idle,
                        name=f"observer-idle-{self.session_id}", daemon=True)
                    self._threads.append(thread)
                    thread.start()
        return self

    def stop(self):
        self._stop()

    def _stop(self, *, only_if_idle=False):
        with self._condition:
            if self._stopping:
                return
            if only_if_idle and (self._active_sse or
                    time.monotonic() - self._last_activity < self.idle_seconds):
                return
            self._stopping = True
            self._stop_requested.set()
            self._condition.notify_all()
        if self._server is not None:
            if self._serving_thread is not None and self._serving_thread.is_alive():
                self._server.shutdown()
            self._server.close_observers()
            self._server.server_close()
        current = threading.current_thread()
        for thread in self._threads:
            if thread is not current:
                thread.join(timeout=2.0)
        self._stopped.set()

    def wait(self, timeout=None):
        return self._stopped.wait(timeout)

    def __enter__(self):
        return self.start()

    def __exit__(self, *_args):
        self.stop()


def _file_reader(path):
    def read():
        return json.loads(path.read_text(encoding="utf-8"))
    return read


def sources_from_config(config_path, *, config=None):
    """Resolve only paths explicitly named by the host, relative to its config."""
    config_path = Path(config_path).absolute()
    try:
        if config is None:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        runs = config["runs"]
        if not isinstance(runs, list) or not runs:
            raise ValueError()
        sources = {}
        for run in runs:
            local_id = _text(run["id"], nonempty=True)
            if local_id in sources:
                raise ValueError()
            path = Path(_text(run["source"], nonempty=True))
            if not path.is_absolute():
                path = config_path.parent / path
            sources[local_id] = {"selection": _selection(run["selection"]),
                                 "reader": _file_reader(path)}
        return sources
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError("INVALID_OBSERVER_CONFIG") from None


def observer_from_config(config_path, **options):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("INVALID_OBSERVER_CONFIG")
    options["theme"] = config.get("theme", "system")
    return Observer(sources_from_config(config_path, config=config), **options)


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
        print(json.dumps({"url": observer.url, "component": observer.component,
                          "session_id": observer.session_id}), flush=True)
        while not observer.wait(0.1):
            if interrupted.is_set():
                observer.stop()
        return 0
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({"error": "OBSERVER_START_FAILED"}), flush=True)
        return 2
    finally:
        if observer is not None:
            observer.stop()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
