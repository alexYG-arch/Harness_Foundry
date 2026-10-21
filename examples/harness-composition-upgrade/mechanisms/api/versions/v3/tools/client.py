"""Client uses its declared timeout and bypasses inherited proxy settings."""
import argparse
import json
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def request(base_url, path, config, opener=None):
    active = opener if opener is not None else build_opener(ProxyHandler({}))
    with active.open(base_url.rstrip("/") + path, timeout=config["timeout"]) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    print(json.dumps(request(args.base_url, "/items", config)))


if __name__ == "__main__":
    main()
