"""Synthetic localhost API component 1; no listener on import."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

VERSION = 1


def response(path, items):
    if path == "/health":
        body = {"status": "ok"}
        if VERSION >= 2:
            body["api_version"] = VERSION
        if VERSION >= 3:
            body["item_count"] = len(items)
        return 200, body
    if path == "/items":
        return 200, {"items": items}
    return 404, {"error": "not_found"}


def make_server(items):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, value = response(self.path, items)
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=Path, required=True)
    args = parser.parse_args()
    with make_server(json.loads(args.items.read_text(encoding="utf-8"))) as server:
        print(json.dumps({"host": "127.0.0.1", "port": server.server_port}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
