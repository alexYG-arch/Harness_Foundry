"""Bind structured resource reports to the existing host command observation."""

import hashlib
import json
import os
from pathlib import Path
from .build_types import RequestValidationError

from .verification_resources import (collect_resource_reports, validate_structured_result, cleanup_resources,
    cleanup_error_details, validate_product_copy, _read_regular)


class CredentialObservation:
    """Archive safe reports while values are live, before a recoverable capture."""

    def __init__(self, observation, binding, redactor):
        self.observation, self.binding, self.redactor = observation, binding, redactor

    def __getattr__(self, name):
        return getattr(self.observation, name)

    def captured(self, capture):
        collected = collect_resource_reports(self.binding, self.observation.root, redactor=self.redactor)
        evaluation = validate_structured_result(collected["verdict"], self.binding, capture.get("exit_code"))
        # Repair IDs are checker-provided data, not fixed protocol tokens.
        # Never persist a secret there or route a repair using a masked ID.
        if any(self.redactor.text(item) != item for item in evaluation.get("repair_artifact_ids", [])):
            evaluation = {"status": "VALIDATION_FAILED", "automatic_retry_allowed": False,
                          "failure_domain": "VERIFIER_INFRASTRUCTURE_OR_UNCLASSIFIED",
                          "resource_result_reason": "credential report contains an unsafe repair identifier"}
        capture["credential_reports"] = {"binding": self.binding, "reports": collected["reports"],
            "report_errors": collected["report_errors"], "evaluation": evaluation}
        self.observation.captured(capture)


def _credential_reports(raw, binding, root):
    """No credential resolution or raw staging reads during recovery."""
    envelope = raw.get("credential_reports")
    if not isinstance(envelope, dict) or envelope.get("binding") != binding:
        raise ValueError("credential report completion capture is unavailable or mismatched")
    reports = envelope["reports"]
    names = [report["name"] for report in reports]
    if len(names) != len(set(names)) or set(names) - set(binding["report_files"]):
        raise ValueError("credential report archive has unexpected attachments")
    if not envelope["report_errors"] and set(names) != set(binding["report_files"]):
        raise ValueError("credential report archive is incomplete")
    for report in reports:
        data = _read_regular(root / "reports", report["name"])
        if len(data) != report["size_bytes"] or hashlib.sha256(data).hexdigest() != report["sha256"]:
            raise ValueError("credential report archive differs from its completion capture")
    return envelope


def _credential_unavailable(raw):
    return {**raw, "status": "UNKNOWN_SIDE_EFFECT", "automatic_retry_allowed": False,
            "failure_domain": "VERIFIER_INFRASTRUCTURE_OR_UNCLASSIFIED",
            "resource_result_reason": "credential report completion or archived evidence is unavailable; no replay"}


def finish_resource_observation(raw, binding, observation_root):
    root = Path(observation_root)
    root.mkdir(parents=True, exist_ok=True)
    saved = root / "resource-result.json"
    if saved.exists():
        stored = json.loads(saved.read_text())
        if stored["binding"] != binding:
            raise ValueError("resource observation belongs to another command binding")
        result = stored["result"]
        if binding["profile"].get("credentials") and result.get("workload_started") is not False:
            try:
                _credential_reports(result, binding, root)
            except (OSError, ValueError, KeyError, TypeError, RequestValidationError):
                return _credential_unavailable(result)
        result["resource_cleanup"] = _cleanup(binding, root, result.get("status") == "PASS")
        return result
    result = {**raw, "resource_binding": binding}
    # Uncertain capture or effects are never made successful by a report file.
    if raw.get("status") in {"PASS", "VALIDATION_FAILED"} and raw.get("workload_started") is not False:
        if binding["profile"].get("credentials"):
            try:
                collected = _credential_reports(raw, binding, root)
            except (OSError, ValueError, KeyError, TypeError, RequestValidationError):
                collected = None
                result = _credential_unavailable(result)
        else:
            collected = collect_resource_reports(binding, root)
        if collected is None:
            pass
        elif collected["report_errors"]:
            result.update(resource_reports=collected["reports"], report_errors=collected["report_errors"])
            result.update(status="UNKNOWN_SIDE_EFFECT" if binding["network"]["mode"] == "REMOTE_SERVICE" else "VALIDATION_FAILED", automatic_retry_allowed=False,
                          failure_domain="VERIFIER_INFRASTRUCTURE_OR_UNCLASSIFIED",
                          resource_result_reason="declared reports are missing or unreadable")
        else:
            result.update(resource_reports=collected["reports"], report_errors=collected["report_errors"])
            result.update(collected["evaluation"] if binding["profile"].get("credentials")
                          else validate_structured_result(collected["verdict"], binding, raw.get("exit_code")))
    else:
        result["automatic_retry_allowed"] = False
    if "product_copy" in binding:
        # Store this fact before successful resource cleanup. Recovery of a
        # durable result must not reread or recreate a deleted product copy.
        result["product_copy_validation"] = validate_product_copy(binding)
        if (result["product_copy_validation"]["status"] != "UNCHANGED"
                and result.get("status") in {"PASS", "VALIDATION_FAILED"}):
            result.update(status="VALIDATION_FAILED", automatic_retry_allowed=False,
                          failure_domain="VERIFIER_INFRASTRUCTURE_OR_UNCLASSIFIED",
                          resource_result_reason="bound product copy inputs changed or became unavailable")
    pending = saved.with_suffix(".pending")
    with pending.open("w", encoding="utf-8") as stream:
        json.dump({"binding": binding, "result": result}, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, saved)
    directory = os.open(root, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    result["resource_cleanup"] = _cleanup(binding, root, result.get("status") == "PASS")
    return result


def _cleanup(binding, root, success):
    path = root / "resource-cleanup.json"
    if path.exists():
        return json.loads(path.read_text())
    result = cleanup_resources(binding, success)
    # The business result is already durable; an ordinary cleanup warning must
    # remain visible without causing a product repair or replay of the command.
    try:
        pending = path.with_suffix(".pending")
        with pending.open("w", encoding="utf-8") as stream:
            json.dump(result, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    except OSError as exc:
        return {"status": "CLEANUP_WARNING", **cleanup_error_details(binding, exc), "cleanup_result": result}
    return result
