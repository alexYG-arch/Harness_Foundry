"""Host-owned local observations, not acceptance; no network or model calls."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess


def observe(python, entry, arguments, cwd):
    result = subprocess.run([python, "-B", str(entry), *arguments], cwd=cwd,
                            capture_output=True, text=True, timeout=30,
                            env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1",
                                 "TMPDIR": str(cwd), "TMP": str(cwd), "TEMP": str(cwd),
                                 "FOUNDRY_TEST_WORKDIR": str(cwd), "BOUND_PYTHON": str(python)})
    return {"argv": arguments, "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def task_observations(python, app, work):
    entry = app / "tasks.py"
    store = work / "tasks.json"
    rows = {}

    def invoke(name, *args, file=store):
        before = file.read_text() if file.exists() else None
        row = observe(python, entry, ["--store", str(file), *args], work)
        row.update(before=before, after=file.read_text() if file.exists() else None)
        rows[name] = row

    for name, args in [
        ("empty", ["list"]), ("add1", ["add", "  写 报告  "]),
        ("add2", ["add", "Review"]), ("list", ["list"]),
        ("complete", ["complete", "1"]), ("idempotent", ["complete", "1"]),
        ("todo", ["list", "--status", "todo"]), ("done", ["list", "--status", "done"]),
        ("delete", ["delete", "1"]), ("add3", ["add", "第三项"]),
        ("final", ["list"]), ("blank", ["add", "  "]),
        ("bad-id", ["complete", "x"]), ("zero-id", ["delete", "0"]),
        ("bad-state", ["list", "--status", "other"]),
        ("unknown", ["complete", "999"]), ("unknown-delete", ["delete", "999"]),
        ("bad-command", ["wrong-command"]),
    ]:
        invoke(name, *args)
    valid_task = {"id": 1, "title": "保留", "status": "todo"}
    invalid = {
        "broken-json": "{broken",
        "wrong-type": {"version": 1, "next_id": "2", "tasks": [valid_task]},
        "duplicate-id": {"version": 1, "next_id": 2, "tasks": [valid_task, valid_task]},
        "bad-version": {"version": 2, "next_id": 2, "tasks": [valid_task]},
        "bad-stored-status": {"version": 1, "next_id": 2, "tasks": [dict(valid_task, status="other")]},
        "blank-stored-title": {"version": 1, "next_id": 2, "tasks": [dict(valid_task, title=" ")]},
        "bad-next-id": {"version": 1, "next_id": 1, "tasks": [valid_task]},
    }
    for name, value in invalid.items():
        file = work / (name + ".json")
        file.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        invoke(name, "add", "不得覆盖", file=file)
    return rows


def csv_observations(python, app, work):
    entry = app / "csv_tool.py"
    rows = {}
    fixtures = {
        "normal": 'id,name\n1,"甲,乙"\n2,丙\n', "empty": "id,name\n",
        "missing": 'id,name,city\n1,甲,上海\n2, ,北京\n3,乙,\n4\n',
        "duplicate": "id,id\n1,2\n", "blank-header": "id,\n1,2\n",
    }
    for name, text in fixtures.items():
        (work / (name + ".csv")).write_text(text, encoding="utf-8")
    (work / "bad-encoding.csv").write_bytes(b"id,name\n1,\xff\n")

    def invoke(name, fixture, *args, command="audit"):
        file = work / (fixture + ".csv")
        before = file.read_bytes() if file.exists() else None
        row = observe(python, entry, [command, str(file), *args], work)
        row["input_unchanged"] = (file.read_bytes() if file.exists() else None) == before
        rows[name] = row

    invoke("summary", "normal", command="summary")
    invoke("normal", "normal", "--required", "name")
    invoke("empty", "empty", "--required", "name", "--strict")
    invoke("missing", "missing", "--required", "name", "--required", "city")
    invoke("strict", "missing", "--required", "name", "--required", "city", "--strict")
    invoke("ordered", "missing", "--required", "city", "--required", "name", "--required", "city")
    invoke("unknown-column", "normal", "--required", "absent")
    invoke("no-required", "normal")
    invoke("empty-column", "normal", "--required", "")
    for name in ("duplicate", "blank-header", "bad-encoding", "no-file"):
        invoke(name, name, "--required", "id")
    return rows


def check_environment(python, harness, app, work, adapter):
    before = adapter.source_snapshot(app, work)
    harness_check = observe(python, harness / "check.py", ["--project", str(app),
        "--workdir", str(work), "--python", str(python)], work)
    tests = adapter.run_tests(app, work, python)
    return {"harness_check": harness_check, "tests": tests,
            "protected_source_unchanged": before == adapter.source_snapshot(app, work)}


def negative_copy(kind, app, destination):
    """Disclosed wrong CLI behavior; preserve imports and the actual app bytes."""
    shutil.copytree(app, destination)
    entry = destination / ("tasks.py" if kind == "task" else "csv_tool.py")
    original = entry.with_name("original_" + entry.name)
    entry.rename(original)
    command = "add" if kind == "task" else "audit"
    wrong = {"tasks": []} if kind == "task" else {"rows": 0, "invalid_rows": []}
    entry.write_text("import json, sys\nfrom pathlib import Path\n"
        + f"original = Path(__file__).with_name({original.name!r})\n"
        + f"if __name__ == '__main__' and {command!r} in sys.argv[1:]:\n"
        + f" print(json.dumps({wrong!r})); raise SystemExit(0)\n"
        + "exec(compile(original.read_bytes(), str(original), 'exec'), globals())\n")
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["task", "csv"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--test-adapter", type=Path, required=True,
                        help="Explicit read-only test_execution.py from the selected Foundry package")
    args = parser.parse_args()
    # Preserve the bound interpreter alias, including a caller's venv.
    args.python = str(Path(args.python).absolute())
    spec = importlib.util.spec_from_file_location("bound_test_adapter", args.test_adapter.resolve(strict=True))
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    root = args.root.resolve()
    scenario = root / "scenario"
    number = 1 + len(list(scenario.glob("attempt-*")))
    work = scenario / f"attempt-{number}"
    work.mkdir()
    app = root / "app"
    injected = args.kind == "task" and number == 1
    if injected:
        # Publicly planned fault: a disposable copy has a no-op add command.
        # The real accepted app is never edited. Retry restores the actual app.
        app = work / "faulty-copy"
        app.mkdir()
        (app / "tasks.py").write_text('import json\nprint(json.dumps({"tasks": []}))\n')
    rows = (task_observations if args.kind == "task" else csv_observations)(args.python, app, work)
    # The generated Harness must have a real, callable local checking interface.
    # No decision is inferred from this process by this observer.
    harness_work = work / "harness-work"
    harness_work.mkdir()
    # U-shaped check uses a disposable copy inside E's approved scratch root,
    # not write access to the accepted app. E-shaped check reads the actual app.
    copy = work / "development-copy"
    shutil.copytree(root / "app", copy)
    development_work = copy / ".foundry-test-work"
    development_work.mkdir(exist_ok=True)
    development = check_environment(args.python, root / "harness", copy, development_work, adapter)
    acceptance = check_environment(args.python, root / "harness", root / "app", harness_work, adapter)
    wrong_app = negative_copy(args.kind, root / "app", work / "negative-copy")
    wrong_work = work / "negative-work"; wrong_work.mkdir()
    negative_before = adapter.source_snapshot(wrong_app, wrong_work)
    negative_check = observe(args.python, root / "harness/check.py", ["--project", str(wrong_app),
        "--workdir", str(wrong_work), "--python", args.python], wrong_work)
    report = {"kind": args.kind, "attempt": number, "fault_injected": injected,
              "fault_recovery": "RESTORED_ACTUAL_APP" if args.kind == "task" and number > 1 else None,
              "observations": rows, **acceptance,
              "development_environment": development, "negative_harness_check": negative_check,
              "negative_source_unchanged": negative_before == adapter.source_snapshot(wrong_app, wrong_work)}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (work / "report.json").write_text(text)
    (scenario / "report.json").write_text(text)
    print(json.dumps({"status": "OBSERVED_NOT_ACCEPTED", "attempt": number, "fault_injected": injected}))


if __name__ == "__main__":
    main()
