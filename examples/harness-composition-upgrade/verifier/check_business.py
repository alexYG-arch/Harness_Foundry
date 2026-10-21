"""Local checks for the R3 business examples, not a model or host-tool executor.

Automatic checks cover declared files and exact structured/numerical obligations.
Reviewed checks additionally consume independently prepared, protected host evidence.
They do not infer visual or semantic truth from a producer's self-report.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse


class BusinessFailure(ValueError):
    """A definite violation of a declared business output obligation."""


class EvidenceUnavailable(ValueError):
    """Missing or stale independent inputs are not a product assertion."""


HOST_OBLIGATIONS = {
    "prd-design": ["original-requirements", "render-mobile-desktop", "interactive-states", "customization-preserved"],
    "data-reasoning": ["computation-execution", "reasoning-boundaries", "customization-preserved"],
    "market-research": ["claim-support-and-conflicts", "reasoning-boundaries", "scope-preserved"],
    "market-live": ["search-and-original-pages", "claim-support-and-dates", "scope-preserved"],
}


def need(condition, message):
    if not condition:
        raise BusinessFailure(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def read_json(path, error=EvidenceUnavailable):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise error("cannot read JSON: " + str(path)) from exc


def number(value):
    need(not isinstance(value, bool), "boolean is not a metric value")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise BusinessFailure("invalid numerical value: " + repr(value)) from exc
    need(result.is_finite(), "metric values must be finite")
    return result


def compare_values(actual, expected, label):
    need(isinstance(actual, dict), label + " must be an object")
    for key, value in expected.items():
        need(key in actual, label + " missing " + key)
        if value is None or isinstance(value, bool):
            need(actual[key] is value, label + " changed " + key)
        elif isinstance(value, (int, Decimal)):
            need(number(actual[key]) == Decimal(value), label + " changed " + key)
        else:
            need(actual[key] == value, label + " changed " + key)


def output_names(manifest, group, version):
    if group == "market-live":
        return manifest["live_outputs"]
    return manifest["outputs"] + (manifest["v2_additional_outputs"] if version == "v2" else [])


def check_output_files(target, names):
    for name in names:
        path = target / name
        need(path.is_file(), "missing declared output: " + name)
        try:
            need(text(path.read_text(encoding="utf-8")), "empty declared output: " + name)
        except (OSError, UnicodeError) as exc:
            raise BusinessFailure("unreadable declared output: " + name) from exc


def check_prd(target, fixture, expected, version):
    trace = read_json(target / "traceability.json", BusinessFailure)
    requirements = trace["requirements"]
    ids = [row["id"] for row in requirements]
    need(len(ids) == len(set(ids)) and set(ids) == {r["id"] for r in expected["requirements"]}, "original requirement IDs missing or duplicated")
    for row in requirements:
        need(text(row["prd_section"]) and row["prototype_refs"] and all(text(x) for x in row["prototype_refs"]), "requirement needs PRD and prototype locators")
    need(set(expected["required_states"]) <= set(trace["states"]), "required state declaration missing")
    need({v["width_px"] for v in expected["required_views"]} <= set(trace["view_widths"]), "required viewport declaration missing")
    need(trace["customization"] == read_json(fixture / "inputs/user-customization.json"), "user customization changed")
    if version == "v2":
        transitions = read_json(target / "state-transitions.json", BusinessFailure)["transitions"]
        edges = set()
        preserving_edges = set()
        for row in transitions:
            need(all(text(row[key]) for key in ("from", "action", "condition", "to")), "transition needs its action and condition")
            need(type(row["preserves_contact_draft"]) is bool and type(row["reservation_created"]) is bool, "transition outcomes must be explicit booleans")
            need(not row["reservation_created"] or row["to"] == "confirmed", "a non-confirmed transition cannot create a reservation")
            edges.add((row["from"], row["to"]))
            if row["preserves_contact_draft"]:
                preserving_edges.add((row["from"], row["to"]))
        for route in expected["v2_addition"]["must_trace"]:
            states = route.split(" -> ")
            required_edges = set(zip(states, states[1:]))
            need(required_edges <= edges, "required transition route missing: " + route)
            # Other actions, such as explicit clearing, may share the same states.
            need({edge for edge in required_edges if edge[1] != "confirmed"} <= preserving_edges,
                 "required transition loses contact draft")


def reference_orders(fixture):
    definition = read_json(fixture / "inputs/metric-definition.json")
    try:
        rows = list(csv.DictReader((fixture / "inputs/orders.csv").read_text(encoding="utf-8").splitlines()))
        revisions = {}
        for row in rows:
            identity = (row["event_id"], int(row["revision"]))
            if identity in revisions and revisions[identity] != row:
                raise EvidenceUnavailable("conflicting protected source revision")
            revisions[identity] = row
        latest = {}
        for (identity, revision), row in revisions.items():
            if identity not in latest or revision > int(latest[identity]["revision"]):
                latest[identity] = row
        zone = timezone(timedelta(hours=definition["timezone_offset_hours"]))
        scoped = {}
        for identity, row in latest.items():
            local_time = datetime.fromisoformat(row["occurred_at"]).astimezone(zone)
            if local_time.date().isoformat() != definition["target_date"] or row["status"] != definition["status"]:
                continue
            amount = Decimal(row["amount"]) * Decimal(definition["units_to_yuan"][row["unit"]]) if row["amount"] else None
            scoped[identity] = {"revision": int(row["revision"]), "local_time": local_time.isoformat(), "channel": row["channel"], "amount_yuan": amount}
        return definition, scoped
    except (OSError, ValueError, KeyError, InvalidOperation) as exc:
        raise EvidenceUnavailable("invalid protected order inputs") from exc


def check_data(target, fixture, expected, version):
    definition, scoped = reference_orders(fixture)
    custom = read_json(fixture / "inputs/user-customization.json")
    detail = list(csv.DictReader(io.StringIO((target / "normalized-orders.csv").read_text(encoding="utf-8"))))
    ids = [row["event_id"] for row in detail]
    need(len(ids) == len(set(ids)) and set(ids) == set(scoped), "normalized orders have wrong identities or duplicate rows")
    for row in detail:
        truth = scoped[row["event_id"]]
        compare_values(row, {key: value for key, value in truth.items() if key not in {"amount_yuan", "local_time"}}, "normalized order " + row["event_id"])
        local_time = datetime.fromisoformat(row["local_time"])
        expected_time = datetime.fromisoformat(truth["local_time"])
        need(local_time.tzinfo is not None and local_time.utcoffset() == expected_time.utcoffset() and local_time == expected_time,
             "normalized local time differs from original source or target timezone")
        need(row["amount_yuan"] == "" if truth["amount_yuan"] is None else number(row["amount_yuan"]) == truth["amount_yuan"], "normalized amount differs from original source")
    known = [row["amount_yuan"] for row in scoped.values() if row["amount_yuan"] is not None]
    subtotal = sum(known, Decimal(0))
    mean = subtotal / len(known)
    calculated = {"eligible_paid_count": len(scoped), "known_amount_count": len(known), "unknown_amount_count": len(scoped) - len(known),
                  "known_revenue_yuan": subtotal, "amount_coverage": Decimal(len(known)) / len(scoped),
                  "known_amount_mean_exact_yuan": mean, "known_amount_mean_display_yuan": mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                  "complete_revenue_yuan": None, "complete_mean_yuan": None, "growth_rate": None}
    # The fixed hand calculation and source recomputation must agree; a changed
    # checking input is not a reason to repair the product to a new answer.
    try:
        compare_values(expected["metrics"], calculated, "protected hand calculation")
    except BusinessFailure as exc:
        raise EvidenceUnavailable(str(exc)) from exc
    metrics = read_json(target / "metrics.json", BusinessFailure)
    compare_values(metrics, calculated, "metrics")
    need(metrics["customization"] == custom, "user calculation parameters changed")
    need(metrics["definition"] == definition, "metric definition changed")
    if version == "v2":
        groups = metrics["groups"]
        need(set(groups) == {row["channel"] for row in scoped.values()}, "channel groups changed")
        for channel, group in groups.items():
            members = [row for row in scoped.values() if row["channel"] == channel]
            amounts = [row["amount_yuan"] for row in members if row["amount_yuan"] is not None]
            compare_values(group, {"eligible_paid_count": len(members), "known_amount_count": len(amounts), "known_revenue_yuan": sum(amounts, Decimal(0))}, "channel " + channel)
        cap = Decimal(custom["sensitivity_missing_amount_cap_yuan"])
        upper = subtotal + (len(scoped) - len(known)) * cap
        sensitivity = read_json(target / "sensitivity.json", BusinessFailure)
        compare_values(sensitivity, {"cap_yuan": cap, "revenue_min_yuan": subtotal, "revenue_max_yuan": upper,
                                    "all_paid_mean_min_yuan": subtotal / len(scoped), "all_paid_mean_max_yuan": upper / len(scoped),
                                    "is_actual_complete_revenue": False}, "conditional sensitivity")
        need(text(sensitivity["assumption"]), "conditional assumption must be stated")


def check_market(target, fixture, expected, version):
    source_index = read_json(fixture / "inputs/sources.json")
    register = read_json(target / "source-register.json", BusinessFailure)
    need(register["synthetic"] is True, "fixed synthetic sources represented as live")
    indexed = {row["source_id"]: row for row in source_index["sources"]}
    rows = register["sources"]
    need(len(rows) == len(indexed) and {row["source_id"] for row in rows} == set(indexed), "source register is incomplete or duplicated")
    citations = set()
    for row in rows:
        compare_values(row, indexed[row["source_id"]], "source register")
        source = (fixture / "inputs" / row["filename"]).read_text(encoding="utf-8")
        actual_paragraphs = set(re.findall(r"^## (P\d+)$", source, re.M))
        if actual_paragraphs != set(row["paragraph_ids"]):
            raise EvidenceUnavailable("protected paragraph index changed")
        citations.update(row["source_id"] + ":" + p for p in actual_paragraphs)
    claims = read_json(target / "claims.json", BusinessFailure)
    need(claims["scope"] == read_json(fixture / "inputs/research-scope.json"), "research scope or customization changed")
    observations = claims["observations"]
    need(len(observations) == 2 and {row["id"] for row in observations} == {"M01", "M02"}, "fixed observations missing or duplicated")
    for observed in observations:
        truth = next(row for row in expected["supported_observations"] if row["id"] == observed["id"])
        compare_values(observed, {"numerator": truth["numerator"], "denominator": truth["denominator"], "ratio": Decimal(truth["numerator"]) / truth["denominator"]}, "source proportion")
        need(text(observed["statement"]), "observation statement missing")
        need(set(truth["citations"]) <= set(observed["citations"]) <= citations, "observation citation mismatch")
    conflict = claims["price_conflict"]
    truth = expected["conflicts"][0]
    need(set(conflict["citations"]) == set(truth["citations"]), "price conflict must retain both sources")
    need(sorted(number(x) for x in conflict["values_yuan"]) == sorted(number(x) for x in truth["values_yuan"]), "conflicting prices changed")
    need(conflict["resolution"] == "unknown", "unresolved price conflict was silently resolved")
    need({row["id"] for row in expected["unsupported_claims"]} <= set(claims["unsupported_claims"]), "unsupported inference declarations missing")


def check_live(target):
    register = read_json(target / "live-source-register.json", BusinessFailure)
    need(text(register["as_of"]) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", register["as_of"]), "live as_of needs YYYY-MM-DD")
    datetime.fromisoformat(register["as_of"])
    sources = register["sources"]
    need(len(sources) == 2 and len({row["product"] for row in sources}) == 2, "live task needs two distinct real-product records")
    for row in sources:
        for key in ("product", "query", "url", "title", "search_tool_ref", "open_tool_ref"):
            need(text(row[key]), "live source missing " + key)
        url = urlparse(row["url"])
        need(url.scheme in {"http", "https"} and bool(url.netloc), "live source needs an opened web URL")
        retrieved = datetime.fromisoformat(row["retrieved_at"])
        need(retrieved.tzinfo is not None, "live retrieval needs an ISO timestamp with timezone")
        for key in ("published_at", "updated_at", "currency", "billing_period", "tax", "region"):
            need(row[key] is None or text(row[key]), "live context must be explicit text or unknown: " + key)
        for key in ("feature", "price", "trial"):
            claim = row["claims"][key]
            if claim["value"] is None:
                need(key != "feature" and text(claim["unknown_reason"]), "missing feature or unexplained unknown: " + key)
            else:
                need(text(claim["value"]) and text(claim["excerpt"]) and text(claim["location"]), "live claim needs original-page excerpt and location: " + key)


def automatic(group, version, target, fixture):
    target, fixture = Path(target), Path(fixture)
    manifest = read_json(fixture / "manifest.json")
    expected = read_json(fixture / "expected.json")
    if manifest["id"] != ("market_research" if group == "market-live" else group.replace("-", "_")):
        raise EvidenceUnavailable("fixture does not match selected group")
    names = output_names(manifest, group, version)
    check_output_files(target, names)
    try:
        if group == "prd-design":
            check_prd(target, fixture, expected, version)
        elif group == "data-reasoning":
            check_data(target, fixture, expected, version)
        elif group == "market-research":
            check_market(target, fixture, expected, version)
        else:
            check_live(target)
    except (KeyError, TypeError, IndexError, InvalidOperation, UnicodeError) as exc:
        raise BusinessFailure("output does not follow its declared ordinary-file contract: " + str(exc)) from exc
    except ValueError as exc:
        if isinstance(exc, (BusinessFailure, EvidenceUnavailable)):
            raise
        raise BusinessFailure("invalid structured output: " + str(exc)) from exc
    return names


def evidence_path(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise EvidenceUnavailable("evidence references must name files inside the prepared host evidence")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise EvidenceUnavailable("evidence reference leaves its prepared root")
    return path


def reviewed(group, version, target, fixture, evidence, names):
    if evidence is None:
        raise EvidenceUnavailable("independent host evidence has not been prepared")
    target, fixture, evidence = Path(target), Path(fixture), Path(evidence)
    review = read_json(evidence / "review.json")
    try:
        if review["group"] != group or review["version"] != version or not text(review["reviewer"]):
            raise EvidenceUnavailable("host review identity or selected version does not match")
        snapshot = evidence_path(evidence, review["reviewed_outputs"])
        for name in names:
            if (snapshot / name).read_bytes() != (target / name).read_bytes():
                raise EvidenceUnavailable("host review is stale for output: " + name)
        if evidence_path(evidence, review["workflow_file"]).read_bytes() != (fixture / "workflows" / (version + ".md")).read_bytes():
            raise EvidenceUnavailable("host review refers to another workflow version")
        required = ["workflow-execution", *HOST_OBLIGATIONS[group], *(["upgrade-recheck"] if version == "v2" else [])]
        rows = review["observations"]
        if len(rows) != len(required) or {row["id"] for row in rows} != set(required):
            raise EvidenceUnavailable("host observations do not cover the declared review obligations")
        failed = []
        for row in rows:
            if row["result"] not in {"PASS", "FAIL"} or not text(row["reason"]) or not row["evidence_refs"]:
                raise EvidenceUnavailable("host observation is unfinished: " + row["id"])
            for ref in row["evidence_refs"]:
                path = evidence_path(evidence, ref)
                if not path.is_file() or not path.read_bytes():
                    raise EvidenceUnavailable("host observation lacks actual evidence: " + row["id"])
            if row["result"] == "FAIL":
                failed.append(row["id"] + ": " + row["reason"])
        if failed:
            raise BusinessFailure("independent host review failed: " + "; ".join(failed))
    except (OSError, KeyError, TypeError) as exc:
        raise EvidenceUnavailable("host evidence is incomplete: " + str(exc)) from exc


def protected_path(path, protected, target):
    path = Path(path).resolve()
    if not path.is_relative_to(protected) or path.is_relative_to(target) or target.is_relative_to(path):
        raise EvidenceUnavailable("checking inputs must come from the separate protected verifier copy")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=list(HOST_OBLIGATIONS), required=True)
    parser.add_argument("--version", choices=["v1", "v2"], required=True)
    parser.add_argument("--phase", choices=["automatic", "reviewed"], required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True, help="protected group manifest.json file")
    parser.add_argument("--host-evidence", type=Path, help="protected host-evidence/review.json file")
    args = parser.parse_args(argv)
    check_id = "business-" + args.phase
    report = {"schema_version": "1.0", "case_id": os.environ.get("FOUNDRY_CASE_ID"), "command_id": os.environ.get("FOUNDRY_COMMAND_ID"),
              "status": "CHECKS_FAILED", "checks": [{"id": check_id, "status": "ERROR"}], "errors": [],
              "group": args.group, "version": args.version, "phase": args.phase, "business_acceptance": False,
              "scope": "automatic structured/numerical checks; semantic and visual judgments require independent host evidence"}
    code = 2
    try:
        if not all(os.environ.get(key) for key in ("FOUNDRY_CASE_ID", "FOUNDRY_COMMAND_ID", "FOUNDRY_REPORT_DIR", "FOUNDRY_VERIFIER_ROOT")):
            raise EvidenceUnavailable("STRUCTURED_V1 host binding is missing")
        target = args.target.resolve()
        protected = Path(os.environ["FOUNDRY_VERIFIER_ROOT"]).resolve()
        manifest = protected_path(args.fixture, protected, target)
        if manifest.name != "manifest.json" or not manifest.is_file():
            raise EvidenceUnavailable("--fixture must name the protected manifest.json file")
        fixture = manifest.parent
        evidence = None
        if args.host_evidence:
            review = protected_path(args.host_evidence, protected, target)
            if review.name != "review.json" or not review.is_file():
                raise EvidenceUnavailable("--host-evidence must name the protected review.json file")
            evidence = review.parent
        names = automatic(args.group, args.version, target, fixture)
        if args.phase == "reviewed":
            reviewed(args.group, args.version, target, fixture, evidence, names)
            report["scope"] = "automatic checks plus byte-bound independent host review; controller acceptance remains external"
        report.update(status="CHECKS_PASS", checks=[{"id": check_id, "status": "PASS"}], business_acceptance=args.phase == "reviewed")
        code = 0
    except BusinessFailure as exc:
        report.update(failure_kind="ASSERTION", checks=[{"id": check_id, "status": "FAIL", "reason": str(exc)}])
        code = 1
    except (EvidenceUnavailable, OSError, KeyError, TypeError) as exc:
        report["errors"] = [str(exc)]
    if os.environ.get("FOUNDRY_REPORT_DIR"):
        (Path(os.environ["FOUNDRY_REPORT_DIR"]) / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
