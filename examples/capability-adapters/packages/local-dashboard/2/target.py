#!/usr/bin/env python3
"""Read explicit target-owned files; never execute tools or recover reports.

The optional display mapping belongs to the target. Checks remain owned by its
existing checker/host. A matching PASS describes only the named check results,
not acceptance of a whole Harness, model task or deployment.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import signal
import threading


def _load_dashboard():
    spec = importlib.util.spec_from_file_location("target_selected_dashboard", Path(__file__).with_name("dashboard.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_RECORD_KEY")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("INVALID_RECORD_NUMBER")))


def _path(root, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("INVALID_TARGET_RECORD_PATH")
    path = Path(value)
    return path if path.is_absolute() else root / path


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _report_bindings(report, kind):
    if kind == "doc-export":
        fields = report.get("input_bindings", {})
        if not isinstance(fields, dict):
            raise ValueError("INVALID_TARGET_REPORT_BINDING")
        result = {key: fields[key + "_sha256"] for key in ("tool", "config", "notes", "sources")
                  if key + "_sha256" in fields}
        if "expected_sha256" in report:
            result["expected"] = report["expected_sha256"]
    elif "observation_binding" not in report:
        result = {}
    else:
        binding = report["observation_binding"]
        if (not isinstance(binding, dict) or binding.get("format") != kind
                or not isinstance(binding.get("files"), dict)):
            raise ValueError("INVALID_TARGET_REPORT_BINDING")
        result = binding["files"]
    if any(value is not None and not _hash(value) for value in result.values()):
        raise ValueError("INVALID_TARGET_REPORT_BINDING")
    return result


def _host_required(configured, root, read):
    """Recover the declared dependency set, not the truth of host observations."""
    task = _json(read(_path(root, configured["task"]["path"])))
    captured = _json(read(_path(root, configured["snapshot"]["path"])))
    inputs, outputs = task["inputs"], task["outputs"]
    if (not isinstance(inputs, dict) or not isinstance(outputs, list) or not outputs
            or not isinstance(task.get("workflow"), str)
            or captured.get("task_id") != task.get("task_id")
            or captured.get("input_files") != {key: "inputs/" + str(index) for index, key in enumerate(inputs)}):
        raise ValueError("INCOMPLETE_HOST_DEPENDENCY_RECORD")
    keys = {"task", "workflow", "snapshot", "expectation", "snapshot:task/task.json", "snapshot:task/workflow"}
    keys.update("input:" + key for key in inputs)
    keys.update("snapshot:" + value for value in captured["input_files"].values())
    keys.update("output:" + name for name in outputs)
    keys.update("snapshot:outputs/" + name for name in outputs)
    for row in captured["observations"]:
        keys.update("snapshot:" + ref for ref in row["evidence_refs"])
    return keys


def _validate_item(item):
    """Mapping errors still invalidate the scope, not just a source item."""
    kind = item["format"]
    if kind not in ("data-summary", "doc-export", "host-review"):
        raise ValueError("UNSUPPORTED_TARGET_RECORD_FORMAT")
    configured = item["files"]
    check_ids = item["check_ids"]
    if (not isinstance(configured, dict) or not configured or not isinstance(check_ids, list)
            or not check_ids or any(not isinstance(key, str) or not key for key in check_ids)
            or len(check_ids) != len(set(check_ids))):
        raise ValueError("INCOMPLETE_TARGET_CHECK_MAPPING")
    _path(Path(), item["report"])
    for key, source in configured.items():
        if not isinstance(source, dict):
            raise ValueError("INVALID_TARGET_FILE_BINDING")
        if set(source) == {"sha256"} and key in ("expected", "expectation") and _hash(source["sha256"]):
            continue
        if set(source) != {"path"}:
            raise ValueError("INVALID_TARGET_FILE_BINDING")
        _path(Path(), source["path"])


def _item_state(item, root, read):
    """Keep explicit failed checks even when the checker stopped before reading all inputs."""
    kind, configured, check_ids = item["format"], item["files"], item["check_ids"]
    report = _json(read(_path(root, item["report"])))
    if not isinstance(report, dict):
        raise ValueError("INCOMPLETE_TARGET_REPORT")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks or any(not isinstance(row, dict) for row in checks):
        raise ValueError("INCOMPLETE_TARGET_CHECKS")
    ids = [row.get("id") for row in checks]
    if any(not isinstance(key, str) for key in ids) or len(ids) != len(set(ids)) or not set(check_ids) <= set(ids):
        raise ValueError("INCOMPLETE_TARGET_CHECKS")
    states = {row.get("status") for row in checks}
    negative = "FAIL" if "FAIL" in states or report.get("findings") else (
        "ERROR" if "ERROR" in states or report.get("errors") else None)
    bindings = _report_bindings(report, kind)
    required = ({"tool", "config", "notes", "sources", "expected"} if kind == "doc-export" else
                {"input", "config", "actual", "expected"} if kind == "data-summary" else
                {"task", "workflow", "snapshot", "expectation"})
    gap = set(bindings) != set(configured) or not required <= bindings.keys()
    for key, source in configured.items():
        observed = bindings.get(key)
        # null means not consumed, not evidence that the file was absent.
        if observed is None:
            gap = True
            continue
        if "sha256" in source:
            current = source["sha256"]
        else:
            try:
                current = _digest(read(_path(root, source["path"])))
            except OSError:
                gap = True
                continue
        if current != observed:
            return "INVALIDATED", "声明文件已变化；旧报告保留，当前结果需原流程核对", False
    if negative:
        detail = ("原检查记录存在已核实未通过项；按目标原流程处理" if negative == "FAIL" else
                  "原检查未完成或异常；看板不会重试业务")
        if gap:
            detail += "；部分绑定未观察或当前不可读，保留原检查状态"
        return negative, detail, gap
    if gap:
        raise ValueError("INCOMPLETE_TARGET_REPORT_BINDING")
    if (report.get("status") != "CHECKS_PASS" or states != {"PASS"}
            or report.get("errors") != [] or any(value is None for value in bindings.values())):
        raise ValueError("INCOMPLETE_TARGET_CHECK_RESULT")
    if kind == "host-review" and set(bindings) != _host_required(configured, root, read):
        raise ValueError("INCOMPLETE_HOST_DEPENDENCY_BINDING")
    if kind == "doc-export":
        execution = report.get("execution", {})
        export = report.get("actual_export")
        if (execution.get("returncode") != 0 or execution.get("invocation_attempts") != 1
                or not isinstance(export, str) or not export.strip()
                or _digest(export.encode("utf-8")) != report.get("actual_sha256")):
            raise ValueError("INCOMPLETE_DOC_EXPORT_RECORD")
    return "PASS", "当前声明文件与原检查一致；仅表示所列检查通过", False


def read_target_projection(record_path, selection, *, previous=None):
    """Read one explicit target mapping and the named native files once each."""
    record_path = Path(record_path)
    seen = {}

    def read(path):
        key = str(path.absolute())
        if key not in seen:
            try:
                seen[key] = path.read_bytes()
            except FileNotFoundError:
                seen[key] = None
        if seen[key] is None:
            raise FileNotFoundError("TARGET_FILE_ABSENT")
        return seen[key]

    record = _json(read(record_path))
    if selection.get("kind") != "harness_run" or record.get("selection") != selection:
        raise ValueError("TARGET_RUN_IDENTITY_MISMATCH")
    items, details, gaps, pending = [], {}, [], []
    rows = record.get("items", [])
    if not isinstance(rows, list):
        raise ValueError("INVALID_TARGET_ITEMS")
    previous = {} if previous is None else previous
    retained = {}
    for item in rows:
        identity = item["item_id"]
        if identity in details:
            raise ValueError("DUPLICATE_TARGET_ITEM")
        _validate_item(item)
        source_key = json.dumps([str(record_path.absolute()), selection, record.get("scope_ref"), identity,
            item["format"], item["files"], item["check_ids"]], sort_keys=True)
        prior = None
        try:
            state, detail, gap = _item_state(item, record_path.parent, read)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            prior = previous.get(source_key)
            state = prior["state"] if prior is not None else "UNKNOWN"
            detail = ("该项来源暂不可读，保留上次未通过状态" if state != "UNKNOWN" else
                      "该项来源尚不可解释；其他可用成果继续显示")
            gap = True
        details[identity] = (state, detail)
        row = {"item_id": identity, "label": item.get("label", identity), "state": state}
        refs = prior["evidence_refs"] if prior is not None else (
            [item["evidence_ref"]] if "evidence_ref" in item else [])
        if refs:
            row["evidence_refs"] = list(refs)
        if state in ("FAIL", "ERROR", "INVALIDATED"):
            retained[source_key] = {"state": state, "evidence_refs": list(refs)}
        items.append(row)
        if state != "PASS":
            pending.append(row["label"] + "：" + detail)
        if gap:
            gaps.append(row["label"] + "：" + detail)
    steps = []
    for step in record.get("steps", []):
        state, detail = details[step["item_id"]]
        if step.get("phase", "check") == "output":
            # A file alone does not prove a tool finished. A bound successful
            # check does establish the result, not its missing process history.
            state = "PASS" if state == "PASS" else "UNKNOWN"
            detail = "成果已由关联检查核对" if state == "PASS" else "成果处理过程未完整记录；查看关联检查状态"
        elif step.get("phase", "check") != "check":
            raise ValueError("INVALID_TARGET_STEP_PHASE")
        row = {key: step[key] for key in ("step_id", "label", "depends_on") if key in step}
        row.update(state=state, detail=detail)
        steps.append(row)
    current = next((step["step_id"] for step in steps
                    if step["state"] in ("FAIL", "ERROR", "INVALIDATED")), None)
    if current is None:
        current = next((step["step_id"] for step in steps if step["state"] != "PASS"), None)
    if current is None and steps:
        current = steps[-1]["step_id"]
    completion = None
    if record.get("scope_complete") is True and items:
        completion = {"completed": sum(row["state"] == "PASS" for row in items),
                      "total": len(items), "label": "本范围声明检查成果（非整个 Harness 验收）"}
    business = {"title": record.get("title", "目标 Harness 运行"),
                "scope_ref": record.get("scope_ref", selection["run_id"]),
                "current": "所列检查已通过" if items and all(row["state"] == "PASS" for row in items) else "按原记录待核对／处理",
                "source_revision": _digest(json.dumps({key: None if raw is None else _digest(raw)
                    for key, raw in sorted(seen.items())}, sort_keys=True).encode()),
                "items": items, "steps": steps, "current_step_id": current,
                "completion": completion, "pending": pending,
                "recent": ["仅观察目标明确指定的文件；连接、重启和刷新不执行检查或业务命令"]}
    if "budget" in record:
        business["budget"] = record["budget"]
    previous.clear()
    previous.update(retained)
    return {"selection": selection, "business": business,
            "observation": {"activity": {"last_output_at": None}, "gaps": gaps}}


def _verify_component(binding):
    root = Path(__file__).resolve().parent
    descriptor = _json((root / "capability.json").read_bytes())
    if (binding.get("name"), binding.get("version")) != (descriptor["name"], descriptor["version"]):
        raise ValueError("TARGET_COMPONENT_VERSION_MISMATCH")
    declared = {"capability.json", *descriptor.get("materials", []), *descriptor.get("runtime_files", []),
                *(row["path"] for row in descriptor["tools"])}
    rows = binding["files"]
    if len(rows) != len(declared) or {row["path"] for row in rows} != declared:
        raise ValueError("INCOMPLETE_TARGET_COMPONENT_BINDING")
    for row in rows:
        relative = PurePosixPath(row["path"])
        if relative.is_absolute() or ".." in relative.parts or not _hash(row["sha256"]):
            raise ValueError("INVALID_TARGET_COMPONENT_BINDING")
        if _digest((root / relative).read_bytes()) != row["sha256"]:
            raise ValueError("TARGET_COMPONENT_SOURCE_CHANGED")


def observer_from_config(config_path, **options):
    config_path = Path(config_path).absolute()
    config = _json(config_path.read_bytes())
    _verify_component(config["component"])
    runs = config["runs"]
    if not isinstance(runs, list) or not runs:
        raise ValueError("NO_EXPLICIT_TARGET_SOURCES")
    sources = {}
    dashboard = _load_dashboard()
    def reader_for(record, selection):
        previous = {}
        def reader():
            candidate = dict(previous)
            projection = read_target_projection(record, selection, previous=candidate)
            # Commit history only after the shared mapping contract accepts it.
            dashboard.normalize_projection(projection, selection)
            previous.clear()
            previous.update(candidate)
            return projection
        return reader
    for run in runs:
        identity, selection = run["id"], run["selection"]
        if not isinstance(identity, str) or not identity.strip() or identity in sources:
            raise ValueError("INVALID_TARGET_SOURCE_ID")
        if selection.get("kind") != "harness_run":
            raise ValueError("EXPECTED_TARGET_SELECTION")
        record = _path(config_path.parent, run["record"])
        sources[identity] = {"selection": selection,
            "reader": reader_for(record, selection)}
    options["theme"] = config.get("theme", "system")
    return dashboard.Observer(sources, **options)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--idle-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    observer, previous, interrupted = None, {}, threading.Event()
    try:
        observer = observer_from_config(args.config, port=args.port,
            poll_seconds=args.poll_seconds, idle_seconds=args.idle_seconds)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_: interrupted.set())
        observer.start()
        print(json.dumps({"url": observer.url, "component": observer.component,
                          "session_id": observer.session_id}), flush=True)
        while not observer.wait(0.1):
            if interrupted.is_set():
                observer.stop()
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        print(json.dumps({"error": "TARGET_OBSERVER_START_FAILED"}), flush=True)
        return 2
    finally:
        if observer is not None:
            observer.stop()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
