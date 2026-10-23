"""Offline RSI case intake, never an execution/acceptance or budget authority.

Only explicitly listed files are read. Reported outcomes and analyst hypotheses
remain separate; no command, linked file, database, model or repair is invoked.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .build_types import SAFE_ID_RE, canonical_json


KINDS = {"TEXT_LOG", "CODEX_JSONL", "FOUNDRY_REPORT", "MATERIAL"}
OWNERS = {"PROJECT", "HARNESS", "CAPABILITY", "FOUNDRY", "ENVIRONMENT", "ACCEPTANCE", "UNKNOWN"}
CONTEXT = ("run_id", "task_id", "platform", "environment", "implementation_version", "test_version", "phase")
STATUSES = {"PASS", "FAIL", "ERROR", "SKIP", "SKIPPED", "NOT_RUN", "UNKNOWN", "ACCEPTED",
            "REJECTED", "INVALIDATED", "BLOCKED", "IN_FLIGHT", "UNKNOWN_SIDE_EFFECT", "NOT_DISPATCHED"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("non-JSON number: " + value)
    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid)


def _identifier(value):
    require(isinstance(value, str) and SAFE_ID_RE.fullmatch(value), "invalid identifier")
    return value


def _status(value):
    return value.upper() if isinstance(value, str) and value.upper() in STATUSES else "UNKNOWN"


def _text_status(line):
    # Recognize runner syntax, not arbitrary prose containing words like PASS.
    value = line.strip()
    if value == "OK" or re.search(r"\.\.\. ok$", value):
        return "PASS"
    if re.search(r"\.\.\. (FAIL|ERROR)$", value):
        return value.rsplit(" ", 1)[-1]
    if re.match(r"FAILED(?:\s|\(|$)", value):
        return "FAIL"
    if re.search(r"\.\.\. skipped(?:\s|$)", value):
        return "SKIP"
    return _status(value)


def _record(source_id, locator, kind, status="UNKNOWN", **details):
    return {"ref": source_id + "#" + locator, "source_id": source_id, "locator": locator,
            "evidence_kind": kind, "reported_status": status,
            "independently_verified": False, **details}


def _report_records(doc, source_id, pointer=""):
    """Keep nested outcome identities separate, including historical invalidations.

    Readback may be partial. Do not reconstruct current acceptance or consumption
    from arbitrary exports; those projections belong to the existing controller.
    """
    if isinstance(doc, dict):
        fields = {key: doc[key] for key in ("status", "result", "native_execution")
                  if isinstance(doc.get(key), str)}
        invalidation = doc.get("event_type") == "BUILD_ACCEPTANCE_INVALIDATED"
        if fields or invalidation:
            statuses = {key: _status(value) for key, value in fields.items()}
            values = set(statuses.values())
            yield _record(source_id, pointer or "/", "FOUNDRY_RECORD_REPORTED",
                          "INVALIDATION_RECORDED" if invalidation else next(iter(values)) if len(values) == 1 else "UNKNOWN",
                          status_fields=fields, normalized_statuses=statuses,
                          identity={key: doc[key] for key in ("attempt_id", "workpack_id", "case_id", "event_id", "prepared_event_id") if key in doc})
        for key, value in doc.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            child = pointer + "/" + escaped
            if key == "invalidations" and isinstance(value, list) and value:
                yield _record(source_id, child, "FOUNDRY_RECORD_REPORTED", "INVALIDATION_RECORDED", data=deepcopy(value))
            yield from _report_records(value, source_id, child)
    elif isinstance(doc, list):
        for index, value in enumerate(doc):
            yield from _report_records(value, source_id, pointer + "/" + str(index))


def _parse(source, raw):
    sid, kind = source["source_id"], source["kind"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        source.update(parse_status="UNPARSED", diagnostic="not UTF-8; original bytes remain at source")
        return []
    source["parse_status"] = "COMPLETE"
    if not text.strip():
        source.update(parse_status="EMPTY", diagnostic="no observations in declared source")
        return []
    if kind == "FOUNDRY_REPORT":
        try:
            doc = read_json(text)
            require(isinstance(doc, (dict, list)), "report must be an object or list")
        except ValueError as error:
            source.update(parse_status="UNPARSED", diagnostic=str(error))
            return [_record(sid, "L1", "UNPARSED", text=text)]
        source["document"] = doc  # Preserve unknown fields and original budget values.
        records = list(_report_records(doc, sid))
        return records or [_record(sid, "/", "FOUNDRY_RECORD_REPORTED", data=doc)]
    records = []
    for index, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        locator = "L" + str(index)
        if kind != "CODEX_JSONL":
            records.append(_record(sid, locator, "TEST_LOG_REPORTED" if kind == "TEXT_LOG" else "DECLARED_MATERIAL",
                                   _text_status(line) if kind == "TEXT_LOG" else "UNKNOWN", text=line))
            continue
        try:
            event = read_json(line)
            require(isinstance(event, dict), "JSONL event must be an object")
        except ValueError as error:
            source["parse_status"] = "PARTIAL"
            records.append(_record(sid, locator, "UNPARSED", text=line, diagnostic=str(error)))
            continue
        item = event.get("item", {})
        payload = event.get("payload", {})
        item = item if isinstance(item, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        model = (item.get("type") == "agent_message" or payload.get("role") == "assistant"
                 or payload.get("type") in {"agent_message", "agent_reasoning"})
        tool = item.get("type") in {"command_execution", "mcp_tool_call"} or payload.get("type") == "function_call_output"
        records.append(_record(sid, locator, "MODEL_STATEMENT" if model else
                               "TOOL_RESULT_REPORTED" if tool else "CODEX_EVENT_REPORTED", data=event))
    return records


def import_case(manifest, source_root):
    """Read a declared local case. Supplied context/attribution is not verified.

    Relative paths resolve against source_root; no implicit linked-source reads.
    Missing/undecodable sources are explicit gaps, not reasons to discard known
    observations. Invalid bindings/manifests are errors, not silently repaired.
    """
    require(isinstance(manifest, dict), "manifest must be an object")
    case_id = _identifier(manifest.get("case_id"))
    require(isinstance(manifest.get("goal"), str) and manifest["goal"].strip(), "goal is required")
    requirements = manifest.get("requirements", [])
    require(isinstance(requirements, list) and all(isinstance(x, str) and x.strip() for x in requirements), "invalid requirements")
    entries = manifest.get("sources")
    require(isinstance(entries, list) and entries, "explicit sources required")
    root = Path(source_root).resolve(strict=True)
    require(root.is_dir(), "source root must be a directory")
    sources, observations, seen = [], [], set()
    for entry in entries:
        require(isinstance(entry, dict), "invalid source entry")
        sid = _identifier(entry.get("source_id"))
        require(sid not in seen, "duplicate source id")
        seen.add(sid)
        kind, name = entry.get("kind"), entry.get("path")
        require(isinstance(kind, str) and kind in KINDS, "unsupported source kind")
        require(isinstance(name, str) and name.strip(), "explicit source path required")
        path = Path(name)
        require(not path.is_absolute() and ".." not in path.parts and name != ".", "source path must stay within declared root")
        resolved = (root / path).resolve()
        require(resolved.is_relative_to(root), "source resolves outside declared root")
        context = entry.get("context", {})
        require(isinstance(context, dict) and all(isinstance(v, str) for v in context.values()), "context must contain text values")
        source = {"source_id": sid, "path": name, "kind": kind,
                  "context": {**{key: "UNKNOWN" for key in CONTEXT}, **context}, "context_verified": False}
        if "sha256" in entry:
            require(isinstance(entry["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), "invalid source digest")
        try:
            require(resolved.is_file(), "source is not an available regular file")
            raw = resolved.read_bytes()
        except (OSError, ValueError):
            source.update(parse_status="UNAVAILABLE", diagnostic="declared source unavailable")
            sources.append(source)
            continue
        source.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        require("sha256" not in entry or entry["sha256"] == source["sha256"], "source bytes changed: " + sid)
        observations.extend(_parse(source, raw))
        sources.append(source)
    refs = {row["ref"] for row in observations}
    unreadable = {source["source_id"] for source in sources
                  if source["parse_status"] in {"UNAVAILABLE", "UNPARSED"}}
    hypotheses, seen = [], set()
    supplied = manifest.get("hypotheses", [])
    require(isinstance(supplied, list), "hypotheses must be a list")
    for item in supplied:
        require(isinstance(item, dict), "invalid hypothesis")
        hid = _identifier(item.get("id"))
        require(hid not in seen, "duplicate hypothesis id")
        seen.add(hid)
        require(isinstance(item.get("owner"), str) and item["owner"] in OWNERS, "invalid maintenance owner")
        require(isinstance(item.get("statement"), str) and item["statement"].strip(), "hypothesis statement required")
        hypothesis = {"id": hid, "owner": item["owner"], "statement": item["statement"]}
        unverified = []
        for key in ("support_refs", "against_refs"):
            values = item.get(key, [])
            require(isinstance(values, list) and all(isinstance(ref, str) for ref in values), "unresolved evidence reference")
            hypothesis[key] = list(dict.fromkeys(values))
            for ref in hypothesis[key]:
                if ref in refs:
                    continue
                sid, separator, locator = ref.partition("#")
                require(separator and locator and sid in unreadable, "unresolved evidence reference")
                unverified.append(ref)
        if unverified:
            # Preserve the claim, not an invented observation. Missing counterevidence
            # also prevents treating the available support as sufficient.
            hypothesis["unverified_refs"] = list(dict.fromkeys(unverified))
        for key in ("proposed_change", "verification", "expected_improvement", "refutation", "decision_reason", "supersedes"):
            value = item.get(key, "UNKNOWN")
            require(isinstance(value, str), "hypothesis fields must be text")
            hypothesis[key] = value
        decision = item.get("decision", "PENDING")
        require(isinstance(decision, str) and decision in {"PENDING", "ADOPT", "REJECT"}, "invalid declared decision")
        hypothesis.update(declared_decision=decision, decision_verified=False)
        hypothesis["assessment"] = "HYPOTHESIS_NOT_CONFIRMED" if hypothesis["support_refs"] and not unverified else "INSUFFICIENT_EVIDENCE"
        hypotheses.append(hypothesis)
    return {"schema_version": "RSI_CASE_V1", "case_id": case_id, "goal": manifest["goal"],
            "requirements": deepcopy(requirements), "sources": sources, "observations": observations,
            "hypotheses": hypotheses, "import_status": "COMPLETE" if all(s["parse_status"] == "COMPLETE" for s in sources) else "PARTIAL",
            "independent_test_total": None, "tdd_assessment": "NOT_ASSESSED",
            "acceptance_verified": False, "instructions_executed": False, "automatic_repair_allowed": False,
            "control_state_modified": False,
            "limitations": ["Reported outcomes and declared context are not independently verified.",
                            "No cross-source test totals, RED/GREEN pairing or current acceptance inferred.",
                            "Missing invalidations in a partial export do not prove acceptance is still valid.",
                            "Local analysis may contain private source text; not a public knowledge package."]}


def write_case(case, output):
    """Create a new local analysis file; never overwrite sources or old evidence."""
    text = canonical_json(case)  # Validate JSON before creating a file.
    with Path(output).open("x", encoding="utf-8") as stream:
        stream.write(text + "\n")
