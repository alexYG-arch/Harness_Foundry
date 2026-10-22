"""Small adapter for the network capabilities of the native command receiver.

These are opt-in verification resources, not a new policy for legacy commands.
Unix sockets identify owned local services; the opt-in TCP selector enables
native local binding, which permits both TCP and UDP on all loopback ports.
The active Codex proxy enforces remote host allowlists, not operations.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
import re


def normalize_network(value, *, write_roots=()):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("network must be an object")
    mode = value.get("mode")
    if mode == "NONE" and set(value) == {"mode"}:
        return {"mode": mode}
    if mode == "LOCAL_SERVICE" and set(value) == {"mode", "tcp"} and value["tcp"] == "LOOPBACK":
        return {"mode": mode, "tcp": "LOOPBACK"}
    if mode == "LOCAL_SERVICE" and set(value) in ({"mode", "unix_sockets"}, {"mode", "tcp", "unix_sockets"}):
        if "tcp" in value and value["tcp"] != "LOOPBACK":
            raise ValueError("local TCP selector must be LOOPBACK")
        paths = value["unix_sockets"]
        if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
            raise ValueError("local service requires exact owned Unix socket paths")
        roots = tuple(Path(root).resolve() for root in write_roots)
        result = []
        for text in paths:
            path = Path(text)
            if (not path.is_absolute() or ".." in path.parts or "\x00" in text
                    or path.resolve() != path or not path.parent.is_dir()
                    or not any(path.is_relative_to(root) and path != root for root in roots)):
                raise ValueError("Unix socket must be inside this command's writable leaf")
            result.append(str(path))
        if len(set(result)) != len(result):
            raise ValueError("duplicate local service socket")
        return {"mode": mode, **({"tcp": "LOOPBACK"} if "tcp" in value else {}), "unix_sockets": result}
    if mode == "REMOTE_SERVICE" and set(value) == {"mode", "allowed_hosts"}:
        hosts = value["allowed_hosts"]
        if not isinstance(hosts, list) or not hosts:
            raise ValueError("remote service requires an explicit host allowlist")
        result = []
        for host in hosts:
            if not isinstance(host, str) or not host or host != host.strip():
                raise ValueError("remote host must be an exact hostname or IP literal")
            try:
                canonical = str(ipaddress.ip_address(host))
            except ValueError:
                try:
                    canonical = host.encode("idna").decode("ascii").lower()
                except UnicodeError as exc:
                    raise ValueError("invalid remote host") from exc
                labels = canonical.split(".")
                if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels):
                    raise ValueError("remote host must not contain a scheme, port, path or wildcard")
            result.append(canonical)
        if len(set(result)) != len(result):
            raise ValueError("duplicate remote host")
        return {"mode": mode, "allowed_hosts": result}
    raise ValueError("unsupported verification network fields or mode")


def native_network_profile(network):
    local_tcp = bool(network and network.get("tcp") == "LOOPBACK")
    if not network or network["mode"] != "REMOTE_SERVICE" and not local_tcp:
        return {"enabled": False}
    hosts = ["localhost", "127.0.0.1", "::1"] if local_tcp else network["allowed_hosts"]
    return {"enabled": True, "domains": {host: "allow" for host in hosts},
            # An ephemeral loopback listener avoids collisions across Cases.
            "proxy_url": "http://127.0.0.1:0", "enable_socks5": False,
            "allow_upstream_proxy": False, "allow_local_binding": local_tcp}


def effective_network_policy(network):
    if not network or network["mode"] == "NONE":
        return {"mode": "NONE", "enforcement": "CODEX_NATIVE_NETWORK_DENY"}
    if network["mode"] == "LOCAL_SERVICE":
        if network.get("tcp") == "LOOPBACK":
            # Keep the existing selector/enforcement label compatible. The
            # native local-binding grant is not limited to TCP traffic.
            return {**network, "enforcement": "CODEX_NATIVE_LOOPBACK_TCP",
                    "loopback_protocols": ["TCP", "UDP"],
                    "proxy_required": True, "external_network": "DENY_EXCEPT_NATIVE_DNS_PORT_53",
                    "guarantee": "LOOPBACK_ALL_PORTS_NOT_SERVICE_ISOLATION"}
        return {**network, "enforcement": "CODEX_NATIVE_EXACT_UNIX_SOCKET", "tcp_network": "DENY"}
    return {**network, "enforcement": "CODEX_NATIVE_PROXY_HOST_ALLOWLIST",
            "proxy_required": True, "direct_network": "DENY",
            "guarantee": "HOST_ALLOWLIST_NOT_PORT_OR_OPERATION"}
