"""Write proposed requests only; no Program, approval, target or model execution."""
from pathlib import Path
SOURCES = {"RELEASE-BUILD-DOCUMENT": "BUILD_DOCUMENT_v0.1.md", "TASK-CLI-PRD": "TASK_PRD.md",
           "CSV-PROJECT-BRIEF": "CSV_BRIEF.md", "CSV-STARTER": "csv_tool.py.txt",
           "CSV-STARTER-TESTS": "test_summary.py.txt", "CSV-USER-NOTES": "USER_NOTES.md", "RUN-METHOD": "RUN_METHOD_v0.2.md"}


def proposal(kind, *, root, bundle, inputs, program_id, runtime):
    """Stateless proposal only. All paths, model and finite bounds are caller data.

    No defaults from a historical approval and no filesystem writes. The host must
    show the result, bind reviewed documents and obtain a later runtime decision.
    """
    if kind not in {"task", "csv"}:
        raise ValueError("unknown acceptance case")
    ROOT, BUNDLE, INPUTS = (Path(path).resolve() for path in (root, bundle, inputs))
    source_id = "TASK-CLI-PRD" if kind == "task" else "CSV-PROJECT-BRIEF"
    atoms, cases, tasks = [], [], []
    for phase, executor, dependency, artifact_names, goal in [
        ("H", "CODEX", [], ["harness/AGENTS.md", "harness/BUILD.md", "harness/check.py"],
         "完整阅读当前案例 PRD/项目说明和 RUN-METHOD；仅建设该例 Coding Harness。check.py 必须支持 --help、--project、--workdir、--python；检查 JSON 状态、错误分类、工作目录及子进程传播遵循 RUN-METHOD v0.2。内部结构自由，不得实施 app。"),
        ("U", "CODEX", ["H"], ["app/tasks.py", "app/test_tasks.py", "app/README.md", "app/HARNESS_USE.md"] if kind == "task" else
         ["app/csv_tool.py", "app/test_summary.py", "app/USER_NOTES.md", "app/test_audit.py", "app/README.md", "app/HARNESS_USE.md"],
         "这是全新会话的实际使用：首先读取 harness/AGENTS.md 和 BUILD.md，依据生成的 Harness 完整开发 app 并实际执行其检查。不修改 harness 或独立 lab。CSV 保留原测试和笔记。测试接受 FOUNDRY_TEST_WORKDIR 和 BOUND_PYTHON 并传给全部子进程；U 调用时目录在 app 内，E 调用时源码只读、数据在 scenario。禁止把 U 的本机路径写死在测试中。HARNESS_USE.md 记录真实使用，不自签验收。"),
        ("E", "LOCAL", ["U"], ["scenario/report.json"], "真实本地业务观察；独立校验；Task 首次合成缺陷与原预算恢复按已展示方法执行。"),
    ] + ([("F", "LOCAL", ["E"], ["completion/result.json"], "只在真实场景已接受后形成后继记录。")] if kind == "task" else []):
        atom = "REQ-" + phase
        contract_source = "RUN-METHOD" if phase in {"H", "F"} else source_id
        count = len((INPUTS / SOURCES[contract_source]).read_text().splitlines())
        locator = f"L1-L{count}"
        atoms.append({"atom_id": atom, "source_id": contract_source, "source_locator": locator,
                      "text_or_lossless_paraphrase": goal})
        cases.append({"case_id": kind.upper() + "-" + phase, "atom_ids": [atom], "description": goal,
                      "acceptance_contract": {"source_id": contract_source, "source_locator": locator}})
        outputs = [{"artifact_id": phase + "-" + str(i), "path": name} for i, name in enumerate(artifact_names)]
        checks = {"H": "harness", "U": "source", "E": "scenario", "F": "final"}
        predecessors = [artifact["artifact_id"] for task in tasks for artifact in task["artifacts"]]
        task = {"workpack_id": phase, "job_id": kind.upper(), "executor": executor, "goal": goal,
                "depends_on": dependency, "atom_ids": [atom],
                "inputs": [{"kind": "SOURCE", "id": key} for key in SOURCES] +
                          [{"kind": "ARTIFACT", "id": key} for key in predecessors],
                "artifacts": outputs, "verification": [{"case_id": kind.upper() + "-" + phase,
                    "artifact_ids": [row["artifact_id"] for row in outputs],
                    "argv": ["python", "-B", "verifier://verify.py", kind, checks[phase],
                             "--root", ".", "--inputs", str(INPUTS), "--python", "executable://python"]}]}
        if phase == "E":
            task["local_argv"] = ["python", "-B", "verifier://exercise.py", kind, "--root", ".", "--python", "executable://python",
                                  "--test-adapter", str(BUNDLE / "src/harness_foundry_factory/test_execution.py")]
        elif phase == "F":
            task["local_argv"] = ["python", "-B", "verifier://complete.py"]
        tasks.append(task)
    request = {"requirement_ir": {"program_id": program_id, "revision": 1,
        "target": {"id": program_id, "mission": "同一发行包的完整小型案例真实建设与使用验收",
                   "scope": ["TASK_PRD.md A1–A6 全范围" if kind == "task" else "CSV_BRIEF.md B1–B5 全范围",
                             "机器前置检查与本地观察不能单独验收真实 Harness；宿主保留逐项实际证据判定"],
                   "non_goals": ["私有 PRD、旧 M1、专项视频、全平台支持、远端发布"]},
        "sources": [{"source_id": key, "path_or_uri": name, "loaded_completely": True} for key, name in SOURCES.items()],
        "atoms": atoms, "acceptance_cases": cases, "negative_cases": [], "open_questions": [], "source_conflicts": []},
        "plan": {"schema_version": "1.0", "plan_id": kind.upper(), "revision": 1,
                 "requirement_revision": 1, "workpacks": tasks}}
    scope = {"workspace_root": str(ROOT / ("task-cli" if kind == "task" else "csv-increment")),
        "task_write_roots": {"H": ["harness"], "U": ["app"], "E": ["scenario"], **({"F": ["completion"]} if kind == "task" else {})},
        "source_read_roots": [str(BUNDLE), str(ROOT / "lab"), str(INPUTS), *runtime["source_read_roots"]],
        "verification_root": str(ROOT / "lab"),
        **{key: runtime[key] for key in ("executables", "codex_executable", "model", "allow_model_service",
            "max_attempts", "max_task_attempts", "command_timeout_seconds", "expires_at")}}
    return request, scope
