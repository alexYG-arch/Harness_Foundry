"""Derive bounded implementation plans from an unchanged approved contract.

No new grant or digest: output ownership identifies the original budget and
write scope. A started task keeps its identity; accepted tasks remain unchanged.
"""

from collections import Counter
from copy import deepcopy

from .build_types import RequestValidationError, canonical_json


def _check(condition, message):
    if not condition:
        raise RequestValidationError(message)


def _task_boundary(task):
    task = deepcopy(task)
    task.pop("goal")
    task.pop("local_argv", None)
    return task


def adapt_build_plan(original, current, scope, started_tasks=()):
    """Return derived write scopes and original task-budget owners.

    Both plans have already passed independent Plan validation. Preserve every
    declared output, its Job/executor, and every exact Case command/artifact
    binding. A merge is possible only across identical approved write scopes.
    Splits may introduce dependencies between the original task's own outputs;
    external source/artifact reads and approved ordering cannot be widened.
    """
    for key in ("schema_version", "plan_id", "requirement_revision"):
        _check(original[key] == current[key], "plan identity changed outside approval")
    old_tasks = {task["workpack_id"]: task for task in original["workpacks"]}
    new_tasks = {task["workpack_id"]: task for task in current["workpacks"]}

    def outputs(plan):
        return {item["artifact_id"]: (item, task) for task in plan["workpacks"] for item in task["artifacts"]}

    old_outputs, new_outputs = outputs(original), outputs(current)
    _check(old_outputs.keys() == new_outputs.keys(), "declared output set changed outside approval")
    for artifact_id, (item, old) in old_outputs.items():
        new_item, new = new_outputs[artifact_id]
        _check(item == new_item and old["job_id"] == new["job_id"] and old["executor"] == new["executor"],
               "artifact, Job or executor binding changed outside approval")

    def checks(plan):
        return Counter(canonical_json(check) for task in plan["workpacks"] for check in task["verification"])

    _check(checks(original) == checks(current), "acceptance command or artifact binding changed outside approval")
    owners, writes, replacements = {}, {}, {key: set() for key in old_tasks}
    for key, task in new_tasks.items():
        parents = sorted({old_outputs[item["artifact_id"]][1]["workpack_id"] for item in task["artifacts"]})
        _check(bool(parents), "replanned task must own approved outputs")
        if key in old_tasks:
            _check(key in parents, "task id cannot be reassigned to another budget")
        roots = scope["task_write_roots"][parents[0]]
        _check(all(set(scope["task_write_roots"][parent]) == set(roots) for parent in parents),
               "merge would widen an approved task write scope")
        owners[key], writes[key] = parents, list(roots)
        for parent in parents:
            replacements[parent].add(key)
        allowed_atoms = {atom for parent in parents for atom in old_tasks[parent]["atom_ids"]}
        _check(set(task["atom_ids"]) <= allowed_atoms, "task requirements changed outside approval")
        allowed_inputs = {canonical_json(item) for parent in parents for item in old_tasks[parent]["inputs"]}
        internal = {item["artifact_id"] for parent in parents for item in old_tasks[parent]["artifacts"]}
        for item in task["inputs"]:
            _check(canonical_json(item) in allowed_inputs or item["kind"] == "ARTIFACT" and item["id"] in internal,
                   "task input scope changed outside approval")

    # A plan's stated dependencies may express sequencing without artifact reads.
    # Keep those original order constraints, even after split/merge, by reachability.
    def ancestors(key):
        reached, pending = set(), list(new_tasks[key]["depends_on"])
        while pending:
            item = pending.pop()
            if item not in reached:
                reached.add(item)
                pending.extend(new_tasks[item]["depends_on"])
        return reached

    reachable = {key: ancestors(key) for key in new_tasks}
    for key, task in old_tasks.items():
        for predecessor in task["depends_on"]:
            for successor in replacements[key]:
                _check(all(prior == successor or prior in reachable[successor] for prior in replacements[predecessor]),
                       "replan removed an approved dependency")

    for task in started_tasks:
        key = task["workpack_id"]
        _check(key in new_tasks and _task_boundary(task) == _task_boundary(new_tasks[key]),
               "started task cannot be split, merged, renamed or structurally changed")
    return writes, owners
