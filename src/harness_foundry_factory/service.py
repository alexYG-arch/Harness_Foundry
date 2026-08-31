"""Deterministic Factory authoring state machine and application service."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Iterable, Mapping
import uuid

from .constants import (
    HF28_PACKAGE_ID,
    HF28_SCHEMA_VERSION,
    PHASE_ORDER,
    RELEASE_STEP_ORDER,
    SCHEMA_VERSION,
    TARGET_CANDIDATE_STATE,
    TERMINAL_CANDIDATE_STATE,
    default_spec_root,
)
from .models import (
    CandidateValidationError,
    ChatRequest,
    ContractGateError,
    InvalidTransitionError,
    ProgramRecord,
    RequestValidationError,
    SAFE_ID_RE,
    SpecDriftError,
    SpecVerificationError,
    TransitionOutcome,
    canonical_json,
    content_sha256,
)
from .store import SQLiteEventStore
from .semantic_contracts import (
    EXPLICIT_PRODUCTION_MODE,
    explicit_production_enabled,
    validate_explicit_production_contracts,
)
from .traceability import WORKPACK_PROJECTS, normalize_ir_coverage


Clock = Callable[[], str]


def _factory_authority_provenance(
    snapshot: Mapping[str, Any],
    *,
    event_store_revision: int | None = None,
    event_store_tip_sha256: str | None = None,
) -> dict[str, Any]:
    source_registry = snapshot.get("source_registry", [])
    requirement_ir = snapshot.get("requirement_ir", {})
    return {
        "event_store_revision": (
            int(event_store_revision)
            if event_store_revision is not None
            else int(snapshot.get("revision", 0))
        ),
        "event_store_tip_sha256": (
            event_store_tip_sha256 or content_sha256(snapshot)
        ),
        "requirement_epoch": int(snapshot.get("requirement_epoch", 0)),
        "source_registry_sha256": content_sha256(source_registry),
        "requirement_ir_sha256": content_sha256(requirement_ir),
    }


def _candidate_generation_commit_binding(
    candidate_path: Path,
    *,
    program_id: str,
    requirement_epoch: int,
    requirement_ir: Mapping[str, Any],
    authority_provenance: Mapping[str, Any],
    request: ChatRequest,
    compiler_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the non-circular binding later sealed by the Factory event."""

    report_ref = "validation/START_PACKAGE_VALIDATION_REPORT.json"
    receipt_ref = "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
    report_path = candidate_path / report_ref
    receipt_path = candidate_path / receipt_ref
    package_path = candidate_path / "PACKAGE_MANIFEST.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
        receipt_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateValidationError(
            "candidate generation commit inputs are unavailable",
            details={"error": str(exc)},
        ) from exc
    candidate_hash, file_count = _tree_hash(candidate_path)
    if (
        compiler_result.get("content_sha256") != candidate_hash
        or compiler_result.get("file_count") != file_count
    ):
        raise CandidateValidationError(
            "compiler result does not match the published Candidate bytes"
        )
    binding = {
        "schema_version": "1.0",
        "binding_kind": "FACTORY_CANDIDATE_GENERATION_COMMIT",
        "program_id": program_id,
        "candidate_version": package.get("candidate_version"),
        "candidate_content_sha256": candidate_hash,
        "candidate_file_count": file_count,
        "validation_report_ref": report_ref,
        "validation_report_sha256": report_hash,
        "validation_report_receipt_ref": receipt_ref,
        "validation_report_receipt_sha256": receipt_hash,
        "requirement_epoch": requirement_epoch,
        "requirement_ir_sha256": content_sha256(requirement_ir),
        "validation_basis": dict(authority_provenance),
        "generation_request_id": request.request_id,
        "generation_idempotency_key": request.idempotency_key,
    }
    binding["binding_sha256"] = content_sha256(binding)
    return binding


class FactoryService:
    """Authoring-only Factory orchestration.

    The service may create and validate a Start Package candidate.  It has no
    transition for approving the candidate, registering a Program Driver,
    executing Workpacks, building projects, or installing a target.
    """

    FROZEN_STATES = {
        "REQUIREMENTS_FROZEN",
        "GENERATING",
        "VALIDATING",
        TERMINAL_CANDIDATE_STATE,
    }

    def __init__(
        self,
        store: SQLiteEventStore,
        *,
        spec_root: str | Path,
        runs_root: str | Path,
        clock: Clock | None = None,
        allow_unlocked_spec_for_tests: bool = False,
    ) -> None:
        self.store = store
        self.spec_root = Path(spec_root).expanduser().resolve()
        self.runs_root = Path(runs_root).expanduser().resolve()
        self.clock = clock or _utc_now
        self.allow_unlocked_spec_for_tests = allow_unlocked_spec_for_tests

    def handle_chat_turn(self, request: ChatRequest | Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, ChatRequest):
            request = ChatRequest.from_dict(request)
        now = self.clock()

        def mutate(
            current: dict[str, Any] | None,
            program_id: str,
            transition_time: str,
        ) -> TransitionOutcome:
            if request.intent == "CREATE":
                if current is not None:
                    raise InvalidTransitionError("CREATE requires no existing program")
                return self._create(program_id, request, transition_time)
            if current is None:
                raise InvalidTransitionError("existing program state is required")
            self._verify_locked_spec(current)
            handler = {
                "ADD_SOURCES": self._add_sources,
                "UPDATE_REQUIREMENTS": self._update_requirements,
                "ANSWER": self._answer,
                "PREPARE_READBACK": self._prepare_readback,
                "REQUEST_FREEZE": self._request_freeze,
                "CONFIRM_FREEZE": self._confirm_freeze,
                "PREPARE_ARCHITECTURE_READBACK": (
                    self._prepare_architecture_readback
                ),
                "REQUEST_ARCHITECTURE_LOCK": self._request_architecture_lock,
                "CONFIRM_ARCHITECTURE_LOCK": self._confirm_architecture_lock,
                "ADVANCE_AUTHORING_UNTIL_GATE": (
                    self._advance_authoring_until_gate
                ),
                "GENERATE": self._generate,
                "REOPEN": self._reopen,
            }[request.intent]
            return handler(deepcopy(current), request, transition_time)

        response = self.store.apply(request, now, mutate)
        self._export_program_views(str(response["program_id"]))
        return response

    def advance_authoring_until_gate(self, program_id: str) -> dict[str, Any]:
        """Advance internal Authoring checks in one CAS to the next real gate."""

        record = self.store.get_program(program_id)
        if record.factory_state in {
            "BLOCKED_REQUIREMENT_GAP",
            "BLOCKED_SOURCE_CONFLICT",
            "BLOCKED_AUTHORING_RISK",
            "REQUIREMENTS_READBACK_READY",
            "WAITING_REQUIREMENTS_FREEZE",
            "REQUIREMENTS_FROZEN",
            TERMINAL_CANDIDATE_STATE,
        }:
            return self._authoring_real_gate_response(record)
        request = ChatRequest.from_dict(
            {
                "request_id": f"AUTO-AUTHORING-{record.state_hash}",
                "idempotency_key": f"AUTO-AUTHORING-{record.state_hash}",
                "program_id": program_id,
                "expected_state_hash": record.state_hash,
                "actor": {
                    "type": "HUMAN_VIA_CODEX_CHAT",
                    "chat_thread_id": "FACTORY-PUBLIC-CLI",
                    "turn_id": f"AUTO-AUTHORING-{record.revision}",
                },
                "intent": "ADVANCE_AUTHORING_UNTIL_GATE",
                "payload": {},
            }
        )
        return self.handle_chat_turn(request)

    def status(self, program_id: str) -> dict[str, Any]:
        record = self.store.get_program(program_id)
        response = record.as_status()
        response.update(
            {
                "authoring_only": True,
                "next_allowed_intents": self._next_allowed_intents(
                    record.factory_state
                ),
                "candidate_status": record.snapshot.get("candidate", {}).get(
                    "status", "NOT_GENERATED"
                ),
                "freeze_status": record.snapshot.get("freeze", {}).get(
                    "status", "NOT_REQUESTED"
                ),
            }
        )
        self._export_program_views(program_id)
        return response

    def readback(self, program_id: str) -> dict[str, Any]:
        record = self.store.get_program(program_id)
        snapshot = record.snapshot
        requirement_ir = snapshot.get("requirement_ir", {})
        gaps = self._requirement_gaps(snapshot)
        response = {
            **record.as_status(),
            "response_type": "READBACK",
            "authoring_boundary": snapshot.get("authoring_boundary"),
            "spec_lock": snapshot.get("spec_lock"),
            "source_registry": snapshot.get("source_registry", []),
            "requirement_ir": requirement_ir,
            "requirement_ir_sha256": content_sha256(requirement_ir),
            "decisions": snapshot.get("decisions", []),
            "questions": gaps[:3],
            "question_count": len(gaps),
            "blockers": snapshot.get("blockers", []),
            "freeze": snapshot.get("freeze"),
            "candidate": snapshot.get("candidate"),
            "next_allowed_intents": self._next_allowed_intents(
                record.factory_state
            ),
            "capabilities_not_proven": snapshot.get(
                "capabilities_not_proven", []
            ),
        }
        self._export_program_views(program_id)
        return response

    def requirement_readback(self, program_id: str) -> dict[str, Any]:
        """Project the authoritative frozen Requirement and its human lock."""

        record = self.store.get_program(program_id)
        return self._requirement_readback_from_snapshot(
            record.snapshot,
            state_hash=record.state_hash,
            revision=record.revision,
        )

    def architecture_readback(self, program_id: str) -> dict[str, Any]:
        """Project the production architecture without changing Program state."""

        record = self.store.get_program(program_id)
        requirement = self._requirement_readback_from_snapshot(record.snapshot)
        readback = self._build_architecture_readback(record.snapshot)
        readback_hash = content_sha256(readback)
        lifecycle = record.snapshot.get("architecture_lifecycle", {})
        architecture_lock = None
        lock_status = "NOT_LOCKED"
        if isinstance(lifecycle, Mapping):
            lock_status = str(lifecycle.get("status") or "NOT_LOCKED")
            stored_readback = lifecycle.get("architecture_readback")
            if stored_readback is not None and content_sha256(stored_readback) != readback_hash:
                self._contract_gate(
                    "ARCHITECTURE_LOCK_STALE",
                    "architecture input changed after readback preparation",
                )
            if lock_status == "LOCKED":
                candidate_lock = lifecycle.get("architecture_lock")
                if not isinstance(candidate_lock, Mapping):
                    self._contract_gate(
                        "ARCHITECTURE_LOCK_MISSING",
                        "architecture lifecycle says LOCKED without a lock",
                    )
                architecture_lock = deepcopy(dict(candidate_lock))
        return {
            "schema_version": "2.9",
            "status": "PASS",
            "response_type": "ARCHITECTURE_READBACK",
            "program_id": program_id,
            "revision": record.revision,
            "state_hash": record.state_hash,
            "requirement_lock_sha256": requirement["requirement_lock"][
                "requirement_lock_sha256"
            ],
            "architecture_readback": readback,
            "architecture_readback_sha256": readback_hash,
            "lock_status": lock_status,
            "architecture_lock": architecture_lock,
            "writes_performed": False,
            "execution_started": False,
        }

    def compile_contract(self, program_id: str) -> dict[str, Any]:
        """Compile the current dual lock entirely in memory."""

        record = self.store.get_program(program_id)
        requirement = self._requirement_readback_from_snapshot(record.snapshot)
        architecture = self.architecture_readback(program_id)
        architecture_lock = architecture.get("architecture_lock")
        if not isinstance(architecture_lock, Mapping):
            self._contract_gate(
                "ARCHITECTURE_LOCK_MISSING",
                "compile requires an explicitly confirmed Architecture Lock",
            )
        try:
            from .compiler import compile_requirement_architecture_contract

            result = compile_requirement_architecture_contract(
                record.snapshot["requirement_ir"],
                requirement_lock=requirement["requirement_lock"],
                architecture_readback=architecture["architecture_readback"],
                architecture_lock=architecture_lock,
            )
        except ValueError as exc:
            gate_code = str(exc).split(":", 1)[0]
            self._contract_gate(gate_code, str(exc))
        return result

    def generation_readiness(self, program_id: str) -> dict[str, Any]:
        """Evaluate the active local-profile Candidate gate without writes."""

        record = self.store.get_program(program_id)
        return self._generation_readiness_from_snapshot(record.snapshot)

    def _generation_readiness_from_snapshot(
        self, snapshot: Mapping[str, Any]
    ) -> dict[str, Any]:
        from .compiler import compile_requirement_architecture_contract
        from .core_validation import validate_core
        from .generation_readiness import (
            GenerationReadinessError,
            evaluate_generation_readiness,
        )

        requirement = self._requirement_readback_from_snapshot(snapshot)
        architecture_readback = self._build_architecture_readback(snapshot)
        lifecycle = snapshot.get("architecture_lifecycle")
        architecture_lock = (
            lifecycle.get("architecture_lock")
            if isinstance(lifecycle, Mapping)
            else None
        )
        if not isinstance(architecture_lock, Mapping):
            self._contract_gate(
                "GENERATION_ARCHITECTURE_LOCK_MISSING",
                "Candidate generation requires the active confirmed Architecture Lock",
            )
        try:
            compiled = compile_requirement_architecture_contract(
                snapshot["requirement_ir"],
                requirement_lock=requirement["requirement_lock"],
                architecture_readback=architecture_readback,
                architecture_lock=architecture_lock,
            )
            validation = validate_core()
            if validation.get("status") != "PASS":
                self._contract_gate(
                    "GENERATION_CORE_VALIDATION_NOT_PASS",
                    "fresh official core validation did not pass",
                )
            from .core_validation import _project_validated_core_evidence

            projection = _project_validated_core_evidence(validation)
            return evaluate_generation_readiness(
                snapshot,
                requirement_lock=requirement["requirement_lock"],
                architecture_readback=architecture_readback,
                architecture_lock=architecture_lock,
                compiled_contract=compiled,
                core_validation=validation,
                core_evidence_projection=projection,
            )
        except GenerationReadinessError as exc:
            self._contract_gate(exc.code, exc.message)
        except ValueError as exc:
            self._contract_gate(
                "GENERATION_COMPILED_CONTRACT_STALE",
                str(exc),
            )
        raise AssertionError("unreachable generation readiness boundary")

    def verify_run(self, program_id: str) -> dict[str, Any]:
        report = self.store.verify_run(program_id)
        if report["status"] == "PASS":
            record = self.store.get_program(program_id)
            try:
                self._verify_locked_spec(record.snapshot)
            except SpecDriftError as exc:
                report["status"] = "FAIL"
                report["errors"].append(
                    {
                        "code": "SPEC_DRIFT",
                        **exc.details,
                    }
                )
        return report

    def verify_spec(self) -> dict[str, Any]:
        if self.spec_root == default_spec_root().resolve():
            try:
                from .spec_lock import SpecLockError, load_verified_spec_lock

                spec_lock = load_verified_spec_lock(self.spec_root)
            except (ImportError, SpecLockError) as exc:
                raise SpecVerificationError(
                    "Harness Foundry v2.8 exact spec lock failed",
                    details={"spec_root": str(self.spec_root), "error": str(exc)},
                ) from exc
            spec_lock = dict(spec_lock)
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS",
                "spec_root": str(self.spec_root),
                "package_id": spec_lock["package_id"],
                "package_version": spec_lock["package_version"],
                "content_sha256": spec_lock["content_sha256"],
                "file_count": spec_lock["file_count"],
                "spec_lock": spec_lock,
                "writes_performed": False,
                "errors": [],
            }

        if not self.allow_unlocked_spec_for_tests:
            raise SpecVerificationError(
                "spec_root must be the exact read-only sibling Harness Foundry v2.8 package",
                details={
                    "expected": str(default_spec_root().resolve()),
                    "actual": str(self.spec_root),
                },
            )

        manifest_path = self.spec_root / "PACKAGE_MANIFEST.json"
        validation_path = self.spec_root / "PACKAGE_VALIDATION_REPORT.json"
        errors: list[dict[str, Any]] = []
        if not manifest_path.is_file():
            errors.append({"code": "SPEC_MANIFEST_MISSING", "path": str(manifest_path)})
            manifest: dict[str, Any] = {}
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append({"code": "SPEC_MANIFEST_INVALID", "detail": str(exc)})
                manifest = {}

        if manifest.get("package_id") != HF28_PACKAGE_ID:
            errors.append(
                {
                    "code": "SPEC_PACKAGE_ID_MISMATCH",
                    "expected": HF28_PACKAGE_ID,
                    "actual": manifest.get("package_id"),
                }
            )
        version = str(manifest.get("version", ""))
        if not version.startswith(f"{HF28_SCHEMA_VERSION}."):
            errors.append(
                {
                    "code": "SPEC_VERSION_MISMATCH",
                    "expected": f"{HF28_SCHEMA_VERSION}.x",
                    "actual": version,
                }
            )

        if not validation_path.is_file():
            errors.append(
                {"code": "SPEC_VALIDATION_REPORT_MISSING", "path": str(validation_path)}
            )
            validation: dict[str, Any] = {}
        else:
            try:
                validation = json.loads(validation_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append({"code": "SPEC_VALIDATION_REPORT_INVALID", "detail": str(exc)})
                validation = {}
        accepted_validation_statuses = {
            "PASS",
            "CONTROLLED_PROGRESSION_AUTHORING_PACKAGE_VALIDATED_NOT_RUNTIME",
        }
        checks = validation.get("checks")
        checks_pass = isinstance(checks, list) and all(
            isinstance(item, Mapping) and item.get("status") == "PASS" for item in checks
        )
        if validation.get("status") not in accepted_validation_statuses or not checks_pass:
            errors.append(
                {
                    "code": "SPEC_VALIDATION_NOT_PASS",
                    "actual": validation.get("status"),
                }
            )

        content_hash, file_count = _tree_hash(self.spec_root)
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS" if not errors else "FAIL",
            "spec_root": str(self.spec_root),
            "package_id": manifest.get("package_id"),
            "package_version": manifest.get("version"),
            "content_sha256": content_hash,
            "file_count": file_count,
            "writes_performed": False,
            "errors": errors,
        }
        if errors:
            raise SpecVerificationError(
                "Harness Foundry v2.8 specification verification failed",
                details=report,
            )
        return report

    def validate_candidate(
        self,
        candidate_root: str | Path,
        spec_lock: Mapping[str, Any] | None = None,
        authoritative_sources: Iterable[Mapping[str, Any]] | None = None,
        authoritative_requirement_ir: Mapping[str, Any] | None = None,
        authority_provenance: Mapping[str, Any] | None = None,
        authority_events: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        root = Path(candidate_root).expanduser().resolve()
        try:
            from .validator import validate_candidate
        except ImportError as exc:  # pragma: no cover - integration guard
            raise CandidateValidationError(
                "candidate validator module is unavailable", details={"error": str(exc)}
            ) from exc
        report = validate_candidate(
            root,
            spec_lock=spec_lock,
            authoritative_sources=(
                list(authoritative_sources)
                if authoritative_sources is not None
                else None
            ),
            authoritative_requirement_ir=authoritative_requirement_ir,
            authority_provenance=authority_provenance,
            authority_events=(
                list(authority_events) if authority_events is not None else None
            ),
        )
        if not isinstance(report, Mapping):
            raise CandidateValidationError("validator returned a non-object report")
        normalized = dict(report)
        boundary_errors = self._candidate_boundary_errors(root)
        if boundary_errors:
            normalized.setdefault("errors", []).extend(boundary_errors)
            normalized["status"] = "FAIL"
        return normalized

    def validate_program_candidate(self, program_id: str) -> dict[str, Any]:
        record = self.store.get_program(program_id)
        candidate_path = record.snapshot.get("candidate", {}).get("candidate_path")
        if not candidate_path:
            raise CandidateValidationError(
                "program has no generated candidate",
                details={"program_id": program_id},
            )
        return self.validate_candidate(
            candidate_path,
            record.snapshot.get("spec_lock"),
            record.snapshot.get("source_registry", []),
            record.snapshot.get("requirement_ir"),
            _factory_authority_provenance(
                record.snapshot,
                event_store_revision=record.revision,
                event_store_tip_sha256=record.state_hash,
            ),
            self.store.list_events(program_id),
        )

    @staticmethod
    def _contract_gate(gate_code: str, message: str) -> None:
        raise ContractGateError(
            message,
            details={"gate_code": gate_code},
        )

    def _requirement_readback_from_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        state_hash: str | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        requirement_ir = snapshot.get("requirement_ir")
        freeze = snapshot.get("freeze")
        if not isinstance(requirement_ir, Mapping) or not isinstance(freeze, Mapping):
            self._contract_gate(
                "REQUIREMENT_LOCK_MISSING",
                "Requirement IR or Freeze record is missing",
            )
        requirement_ir_hash = content_sha256(requirement_ir)
        if (
            freeze.get("status") != "FROZEN"
            or freeze.get("requirement_ir_sha256") != requirement_ir_hash
        ):
            self._contract_gate(
                "REQUIREMENT_LOCK_STALE",
                "Requirement Freeze does not bind the current Requirement IR",
            )
        open_conflicts = self._source_conflicts(snapshot)
        gaps = self._requirement_gaps(snapshot)
        if open_conflicts or gaps:
            self._contract_gate(
                "REQUIREMENT_CONFLICT_OPEN",
                "Requirement Readback has unresolved conflicts or gaps",
            )

        readback_basis_hash = content_sha256(
            {
                "requirement_ir": requirement_ir,
                "source_registry": snapshot.get("source_registry", []),
                "requirement_epoch": snapshot.get("requirement_epoch"),
            }
        )
        prepared = snapshot.get("readback")
        if (
            not isinstance(prepared, Mapping)
            or prepared.get("readback_sha256") != readback_basis_hash
        ):
            self._contract_gate(
                "REQUIREMENT_LOCK_STALE",
                "approved Requirement Readback no longer matches current inputs",
            )
        target = requirement_ir.get("target")
        target = target if isinstance(target, Mapping) else {}
        source_hashes = {
            str(item.get("source_id")): str(
                item.get("sha256") or item.get("content_sha256") or ""
            )
            for item in snapshot.get("source_registry", [])
            if isinstance(item, Mapping) and item.get("source_id")
        }
        atom_ids = [
            str(item["atom_id"])
            for item in requirement_ir.get("atoms", [])
            if isinstance(item, Mapping) and item.get("atom_id")
        ]
        readback = {
            "atom_ids": atom_ids,
            "scope": deepcopy(target.get("scope", [])),
            "non_goals": deepcopy(target.get("non_goals", [])),
            "decisions": deepcopy(snapshot.get("decisions", [])),
            "open_conflicts": [],
            "source_hashes": source_hashes,
            "acceptance_case_ids_by_atom": self._case_ids_by_atom(
                requirement_ir.get("acceptance_cases", [])
            ),
            "negative_case_ids_by_atom": self._case_ids_by_atom(
                requirement_ir.get("negative_cases", [])
            ),
        }
        approval_request_id = str(
            freeze.get("decision_evidence", {}).get("request_id") or "UNKNOWN"
        )
        requirement_lock = {
            "schema_version": "2.9",
            "status": "LOCKED",
            "requirement_epoch": snapshot.get("requirement_epoch"),
            "readback_sha256": readback_basis_hash,
            "requirement_ir_sha256": requirement_ir_hash,
            "approval_receipt_ref": (
                f"factory-event://{snapshot.get('program_id')}/{approval_request_id}"
            ),
            "conflicts_closed": True,
            "locked_at": freeze.get("approved_at"),
        }
        requirement_lock["requirement_lock_sha256"] = content_sha256(
            requirement_lock
        )
        return {
            "schema_version": "2.9",
            "status": "PASS",
            "response_type": "REQUIREMENT_READBACK",
            "program_id": snapshot.get("program_id"),
            "revision": revision,
            "state_hash": state_hash,
            "requirement_epoch": snapshot.get("requirement_epoch"),
            "requirement_readback": readback,
            "readback_sha256": readback_basis_hash,
            "requirement_ir_sha256": requirement_ir_hash,
            "requirement_lock": requirement_lock,
            "writes_performed": False,
            "execution_started": False,
        }

    @staticmethod
    def _case_ids_by_atom(cases: Any) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if not isinstance(cases, list):
            return result
        for item in cases:
            if not isinstance(item, Mapping) or not item.get("case_id"):
                continue
            atom_ids = item.get("atom_ids")
            if not isinstance(atom_ids, list) and item.get("atom_id"):
                atom_ids = [item["atom_id"]]
            if not isinstance(atom_ids, list):
                continue
            for atom_id in atom_ids:
                result.setdefault(str(atom_id), []).append(str(item["case_id"]))
        return result

    def _build_architecture_readback(
        self, snapshot: Mapping[str, Any]
    ) -> dict[str, Any]:
        requirement_ir = snapshot.get("requirement_ir")
        if not isinstance(requirement_ir, Mapping):
            self._contract_gate(
                "REQUIREMENT_LOCK_MISSING", "Requirement IR is missing"
            )
        target = requirement_ir.get("target")
        if not isinstance(target, Mapping):
            self._contract_gate(
                "ARCHITECTURE_DECISION_INCOMPLETE", "target is missing"
            )
        architecture_epoch = target.get("architecture_epoch")
        control_plane_epoch = target.get("control_plane_epoch")
        epoch_contract = target.get("epoch4_architecture_control_plane_contract")
        expected_architecture = (
            epoch_contract.get("architecture_epoch")
            if isinstance(epoch_contract, Mapping)
            else architecture_epoch
        )
        expected_control = (
            epoch_contract.get("control_plane_epoch")
            if isinstance(epoch_contract, Mapping)
            else control_plane_epoch
        )
        if (
            not isinstance(architecture_epoch, int)
            or not isinstance(control_plane_epoch, int)
            or architecture_epoch != control_plane_epoch
            or architecture_epoch != expected_architecture
            or control_plane_epoch != expected_control
        ):
            self._contract_gate(
                "MIXED_EPOCH",
                "Architecture and Control Plane epochs must be one supported pair",
            )

        fields = (
            "capabilities",
            "stages",
            "subharnesses",
            "modules",
            "rules",
            "policies",
            "tools",
            "interfaces",
            "failure_returns",
            "unresolved_decisions",
        )
        explicit = target.get("architecture_input")
        if isinstance(explicit, Mapping):
            missing = [field for field in fields if field not in explicit]
            if missing:
                self._contract_gate(
                    "ARCHITECTURE_DECISION_INCOMPLETE",
                    "architecture_input is missing: " + ", ".join(missing),
                )
            readback = {field: deepcopy(explicit[field]) for field in fields}
        else:
            readback = self._derive_architecture_readback(requirement_ir, target)
        if any(not isinstance(readback.get(field), list) for field in fields):
            self._contract_gate(
                "ARCHITECTURE_DECISION_INCOMPLETE",
                "every Architecture Readback section must be an array",
            )
        required_nonempty = (
            "capabilities",
            "stages",
            "subharnesses",
            "modules",
            "rules",
            "policies",
            "interfaces",
            "failure_returns",
        )
        empty = [field for field in required_nonempty if not readback[field]]
        if empty or readback["unresolved_decisions"]:
            self._contract_gate(
                "ARCHITECTURE_DECISION_INCOMPLETE",
                "unresolved or empty Architecture sections: "
                + ", ".join(empty or ["unresolved_decisions"]),
            )
        return {
            "schema_version": "2.9",
            "program_id": snapshot.get("program_id"),
            "requirement_epoch": snapshot.get("requirement_epoch"),
            "architecture_epoch": architecture_epoch,
            "control_plane_epoch": control_plane_epoch,
            **readback,
        }

    def _derive_architecture_readback(
        self,
        requirement_ir: Mapping[str, Any],
        target: Mapping[str, Any],
    ) -> dict[str, Any]:
        epoch38 = target.get("v2_9_charter_architecture_correction_epoch38")
        topology = (
            epoch38.get("planned_owned_core_topology")
            if isinstance(epoch38, Mapping)
            else {}
        )
        topology = topology if isinstance(topology, Mapping) else {}
        atoms = [
            item
            for item in requirement_ir.get("atoms", [])
            if isinstance(item, Mapping) and item.get("atom_id")
        ]
        edges = [
            item
            for item in requirement_ir.get("coverage_edges", [])
            if isinstance(item, Mapping)
        ]
        rules: list[Any] = []
        policies: list[Any] = []
        failure_returns: list[Any] = []
        for atom in atoms:
            rules.extend(deepcopy(atom.get("order_constraints", [])))
            policies.extend(deepcopy(atom.get("compatibility_constraints", [])))
            policies.extend(deepcopy(atom.get("defaults", [])))
            failure_returns.extend(deepcopy(atom.get("error_semantics", [])))
            contract = atom.get("production_contract")
            if not isinstance(contract, Mapping):
                continue
            policies.extend(deepcopy(contract.get("forbidden_inferences", [])))
            for obligation in contract.get("workpack_obligations", []):
                if not isinstance(obligation, Mapping):
                    continue
                rules.extend(deepcopy(obligation.get("deterministic_steps", [])))
                policies.extend(deepcopy(obligation.get("forbidden_inferences", [])))
                for artifact in obligation.get("artifact_obligations", []):
                    if isinstance(artifact, Mapping) and artifact.get("failure_return"):
                        failure_returns.append(deepcopy(artifact["failure_return"]))
        unresolved = deepcopy(requirement_ir.get("open_questions", []))
        unresolved.extend(deepcopy(requirement_ir.get("source_conflicts", [])))
        return {
            "capabilities": [
                {
                    "atom_id": str(atom["atom_id"]),
                    "statement": atom.get("text_or_lossless_paraphrase"),
                    "owner": atom.get("owner"),
                    "delivery_tier": atom.get("delivery_tier"),
                }
                for atom in atoms
            ],
            "stages": self._unique_values(
                value for edge in edges for value in edge.get("stage_ids", [])
            ),
            "subharnesses": self._unique_values(
                value for edge in edges for value in edge.get("workpack_ids", [])
            ),
            "modules": deepcopy(topology.get("source_modules", [])),
            "rules": self._unique_values(rules),
            "policies": self._unique_values(policies),
            "tools": deepcopy(target.get("required_tools", [])),
            "interfaces": deepcopy(
                topology.get("required_public_capabilities", [])
            ),
            "failure_returns": self._unique_values(failure_returns),
            "unresolved_decisions": unresolved,
        }

    @staticmethod
    def _unique_values(values: Iterable[Any]) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()
        for value in values:
            key = content_sha256(value)
            if key not in seen:
                seen.add(key)
                result.append(deepcopy(value))
        return result

    def _create(
        self,
        program_id: str,
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        spec_report = self.verify_spec()
        requirement_ir = self._normalize_requirement_patch(request.payload)
        requirement_ir = self._canonicalize_ir(requirement_ir, program_id)
        snapshot = {
            "program_id": program_id,
            "factory_state": "INTAKE_OPEN",
            "authoring_boundary": {
                "execution_mode": "AUTHORING_ONLY",
                "execution_started": False,
                "install_started": False,
                "certification_started": False,
                "auto_start_generated_workpacks": False,
                "terminal_state": TERMINAL_CANDIDATE_STATE,
                "target_terminal_state": TARGET_CANDIDATE_STATE,
            },
            "spec_lock": {
                **spec_report.get(
                    "spec_lock",
                    {
                        "package_id": spec_report["package_id"],
                        "package_version": spec_report["package_version"],
                        "content_sha256": spec_report["content_sha256"],
                        "file_count": spec_report["file_count"],
                    },
                ),
                "locked_at": now,
            },
            "requirement_epoch": 0,
            "source_registry": [],
            "requirement_ir": requirement_ir,
            "decisions": deepcopy(requirement_ir.get("decisions", [])),
            "blockers": [],
            "freeze": {"status": "NOT_REQUESTED"},
            "candidate": {"status": "NOT_GENERATED"},
            "capabilities_not_proven": [
                "START_PACKAGE_HUMAN_APPROVED",
                "PROGRAM_DRIVER_REGISTERED_OR_STARTED",
                "WORKPACK_EXECUTED",
                "THREE_ENGINEERING_PROJECTS_BUILT",
                "HARNESS_IMPLEMENTED_OR_INSTALLED",
                "CONFORMANCE_CERTIFIED",
                "REAL_TARGET_INSTALLED",
            ],
        }
        declared_sources = requirement_ir.get("sources", [])
        sources = request.payload.get("sources") or request.payload.get("source_paths")
        snapshot_root = self.runs_root / program_id / "sources" / "snapshots"
        records = (
            self._source_records(declared_sources, now, snapshot_root=snapshot_root)
            if declared_sources
            else []
        )
        if sources:
            records.extend(
                self._source_records(sources, now, snapshot_root=snapshot_root)
            )
        records.append(self._chat_source_record(request, now))
        snapshot["source_registry"] = self._merge_source_records([], records)
        snapshot["factory_state"] = "CLARIFYING"
        self._sync_ir_metadata(snapshot)
        gaps = self._requirement_gaps(snapshot)
        self._sync_ir_metadata(snapshot, open_questions=gaps)
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="PROGRAM_CREATED",
            response={
                "status": "WAITING_USER" if gaps else "OK",
                "response_type": "QUESTIONS" if gaps else "STATUS",
                "questions": gaps[:3],
                "question_count": len(gaps),
                "next_allowed_intents": self._next_allowed_intents(
                    snapshot["factory_state"]
                ),
                "human_summary": "Factory Program created in AUTHORING_ONLY mode.",
            },
        )

    def _add_sources(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        self._require_mutable_requirements(snapshot)
        sources = request.payload.get("sources") or request.payload.get("source_paths")
        if not sources:
            raise RequestValidationError("ADD_SOURCES requires payload.sources")
        records = self._source_records(
            sources,
            now,
            snapshot_root=self.runs_root
            / snapshot["program_id"]
            / "sources"
            / "snapshots",
        )
        snapshot["source_registry"] = self._merge_source_records(
            snapshot["source_registry"], records
        )
        snapshot["factory_state"] = "CLARIFYING"
        self._sync_ir_metadata(snapshot)
        gaps = self._requirement_gaps(snapshot)
        self._sync_ir_metadata(snapshot, open_questions=gaps)
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="SOURCES_REGISTERED",
            response={
                "status": "WAITING_USER" if gaps else "OK",
                "response_type": "QUESTIONS",
                "registered_sources": records,
                "questions": gaps[:3],
                "question_count": len(gaps),
                "next_allowed_intents": self._next_allowed_intents("CLARIFYING"),
            },
        )

    def _update_requirements(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        self._require_mutable_requirements(snapshot)
        supported_fields = {
            "requirement_ir",
            "requirements",
            "target",
            "atoms",
            "acceptance_cases",
            "acceptance_criteria",
            "negative_cases",
            "negative_tests",
            "assumptions",
            "open_questions",
            "decisions",
            "user_adjustments",
            "automation",
            "source_conflicts",
            "target_id",
            "target_name",
            "target_type",
            "selected_profile",
            "profile",
            "target_root",
            "output_root",
            "mission",
            "scope",
            "non_goals",
            "primary_runtime",
            "description",
        }
        unknown_fields = sorted(set(request.payload) - supported_fields)
        if unknown_fields:
            raise RequestValidationError(
                "UPDATE_REQUIREMENTS unknown payload fields: "
                + ", ".join(unknown_fields)
            )
        patch = self._normalize_requirement_patch(request.payload)
        material_patch = {
            key: value for key, value in patch.items() if key != "schema_version"
        }
        if not _has_material_requirement_patch(material_patch):
            raise RequestValidationError(
                "UPDATE_REQUIREMENTS requires a non-empty requirement patch"
            )
        snapshot["requirement_ir"] = _deep_merge(snapshot["requirement_ir"], patch)
        if isinstance(patch.get("decisions"), list):
            snapshot["decisions"] = _merge_json_records(
                snapshot["decisions"], patch["decisions"]
            )
        snapshot["source_registry"] = self._merge_source_records(
            snapshot["source_registry"], [self._chat_source_record(request, now)]
        )
        snapshot["factory_state"] = "CLARIFYING"
        snapshot["decisions"].append(
            {
                "decision_id": f"DEC-{uuid.uuid4().hex.upper()}",
                "kind": "REQUIREMENT_UPDATE",
                "actor": request.actor.as_dict(),
                "recorded_at": now,
                "patch_sha256": content_sha256(patch),
            }
        )
        snapshot["requirement_ir"] = self._canonicalize_ir(
            snapshot["requirement_ir"], snapshot["program_id"]
        )
        self._sync_ir_metadata(snapshot)
        gaps = self._requirement_gaps(snapshot)
        self._sync_ir_metadata(snapshot, open_questions=gaps)
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="REQUIREMENTS_UPDATED",
            response={
                "status": "WAITING_USER" if gaps else "OK",
                "response_type": "QUESTIONS" if gaps else "READBACK_READY",
                "questions": gaps[:3],
                "question_count": len(gaps),
                "requirement_ir_sha256": content_sha256(snapshot["requirement_ir"]),
                "next_allowed_intents": self._next_allowed_intents("CLARIFYING"),
            },
        )

    def _answer(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        self._require_mutable_requirements(snapshot)
        answers = request.payload.get("answers")
        if answers is None and "question_id" in request.payload:
            answers = [
                {
                    "question_id": request.payload.get("question_id"),
                    "answer": request.payload.get("answer"),
                }
            ]
        if isinstance(answers, Mapping):
            answers = [
                {"question_id": question_id, "answer": answer}
                for question_id, answer in answers.items()
            ]
        if not isinstance(answers, list) or not answers:
            raise RequestValidationError(
                "ANSWER requires payload.answers or question_id/answer"
            )
        normalized_answers: list[dict[str, Any]] = []
        for answer in answers:
            if not isinstance(answer, Mapping) or not answer.get("question_id"):
                raise RequestValidationError("each answer requires question_id")
            normalized_answers.append(
                {
                    "question_id": str(answer["question_id"]),
                    "answer": answer.get("answer"),
                    "actor": request.actor.as_dict(),
                    "recorded_at": now,
                }
            )
        snapshot["decisions"].extend(normalized_answers)
        snapshot["source_registry"] = self._merge_source_records(
            snapshot["source_registry"], [self._chat_source_record(request, now)]
        )
        patch_payload = request.payload.get("requirements_patch")
        if patch_payload is not None:
            if not isinstance(patch_payload, Mapping):
                raise RequestValidationError("requirements_patch must be an object")
            patch = self._normalize_requirement_patch(dict(patch_payload))
            snapshot["requirement_ir"] = _deep_merge(snapshot["requirement_ir"], patch)
        snapshot["factory_state"] = "CLARIFYING"
        snapshot["requirement_ir"] = self._canonicalize_ir(
            snapshot["requirement_ir"], snapshot["program_id"]
        )
        self._sync_ir_metadata(snapshot)
        gaps = self._requirement_gaps(snapshot)
        self._sync_ir_metadata(snapshot, open_questions=gaps)
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="CLARIFICATION_ANSWERS_RECORDED",
            response={
                "status": "WAITING_USER" if gaps else "OK",
                "response_type": "QUESTIONS" if gaps else "READBACK_READY",
                "questions": gaps[:3],
                "question_count": len(gaps),
                "next_allowed_intents": self._next_allowed_intents("CLARIFYING"),
            },
        )

    def _advance_authoring_until_gate(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        if snapshot.get("factory_state") not in {
            "INTAKE_OPEN",
            "CLARIFYING",
            "BLOCKED_REQUIREMENT_GAP",
        }:
            raise InvalidTransitionError(
                "ADVANCE_AUTHORING_UNTIL_GATE is not allowed from current state",
                details={"factory_state": snapshot.get("factory_state")},
            )
        self._validate_authoring_epoch_pair(snapshot)
        source_conflicts = self._source_conflicts(snapshot)
        if source_conflicts:
            blocker = self._typed_authoring_blocker(
                blocker_type="WAITING_EXTERNAL_STATE",
                owner="SOURCE_OWNER",
                finding="A registered local source changed or became unavailable.",
                evidence=source_conflicts,
                intents=["REOPEN"],
            )
            snapshot["factory_state"] = "BLOCKED_SOURCE_CONFLICT"
            snapshot["blockers"] = [blocker]
            return TransitionOutcome(
                snapshot=snapshot,
                event_type="AUTHORING_AUTO_ADVANCE_STOPPED",
                response={
                    "status": "STOPPED_AT_REAL_GATE",
                    "response_type": "AUTHORING_GATE",
                    "engine_id": "GenericTransitionEngine",
                    "stop_reason": "WAITING_EXTERNAL_STATE",
                    "trace": [],
                    "blockers": [blocker],
                    "next_allowed_intents": ["REOPEN"],
                },
            )

        target = snapshot.get("requirement_ir", {}).get("target", {})
        if isinstance(target, Mapping):
            self._validate_authoring_policy(target)
            declared_gate = self._declared_authoring_risk_gate(target)
            if declared_gate is not None:
                snapshot["factory_state"] = "BLOCKED_AUTHORING_RISK"
                snapshot["blockers"] = [declared_gate]
                return TransitionOutcome(
                    snapshot=snapshot,
                    event_type="AUTHORING_AUTO_ADVANCE_STOPPED",
                    response={
                        "status": "STOPPED_AT_REAL_GATE",
                        "response_type": "AUTHORING_GATE",
                        "engine_id": "GenericTransitionEngine",
                        "stop_reason": declared_gate["blocker_type"],
                        "trace": [],
                        "blockers": [declared_gate],
                        "next_allowed_intents": declared_gate[
                            "minimum_return_path"
                        ]["intents"],
                    },
                )

        transitions = (
            "REQUIREMENT_CLASSIFICATION",
            "CHARTER_CLAUSE_DISPOSITION",
            "POLICY_COVERAGE",
            "ARCHITECTURE_CANDIDATE",
            "RUN_CONTRACT",
            "EVIDENCE_APPLICABILITY",
            "AUTHORING_READBACK",
        )
        requirement_ir = snapshot["requirement_ir"]
        authoring_basis_sha256 = content_sha256(
            {
                "program_id": snapshot["program_id"],
                "requirement_epoch": snapshot["requirement_epoch"],
                "requirement_ir": requirement_ir,
                "source_registry": snapshot["source_registry"],
            }
        )
        step_evidence = {
            "REQUIREMENT_CLASSIFICATION": {
                "atom_count": len(requirement_ir.get("atoms", [])),
                "acceptance_case_count": len(
                    requirement_ir.get("acceptance_cases", [])
                ),
                "negative_case_count": len(
                    requirement_ir.get("negative_cases", [])
                ),
            },
            "CHARTER_CLAUSE_DISPOSITION": {
                "scope_count": len(target.get("scope", [])),
                "non_goal_count": len(target.get("non_goals", [])),
                "disposition": "BOUND_TO_REQUIREMENT_IR",
            },
            "POLICY_COVERAGE": {
                "policy_status": target.get("authoring_policy_status", "READY"),
                "unknown_policy": "FAIL_CLOSED",
                "conflict_policy": "FAIL_CLOSED",
            },
            "ARCHITECTURE_CANDIDATE": {
                "profile": target.get("profile"),
                "primary_runtime": target.get("primary_runtime"),
                "architecture_epoch": target.get("architecture_epoch"),
            },
            "RUN_CONTRACT": {
                "execution_mode": "AUTHORING_ONLY",
                "execution_started": False,
                "state_commit": "SINGLE_CAS",
            },
            "EVIDENCE_APPLICABILITY": {
                "acceptance_cases_applicable": True,
                "negative_cases_applicable": True,
                "validator_substitution_allowed": False,
            },
            "AUTHORING_READBACK": {
                "requirement_ir_sha256": content_sha256(requirement_ir),
                "source_registry_sha256": content_sha256(
                    snapshot["source_registry"]
                ),
            },
        }
        contracts = {
            transition_id: {
                "transition_id": transition_id,
                "authoring_basis_sha256": authoring_basis_sha256,
                "next_transition_id": (
                    transitions[index + 1]
                    if index + 1 < len(transitions)
                    else None
                ),
            }
            for index, transition_id in enumerate(transitions)
        }
        gaps = self._requirement_gaps(snapshot)

        def execute(contract: Mapping[str, Any]) -> dict[str, Any]:
            transition_id = str(contract["transition_id"])
            if transition_id == "REQUIREMENT_CLASSIFICATION" and gaps:
                return {
                    "status": "STOPPED",
                    "transition_id": transition_id,
                    "stop_reason": "BLOCKING_HIGH_CONFLICT",
                    "finding": "Requirement classification is incomplete.",
                    "evidence": deepcopy(gaps),
                }
            return {
                "status": "COMMITTED",
                "transition_id": transition_id,
                "next_transition_id": contract.get("next_transition_id"),
                "authoring_basis_sha256": contract["authoring_basis_sha256"],
                "finding": f"{transition_id} completed without a real human gate.",
                "evidence": deepcopy(step_evidence[transition_id]),
                "human_gate": False,
            }

        from .control_kernel import GenericTransitionEngine

        advanced = GenericTransitionEngine.advance_path_until_gate(
            start_transition_id=transitions[0],
            resolve_transition=contracts.get,
            execute_transition=execute,
            max_transitions=len(transitions),
        )
        trace = [
            {
                **item,
                "status": (
                    "COMPLETED" if item.get("status") == "COMMITTED" else "STOPPED"
                ),
            }
            for item in advanced["trace"]
        ]
        if gaps:
            blocker = self._typed_authoring_blocker(
                blocker_type="BLOCKING_HIGH_CONFLICT",
                owner="REQUIREMENT_OWNER",
                finding="Requirement classification found blocking gaps or conflicts.",
                evidence=gaps,
                intents=["UPDATE_REQUIREMENTS", "ANSWER"],
            )
            snapshot["factory_state"] = "BLOCKED_REQUIREMENT_GAP"
            snapshot["blockers"] = [blocker]
            self._sync_ir_metadata(snapshot, open_questions=gaps)
            return TransitionOutcome(
                snapshot=snapshot,
                event_type="AUTHORING_AUTO_ADVANCE_STOPPED",
                response={
                    "status": "STOPPED_AT_REAL_GATE",
                    "response_type": "AUTHORING_GATE",
                    "engine_id": "GenericTransitionEngine",
                    "stop_reason": "BLOCKING_HIGH_CONFLICT",
                    "trace": trace,
                    "blockers": [blocker],
                    "questions": gaps[:3],
                    "question_count": len(gaps),
                    "next_allowed_intents": ["UPDATE_REQUIREMENTS", "ANSWER"],
                },
            )

        readback = self._prepare_readback(snapshot, request, now)
        snapshot = readback.snapshot
        snapshot["authoring_auto_advance"] = {
            "engine_id": "GenericTransitionEngine",
            "status": "STOPPED_AT_REAL_GATE",
            "stop_reason": "WAITING_REQUIREMENT_FREEZE",
            "trace": trace,
            "authoring_basis_sha256": authoring_basis_sha256,
            "completed_at": now,
        }
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="AUTHORING_AUTO_ADVANCED_TO_REAL_GATE",
            response={
                "status": "STOPPED_AT_REAL_GATE",
                "response_type": "AUTHORING_READBACK",
                "engine_id": "GenericTransitionEngine",
                "stop_reason": "WAITING_REQUIREMENT_FREEZE",
                "trace": trace,
                "readback_sha256": readback.response["readback_sha256"],
                "next_allowed_intents": readback.response[
                    "next_allowed_intents"
                ],
                "human_summary": (
                    "Internal Authoring checks completed in one CAS; Requirement Freeze is the next real gate."
                ),
            },
        )

    def _authoring_real_gate_response(self, record: ProgramRecord) -> dict[str, Any]:
        blockers = deepcopy(record.snapshot.get("blockers", []))
        stop_reason = {
            "BLOCKED_REQUIREMENT_GAP": "BLOCKING_HIGH_CONFLICT",
            "BLOCKED_SOURCE_CONFLICT": "WAITING_EXTERNAL_STATE",
            "BLOCKED_AUTHORING_RISK": (
                blockers[0].get("blocker_type", "POLICY_UNKNOWN")
                if blockers and isinstance(blockers[0], Mapping)
                else "POLICY_UNKNOWN"
            ),
            "REQUIREMENTS_READBACK_READY": "WAITING_REQUIREMENT_FREEZE",
            "WAITING_REQUIREMENTS_FREEZE": "WAITING_REQUIREMENT_FREEZE_CONFIRMATION",
            "REQUIREMENTS_FROZEN": "REQUIREMENTS_FROZEN",
            TERMINAL_CANDIDATE_STATE: "WAITING_CANDIDATE_HUMAN_REVIEW",
        }[record.factory_state]
        auto = record.snapshot.get("authoring_auto_advance", {})
        return {
            "schema_version": "2.9",
            "status": "ALREADY_AT_REAL_GATE",
            "response_type": "AUTHORING_GATE",
            "program_id": record.program_id,
            "revision": record.revision,
            "state_hash": record.state_hash,
            "factory_state": record.factory_state,
            "engine_id": "GenericTransitionEngine",
            "stop_reason": stop_reason,
            "trace": deepcopy(auto.get("trace", [])),
            "blockers": blockers,
            "next_allowed_intents": self._next_allowed_intents(
                record.factory_state
            ),
            "writes_performed": False,
            "execution_started": False,
        }

    def _validate_authoring_epoch_pair(self, snapshot: Mapping[str, Any]) -> None:
        target = snapshot.get("requirement_ir", {}).get("target", {})
        if not isinstance(target, Mapping):
            return
        architecture_epoch = target.get("architecture_epoch")
        control_plane_epoch = target.get("control_plane_epoch")
        if architecture_epoch is None and control_plane_epoch is None:
            return
        if (
            not isinstance(architecture_epoch, int)
            or isinstance(architecture_epoch, bool)
            or not isinstance(control_plane_epoch, int)
            or isinstance(control_plane_epoch, bool)
            or architecture_epoch != control_plane_epoch
        ):
            self._contract_gate(
                "MIXED_EPOCH",
                "Authoring Architecture and Control Plane epochs must match",
            )

    def _validate_authoring_policy(self, target: Mapping[str, Any]) -> None:
        status = target.get("authoring_policy_status")
        if status is None or status == "READY":
            return
        if status == "CONFLICT":
            self._contract_gate(
                "POLICY_CONFLICT",
                "Authoring policy inputs conflict at the active authority precedence",
            )
        self._contract_gate(
            "POLICY_UNKNOWN",
            "Authoring policy status is unknown or unsupported",
        )

    @staticmethod
    def _typed_authoring_blocker(
        *,
        blocker_type: str,
        owner: str,
        finding: str,
        evidence: Any,
        intents: list[str],
    ) -> dict[str, Any]:
        return {
            "blocker_type": blocker_type,
            "owner": owner,
            "finding": finding,
            "evidence": deepcopy(evidence),
            "prohibited_substitute_evidence": [
                "VALIDATOR_PASS_ONLY",
                "MANIFEST_PRESENCE_ONLY",
                "CHAT_MEMORY_ONLY",
            ],
            "minimum_return_path": {"intents": intents},
            "human_gate": True,
        }

    def _declared_authoring_risk_gate(
        self, target: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        cases = (
            (
                bool(target.get("external_state_required")),
                "external_state_required",
                "WAITING_EXTERNAL_STATE",
                "EXTERNAL_STATE_OWNER",
                "A declared external state dependency is not ready.",
            ),
            (
                bool(target.get("authority_expansion_required")),
                "authority_expansion_required",
                "AUTHORITY_EXPANSION",
                "AUTHORITY_OWNER",
                "The next Authoring transition requires expanded authority.",
            ),
            (
                bool(target.get("irreversible_risk")),
                "irreversible_risk",
                "IRREVERSIBLE_RISK",
                "RISK_OWNER",
                "The next Authoring transition declares irreversible risk.",
            ),
        )
        for active, target_field, blocker_type, owner, finding in cases:
            if active:
                return self._typed_authoring_blocker(
                    blocker_type=blocker_type,
                    owner=owner,
                    finding=finding,
                    evidence={"target_field": target_field, "value": True},
                    intents=["REOPEN"],
                )
        return None

    def _prepare_readback(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        if snapshot["factory_state"] not in {"INTAKE_OPEN", "CLARIFYING", "REQUIREMENTS_READBACK_READY"}:
            raise InvalidTransitionError(
                "PREPARE_READBACK is not allowed from current state",
                details={"factory_state": snapshot["factory_state"]},
            )
        gaps = self._requirement_gaps(snapshot)
        if gaps:
            snapshot["factory_state"] = "BLOCKED_REQUIREMENT_GAP"
            snapshot["blockers"] = [
                {"code": item["question_id"], "detail": item["prompt"]}
                for item in gaps
            ]
            self._sync_ir_metadata(snapshot, open_questions=gaps)
            return TransitionOutcome(
                snapshot=snapshot,
                event_type="REQUIREMENTS_READBACK_BLOCKED",
                response={
                    "status": "BLOCKED",
                    "response_type": "QUESTIONS",
                    "questions": gaps[:3],
                    "question_count": len(gaps),
                    "blockers": snapshot["blockers"],
                    "next_allowed_intents": ["UPDATE_REQUIREMENTS", "ANSWER"],
                },
            )
        snapshot["blockers"] = []
        snapshot["factory_state"] = "REQUIREMENTS_READBACK_READY"
        self._sync_ir_metadata(snapshot, open_questions=[])
        readback_hash = content_sha256(
            {
                "requirement_ir": snapshot["requirement_ir"],
                "source_registry": snapshot["source_registry"],
                "requirement_epoch": snapshot["requirement_epoch"],
            }
        )
        snapshot["readback"] = {
            "status": "READY",
            "readback_sha256": readback_hash,
            "prepared_at": now,
        }
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="REQUIREMENTS_READBACK_PREPARED",
            response={
                "response_type": "READBACK",
                "readback_sha256": readback_hash,
                "requirement_ir": snapshot["requirement_ir"],
                "source_registry": snapshot["source_registry"],
                "next_allowed_intents": ["REQUEST_FREEZE", "UPDATE_REQUIREMENTS", "ANSWER"],
            },
        )

    def _request_freeze(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        if snapshot["factory_state"] != "REQUIREMENTS_READBACK_READY":
            raise InvalidTransitionError(
                "REQUEST_FREEZE requires REQUIREMENTS_READBACK_READY",
                details={"factory_state": snapshot["factory_state"]},
            )
        source_conflicts = self._source_conflicts(snapshot)
        if source_conflicts:
            snapshot["factory_state"] = "BLOCKED_SOURCE_CONFLICT"
            snapshot["blockers"] = source_conflicts
            return TransitionOutcome(
                snapshot=snapshot,
                event_type="SOURCE_CONFLICT_DETECTED",
                response={
                    "status": "BLOCKED",
                    "response_type": "BLOCKER",
                    "blockers": source_conflicts,
                    "next_allowed_intents": ["REOPEN"],
                },
            )
        gaps = self._requirement_gaps(snapshot)
        if gaps:
            raise InvalidTransitionError(
                "requirements are not eligible for freeze",
                details={"questions": gaps},
            )
        requirement_hash = content_sha256(snapshot["requirement_ir"])
        source_hash = content_sha256(snapshot["source_registry"])
        challenge_id = f"FREEZE-{uuid.uuid4().hex.upper()}"
        confirmation_token = f"CONFIRM_REQUIREMENTS_FREEZE {challenge_id} {requirement_hash}"
        snapshot["factory_state"] = "WAITING_REQUIREMENTS_FREEZE"
        snapshot["freeze"] = {
            "status": "WAITING_HUMAN_CONFIRMATION",
            "challenge_id": challenge_id,
            "requirement_ir_sha256": requirement_hash,
            "source_registry_sha256": source_hash,
            "spec_content_sha256": snapshot["spec_lock"]["content_sha256"],
            "requirement_epoch": snapshot["requirement_epoch"],
            "requested_at": now,
            "requested_by": request.actor.as_dict(),
            "confirmation_token": confirmation_token,
        }
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="REQUIREMENTS_FREEZE_REQUESTED",
            response={
                "status": "WAITING_USER",
                "response_type": "APPROVAL_REQUIRED",
                "approval_challenge": snapshot["freeze"],
                "human_summary": (
                    f"Explicit human confirmation is required for {challenge_id}; "
                    "the Factory cannot self-approve."
                ),
                "next_allowed_intents": ["CONFIRM_FREEZE", "REOPEN"],
            },
        )

    def _confirm_freeze(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        if snapshot["factory_state"] != "WAITING_REQUIREMENTS_FREEZE":
            raise InvalidTransitionError(
                "CONFIRM_FREEZE requires WAITING_REQUIREMENTS_FREEZE",
                details={"factory_state": snapshot["factory_state"]},
            )
        if "HUMAN" not in request.actor.type.upper():
            raise InvalidTransitionError(
                "requirements freeze must be confirmed by a human actor",
                details={"actor_type": request.actor.type},
            )
        challenge = snapshot["freeze"]
        challenge_id = request.payload.get("challenge_id") or request.payload.get(
            "approval_challenge_id"
        )
        requirement_hash = request.payload.get("requirement_ir_sha256") or request.payload.get(
            "requirement_hash"
        )
        decision = str(request.payload.get("decision", "")).upper()
        approved = request.payload.get("approved") is True or decision in {
            "APPROVE",
            "APPROVED",
            "CONFIRM",
        }
        confirmation_text = request.payload.get("confirmation_text")
        if challenge_id != challenge["challenge_id"]:
            raise InvalidTransitionError(
                "freeze challenge_id does not match",
                details={"expected": challenge["challenge_id"], "actual": challenge_id},
            )
        if requirement_hash != challenge["requirement_ir_sha256"]:
            raise InvalidTransitionError(
                "freeze requirement hash does not match",
                details={
                    "expected": challenge["requirement_ir_sha256"],
                    "actual": requirement_hash,
                },
            )
        if confirmation_text != challenge.get("confirmation_token"):
            raise InvalidTransitionError(
                "freeze confirmation_text must exactly repeat the bound confirmation token"
            )
        requested_by = challenge.get("requested_by", {})
        if (
            request.actor.chat_thread_id != requested_by.get("chat_thread_id")
            or request.actor.turn_id == requested_by.get("turn_id")
        ):
            raise InvalidTransitionError(
                "freeze confirmation must come from a later user turn in the same Chat"
            )
        if content_sha256(snapshot.get("source_registry", [])) != challenge.get(
            "source_registry_sha256"
        ):
            raise InvalidTransitionError("source registry changed after freeze challenge")
        source_conflicts = self._source_conflicts(snapshot)
        if source_conflicts:
            snapshot["factory_state"] = "BLOCKED_SOURCE_CONFLICT"
            snapshot["blockers"] = source_conflicts
            return TransitionOutcome(
                snapshot=snapshot,
                event_type="SOURCE_CONFLICT_DETECTED",
                response={
                    "status": "BLOCKED",
                    "response_type": "BLOCKER",
                    "blockers": source_conflicts,
                    "next_allowed_intents": ["REOPEN"],
                },
            )
        if not approved:
            raise InvalidTransitionError("freeze confirmation must explicitly approve")
        if content_sha256(snapshot["requirement_ir"]) != requirement_hash:
            raise InvalidTransitionError("requirements changed after freeze challenge")
        snapshot["factory_state"] = "REQUIREMENTS_FROZEN"
        snapshot["freeze"] = {
            **challenge,
            "status": "FROZEN",
            "approved_at": now,
            "approved_by": request.actor.as_dict(),
            "decision_evidence": {
                "request_id": request.request_id,
                "chat_thread_id": request.actor.chat_thread_id,
                "turn_id": request.actor.turn_id,
            },
        }
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="REQUIREMENTS_FROZEN_BY_HUMAN",
            response={
                "response_type": "RESULT",
                "freeze_lock": snapshot["freeze"],
                "next_allowed_intents": ["GENERATE", "REOPEN"],
                "human_summary": "Requirements are frozen; no target execution is authorized.",
            },
        )

    def _prepare_architecture_readback(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        if snapshot.get("factory_state") != "REQUIREMENTS_FROZEN":
            raise InvalidTransitionError(
                "PREPARE_ARCHITECTURE_READBACK requires REQUIREMENTS_FROZEN",
                details={"factory_state": snapshot.get("factory_state")},
            )
        requirement = self._requirement_readback_from_snapshot(snapshot)
        readback = self._build_architecture_readback(snapshot)
        readback_hash = content_sha256(readback)
        snapshot["architecture_lifecycle"] = {
            "status": "READBACK_READY",
            "requirement_lock_sha256": requirement["requirement_lock"][
                "requirement_lock_sha256"
            ],
            "architecture_epoch": readback["architecture_epoch"],
            "control_plane_epoch": readback["control_plane_epoch"],
            "architecture_readback": readback,
            "architecture_readback_sha256": readback_hash,
            "prepared_at": now,
            "prepared_by": request.actor.as_dict(),
        }
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="ARCHITECTURE_READBACK_PREPARED",
            response={
                "response_type": "ARCHITECTURE_READBACK",
                "architecture_readback": readback,
                "architecture_readback_sha256": readback_hash,
                "next_allowed_intents": [
                    "REQUEST_ARCHITECTURE_LOCK",
                    "REOPEN",
                ],
                "human_summary": (
                    "Architecture Readback is ready; no lock or execution was granted."
                ),
            },
        )

    def _request_architecture_lock(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        lifecycle = snapshot.get("architecture_lifecycle")
        if (
            snapshot.get("factory_state") != "REQUIREMENTS_FROZEN"
            or not isinstance(lifecycle, Mapping)
            or lifecycle.get("status") != "READBACK_READY"
        ):
            raise InvalidTransitionError(
                "REQUEST_ARCHITECTURE_LOCK requires an Architecture Readback",
                details={"factory_state": snapshot.get("factory_state")},
            )
        requirement = self._requirement_readback_from_snapshot(snapshot)
        readback = self._build_architecture_readback(snapshot)
        readback_hash = content_sha256(readback)
        if (
            lifecycle.get("architecture_readback_sha256") != readback_hash
            or lifecycle.get("requirement_lock_sha256")
            != requirement["requirement_lock"]["requirement_lock_sha256"]
        ):
            self._contract_gate(
                "ARCHITECTURE_LOCK_STALE",
                "Architecture or Requirement Lock changed after readback preparation",
            )
        challenge_id = f"ARCH-FREEZE-{uuid.uuid4().hex.upper()}"
        confirmation_token = (
            f"CONFIRM_ARCHITECTURE_LOCK {challenge_id} {readback_hash}"
        )
        snapshot["architecture_lifecycle"] = {
            **deepcopy(dict(lifecycle)),
            "status": "WAITING_HUMAN_CONFIRMATION",
            "challenge_id": challenge_id,
            "confirmation_token": confirmation_token,
            "requested_at": now,
            "requested_by": request.actor.as_dict(),
        }
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="ARCHITECTURE_LOCK_REQUESTED",
            response={
                "status": "WAITING_USER",
                "response_type": "APPROVAL_REQUIRED",
                "approval_challenge": {
                    "challenge_id": challenge_id,
                    "architecture_readback_sha256": readback_hash,
                    "requirement_lock_sha256": lifecycle[
                        "requirement_lock_sha256"
                    ],
                    "architecture_epoch": lifecycle["architecture_epoch"],
                    "control_plane_epoch": lifecycle["control_plane_epoch"],
                    "confirmation_token": confirmation_token,
                    "requested_at": now,
                    "requested_by": request.actor.as_dict(),
                },
                "next_allowed_intents": [
                    "CONFIRM_ARCHITECTURE_LOCK",
                    "REOPEN",
                ],
                "human_summary": (
                    "Exact later human confirmation is required; the Factory cannot self-lock Architecture."
                ),
            },
        )

    def _confirm_architecture_lock(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        lifecycle = snapshot.get("architecture_lifecycle")
        if (
            snapshot.get("factory_state") != "REQUIREMENTS_FROZEN"
            or not isinstance(lifecycle, Mapping)
            or lifecycle.get("status") != "WAITING_HUMAN_CONFIRMATION"
        ):
            raise InvalidTransitionError(
                "CONFIRM_ARCHITECTURE_LOCK requires a pending challenge"
            )
        challenge_id = request.payload.get("challenge_id")
        readback_hash = request.payload.get("architecture_readback_sha256")
        confirmation_text = request.payload.get("confirmation_text")
        decision = str(request.payload.get("decision", "")).upper()
        approved = request.payload.get("approved") is True or decision in {
            "APPROVE",
            "APPROVED",
            "CONFIRM",
        }
        if challenge_id != lifecycle.get("challenge_id"):
            raise InvalidTransitionError("architecture challenge_id does not match")
        if readback_hash != lifecycle.get("architecture_readback_sha256"):
            raise InvalidTransitionError(
                "architecture readback hash does not match"
            )
        if confirmation_text != lifecycle.get("confirmation_token"):
            raise InvalidTransitionError(
                "architecture confirmation_text must exactly repeat the bound token"
            )
        requested_by = lifecycle.get("requested_by", {})
        if (
            request.actor.chat_thread_id != requested_by.get("chat_thread_id")
            or request.actor.turn_id == requested_by.get("turn_id")
        ):
            raise InvalidTransitionError(
                "architecture confirmation must come from a later user turn in the same Chat"
            )
        if not approved:
            raise InvalidTransitionError(
                "architecture confirmation must explicitly approve"
            )
        requirement = self._requirement_readback_from_snapshot(snapshot)
        readback = self._build_architecture_readback(snapshot)
        if content_sha256(readback) != readback_hash:
            self._contract_gate(
                "ARCHITECTURE_LOCK_STALE",
                "Architecture input changed after lock challenge",
            )
        requirement_lock_sha256 = requirement["requirement_lock"][
            "requirement_lock_sha256"
        ]
        if lifecycle.get("requirement_lock_sha256") != requirement_lock_sha256:
            self._contract_gate(
                "REQUIREMENT_LOCK_STALE",
                "Requirement Lock changed after Architecture challenge",
            )
        topology = {
            field: deepcopy(readback[field])
            for field in (
                "capabilities",
                "stages",
                "subharnesses",
                "modules",
                "rules",
                "policies",
                "tools",
                "interfaces",
            )
        }
        architecture_lock = {
            "schema_version": "2.9",
            "status": "LOCKED",
            "requirement_lock_sha256": requirement_lock_sha256,
            "architecture_readback_sha256": readback_hash,
            "topology_sha256": content_sha256(topology),
            "policy_refs": [
                f"architecture-readback://policies/{index}"
                for index, _ in enumerate(readback["policies"])
            ],
            "tool_manifest_ref": "architecture-readback://tools",
            "failure_return_map_sha256": content_sha256(
                readback["failure_returns"]
            ),
            "requirement_epoch": snapshot.get("requirement_epoch"),
            "architecture_epoch": readback["architecture_epoch"],
            "control_plane_epoch": readback["control_plane_epoch"],
            "locked_at": now,
            "approval_receipt_ref": (
                f"factory-event://{snapshot.get('program_id')}/{request.request_id}"
            ),
        }
        architecture_lock["architecture_lock_sha256"] = content_sha256(
            architecture_lock
        )
        snapshot["architecture_lifecycle"] = {
            **deepcopy(dict(lifecycle)),
            "status": "LOCKED",
            "locked_at": now,
            "locked_by": request.actor.as_dict(),
            "decision_evidence": {
                "request_id": request.request_id,
                "chat_thread_id": request.actor.chat_thread_id,
                "turn_id": request.actor.turn_id,
            },
            "architecture_lock": architecture_lock,
        }
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="ARCHITECTURE_LOCKED_BY_HUMAN",
            response={
                "response_type": "RESULT",
                "architecture_lock": architecture_lock,
                "next_allowed_intents": ["REOPEN"],
                "human_summary": (
                    "Architecture is locked; compile is read-only and no execution is authorized."
                ),
            },
        )

    def _generate(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        if snapshot["factory_state"] != "REQUIREMENTS_FROZEN":
            raise InvalidTransitionError(
                "GENERATE requires REQUIREMENTS_FROZEN",
                details={"factory_state": snapshot["factory_state"]},
            )
        if self._requirement_gaps(snapshot):
            raise InvalidTransitionError("frozen requirement IR no longer passes completeness")
        if snapshot["freeze"].get("requirement_ir_sha256") != content_sha256(
            snapshot["requirement_ir"]
        ):
            raise InvalidTransitionError("frozen requirement hash no longer matches")
        unexpected_overrides = sorted(
            key for key in ("staging_root", "target_root") if key in request.payload
        )
        if unexpected_overrides:
            raise RequestValidationError(
                "GENERATE cannot override frozen output or Factory staging paths",
                details={"forbidden_fields": unexpected_overrides},
            )
        generation_readiness: dict[str, Any] | None = None
        if int(snapshot.get("requirement_epoch", 0)) >= 38:
            generation_readiness = self._generation_readiness_from_snapshot(snapshot)
        authority_provenance = _factory_authority_provenance(snapshot)
        snapshot["generation_trace"] = [
            {
                "state": "GENERATING",
                "status": "ENTERED",
                "at": now,
                "side_effect_boundary": "STAGING_ONLY",
            }
        ]
        source_conflicts = self._source_conflicts(snapshot)
        if source_conflicts:
            snapshot["factory_state"] = "BLOCKED_SOURCE_CONFLICT"
            snapshot["blockers"] = source_conflicts
            return TransitionOutcome(
                snapshot=snapshot,
                event_type="SOURCE_CONFLICT_DETECTED",
                response={
                    "status": "BLOCKED",
                    "response_type": "BLOCKER",
                    "blockers": source_conflicts,
                    "next_allowed_intents": ["REOPEN"],
                },
            )

        try:
            from .compiler import compile_candidate
        except ImportError as exc:  # pragma: no cover - integration guard
            raise CandidateValidationError(
                "candidate compiler module is unavailable", details={"error": str(exc)}
            ) from exc

        program_id = snapshot["program_id"]
        program_root = self.runs_root / program_id
        frozen_output_root = snapshot["requirement_ir"]["target"]["output_root"]
        target_root = Path(frozen_output_root).expanduser().resolve()
        protected_roots = [
            self.spec_root,
            Path(__file__).resolve().parents[2],
            self.runs_root,
        ]
        for source in snapshot.get("source_registry", []):
            if not isinstance(source, Mapping):
                continue
            location = source.get("path_or_uri") or source.get("path")
            if isinstance(location, str) and "://" not in location:
                protected_roots.append(Path(location).expanduser().resolve())
        overlap = next(
            (
                protected
                for protected in protected_roots
                if _paths_overlap(target_root, protected)
            ),
            None,
        )
        if overlap is not None:
            raise RequestValidationError(
                "target output_root overlaps a protected Factory, specification, run, or source path",
                details={"target_root": str(target_root), "protected_root": str(overlap)},
            )
        target_root.parent.mkdir(parents=True, exist_ok=True)
        request_path_token = content_sha256(request.request_id)[:16]
        staging_root = (
            target_root.parent
            / f".{target_root.name}.hffactory-staging-{program_id}-{request_path_token}"
        ).resolve()
        try:
            result = compile_candidate(
                snapshot["requirement_ir"],
                self.spec_root,
                staging_root,
                target_root,
                snapshot["created_at"],
                snapshot["spec_lock"],
                authority_provenance=authority_provenance,
                generation_readiness=generation_readiness,
            )
        except FileExistsError as exc:
            snapshot["factory_state"] = "OUTPUT_COLLISION"
            snapshot["blockers"] = [
                {
                    "code": "HF28_OUTPUT_COLLISION",
                    "target_root": str(target_root),
                    "message": str(exc),
                }
            ]
            return TransitionOutcome(
                snapshot=snapshot,
                event_type="OUTPUT_COLLISION_DETECTED",
                response={
                    "status": "BLOCKED",
                    "response_type": "BLOCKER",
                    "blockers": snapshot["blockers"],
                    "next_allowed_intents": ["REOPEN"],
                },
            )
        if isinstance(result, Mapping):
            compiler_result = dict(result)
            prepublication_validation_report = compiler_result.pop(
                "_prepublication_validation_report", None
            )
            candidate_path = Path(
                compiler_result.get("candidate_path")
                or compiler_result.get("candidate_root")
                or compiler_result.get("target_root")
                or target_root
            ).expanduser().resolve()
        elif isinstance(result, (str, os.PathLike)):
            candidate_path = Path(result).expanduser().resolve()
            compiler_result = {"candidate_path": str(candidate_path)}
            prepublication_validation_report = None
        else:
            candidate_path = target_root
            compiler_result = {"candidate_path": str(candidate_path)}
            prepublication_validation_report = None

        requirement_epoch = int(snapshot.get("requirement_epoch", 0))
        generation_commit_binding: dict[str, Any] | None = None
        if requirement_epoch >= 31:
            if not isinstance(prepublication_validation_report, Mapping):
                raise CandidateValidationError(
                    "Epoch 31 generation requires the compiler's constrained prepublication validation report"
                )
            validation_report = dict(prepublication_validation_report)
            generation_commit_binding = _candidate_generation_commit_binding(
                candidate_path,
                program_id=program_id,
                requirement_epoch=requirement_epoch,
                requirement_ir=snapshot["requirement_ir"],
                authority_provenance=authority_provenance,
                request=request,
                compiler_result=compiler_result,
            )
        else:
            validation_report = self.validate_candidate(
                candidate_path,
                snapshot.get("spec_lock"),
                snapshot.get("source_registry", []),
                snapshot.get("requirement_ir"),
                authority_provenance,
            )
        snapshot["generation_trace"].append(
            {
                "state": "VALIDATING",
                "status": "COMPLETED",
                "at": now,
                "validator_status": validation_report.get("status"),
            }
        )
        validation_pass = validation_report.get("status") == "PASS" or validation_report.get(
            "valid"
        ) is True
        if not validation_pass:
            snapshot["factory_state"] = "BLOCKED_REQUIREMENT_GAP"
            snapshot["candidate"] = {
                "status": "VALIDATION_FAILED",
                "candidate_path": str(candidate_path),
                "compiler_result": compiler_result,
                "validation_report": validation_report,
                "execution_started": False,
            }
            return TransitionOutcome(
                snapshot=snapshot,
                event_type="CANDIDATE_VALIDATION_FAILED",
                response={
                    "status": "BLOCKED",
                    "response_type": "BLOCKER",
                    "candidate": snapshot["candidate"],
                    "next_allowed_intents": ["REOPEN"],
                },
            )

        snapshot["factory_state"] = TERMINAL_CANDIDATE_STATE
        snapshot["generation_trace"].append(
            {
                "state": TERMINAL_CANDIDATE_STATE,
                "status": "ENTERED",
                "at": now,
                "authoring_stop": True,
            }
        )
        snapshot["candidate"] = {
            "status": TARGET_CANDIDATE_STATE,
            "candidate_path": str(candidate_path),
            "compiler_result": compiler_result,
            "validation_report": validation_report,
            "requirement_ir_sha256": content_sha256(snapshot["requirement_ir"]),
            "spec_content_sha256": snapshot["spec_lock"]["content_sha256"],
            "generated_at": now,
            "execution_mode": "AUTHORING_ONLY",
            "execution_started": False,
            "auto_start_generated_workpacks": False,
            "human_approval_status": "PENDING",
        }
        if generation_commit_binding is not None:
            snapshot["candidate"][
                "generation_commit_binding"
            ] = generation_commit_binding
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
            response={
                "status": "WAITING_USER",
                "response_type": "APPROVAL_REQUIRED",
                "candidate": snapshot["candidate"],
                "artifact_refs": [str(candidate_path)],
                "next_allowed_intents": ["REOPEN"],
                "hard_stop": "START_PACKAGE_HUMAN_REVIEW",
                "human_summary": (
                    "Candidate generated and validated. The Factory has stopped; "
                    "no Workpack, Driver, build, install, or certification was started."
                ),
            },
        )

    def _reopen(
        self,
        snapshot: dict[str, Any],
        request: ChatRequest,
        now: str,
    ) -> TransitionOutcome:
        if snapshot["factory_state"] not in {
            "WAITING_REQUIREMENTS_FREEZE",
            "REQUIREMENTS_FROZEN",
            "BLOCKED_REQUIREMENT_GAP",
            "BLOCKED_SOURCE_CONFLICT",
            "BLOCKED_AUTHORING_RISK",
            "OUTPUT_COLLISION",
            TERMINAL_CANDIDATE_STATE,
            "REOPEN_REQUIRED",
        }:
            raise InvalidTransitionError(
                "REOPEN is not allowed from current state",
                details={"factory_state": snapshot["factory_state"]},
            )
        reason = request.payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise RequestValidationError("REOPEN requires a non-empty reason")
        previous_freeze = snapshot.get("freeze")
        previous_candidate = snapshot.get("candidate")
        previous_architecture = snapshot.get("architecture_lifecycle")
        previous_candidate_path = (
            previous_candidate.get("candidate_path")
            if isinstance(previous_candidate, Mapping)
            else None
        )
        snapshot["requirement_epoch"] = int(snapshot.get("requirement_epoch", 0)) + 1
        snapshot["factory_state"] = "CLARIFYING"
        snapshot["freeze"] = {
            "status": "INVALIDATED_BY_REOPEN",
            "invalidated_at": now,
            "previous_freeze_sha256": content_sha256(previous_freeze),
            "reason": reason,
        }
        snapshot["candidate"] = {
            "status": "INVALIDATED_BY_REOPEN",
            "invalidated_at": now,
            "previous_candidate_sha256": content_sha256(previous_candidate),
            "reason": reason,
            "invalidated_candidate_path": previous_candidate_path,
        }
        if previous_architecture is not None:
            snapshot["architecture_lifecycle"] = {
                "status": "INVALIDATED_BY_REOPEN",
                "invalidated_at": now,
                "previous_architecture_sha256": content_sha256(
                    previous_architecture
                ),
                "reason": reason,
            }
        if previous_candidate_path:
            target = snapshot.get("requirement_ir", {}).get("target", {})
            if isinstance(target, dict):
                target["previous_output_root"] = previous_candidate_path
                target["output_root"] = None
        snapshot["blockers"] = []
        snapshot["decisions"].append(
            {
                "decision_id": f"DEC-{uuid.uuid4().hex.upper()}",
                "kind": "REOPEN_REQUIREMENTS",
                "reason": reason,
                "actor": request.actor.as_dict(),
                "recorded_at": now,
            }
        )
        self._sync_ir_metadata(snapshot)
        gaps = self._requirement_gaps(snapshot)
        self._sync_ir_metadata(snapshot, open_questions=gaps)
        return TransitionOutcome(
            snapshot=snapshot,
            event_type="REQUIREMENTS_REOPENED_AND_DOWNSTREAM_INVALIDATED",
            response={
                "response_type": "QUESTIONS",
                "requirement_epoch": snapshot["requirement_epoch"],
                "questions": gaps[:3],
                "next_allowed_intents": self._next_allowed_intents("CLARIFYING"),
            },
        )

    def _verify_locked_spec(self, snapshot: Mapping[str, Any]) -> None:
        lock = snapshot.get("spec_lock", {})
        if isinstance(lock, Mapping) and isinstance(lock.get("files"), Mapping):
            try:
                from .spec_lock import verify_spec_lock

                report = verify_spec_lock(lock, self.spec_root)
            except ImportError as exc:  # pragma: no cover - integration guard
                raise SpecDriftError(
                    "spec lock verifier is unavailable", details={"error": str(exc)}
                ) from exc
            if report.get("status") != "PASS":
                raise SpecDriftError(
                    "Harness Foundry v2.8 exact spec lock no longer verifies",
                    details={"verification_report": report},
                )
            return
        current = self.verify_spec()
        locked = lock.get("content_sha256") if isinstance(lock, Mapping) else None
        if current["content_sha256"] != locked:
            raise SpecDriftError(
                "Harness Foundry v2.8 specification changed after Program creation",
                details={"locked": locked, "current": current["content_sha256"]},
            )

    def _require_mutable_requirements(self, snapshot: Mapping[str, Any]) -> None:
        if snapshot.get("factory_state") in self.FROZEN_STATES or snapshot.get(
            "freeze", {}
        ).get("status") == "FROZEN":
            raise InvalidTransitionError(
                "requirements are frozen; issue REOPEN before changing them",
                details={"required_intent": "REOPEN"},
            )
        if snapshot.get("factory_state") == "WAITING_REQUIREMENTS_FREEZE":
            raise InvalidTransitionError(
                "freeze challenge is active; issue REOPEN before changing requirements",
                details={"required_intent": "REOPEN"},
            )

    def _normalize_requirement_patch(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        if isinstance(payload.get("requirement_ir"), Mapping):
            raw = deepcopy(dict(payload["requirement_ir"]))
        elif isinstance(payload.get("requirements"), Mapping):
            raw = deepcopy(dict(payload["requirements"]))
        else:
            for key in (
                "target",
                "atoms",
                "acceptance_cases",
                "negative_cases",
                "assumptions",
                "open_questions",
                "decisions",
                "user_adjustments",
                "automation",
                "source_conflicts",
            ):
                if key in payload:
                    raw[key] = deepcopy(payload[key])

        target = deepcopy(raw.get("target")) if isinstance(raw.get("target"), Mapping) else {}
        legacy_target_fields = {
            "target_id": "id",
            "target_name": "name",
            "target_type": "type",
            "selected_profile": "profile",
            "profile": "profile",
            "target_root": "output_root",
            "output_root": "output_root",
            "mission": "mission",
            "scope": "scope",
            "non_goals": "non_goals",
            "primary_runtime": "primary_runtime",
        }
        for source_key, target_key in legacy_target_fields.items():
            if source_key in payload:
                target[target_key] = deepcopy(payload[source_key])
            elif source_key in raw and source_key != "target":
                target[target_key] = deepcopy(raw[source_key])
        if "description" in payload and "mission" not in target:
            target["mission"] = payload["description"]
        if target:
            raw["target"] = target

        atom_source = payload.get("atoms", raw.get("atoms"))
        if atom_source is None and isinstance(payload.get("requirements"), list):
            atom_source = payload["requirements"]
        if atom_source is not None:
            if not isinstance(atom_source, list):
                raise RequestValidationError("atoms/requirements list must be an array")
            atoms: list[Any] = []
            for index, atom in enumerate(atom_source, 1):
                if isinstance(atom, str):
                    atoms.append(
                        {
                            "atom_id": f"REQ-{index:03d}",
                            "statement": atom,
                            "source_kind": "USER_CHAT",
                        }
                    )
                elif isinstance(atom, Mapping):
                    atoms.append(deepcopy(dict(atom)))
                else:
                    raise RequestValidationError("each atom must be a string or object")
            raw["atoms"] = atoms

        acceptance = payload.get(
            "acceptance_cases", payload.get("acceptance_criteria", raw.get("acceptance_cases"))
        )
        if acceptance is not None:
            if not isinstance(acceptance, list):
                raise RequestValidationError("acceptance_cases must be an array")
            raw["acceptance_cases"] = deepcopy(acceptance)
        negative = payload.get(
            "negative_cases", payload.get("negative_tests", raw.get("negative_cases"))
        )
        if negative is not None:
            if not isinstance(negative, list):
                raise RequestValidationError("negative_cases must be an array")
            raw["negative_cases"] = deepcopy(negative)

        raw["schema_version"] = SCHEMA_VERSION
        return raw

    def _canonicalize_ir(
        self, requirement_ir: Mapping[str, Any], program_id: str
    ) -> dict[str, Any]:
        ir = deepcopy(dict(requirement_ir))
        ir["schema_version"] = SCHEMA_VERSION
        ir["program_id"] = program_id
        target = ir.get("target")
        if not isinstance(target, Mapping):
            target = {}
        else:
            target = deepcopy(dict(target))
        if isinstance(target.get("type"), str):
            target["type"] = target["type"].upper()
        if isinstance(target.get("profile"), str):
            target["profile"] = target["profile"].upper()
        ir["target"] = target
        for key in (
            "sources",
            "atoms",
            "acceptance_cases",
            "negative_cases",
            "assumptions",
            "open_questions",
            "decisions",
            "user_adjustments",
            "source_conflicts",
        ):
            ir.setdefault(key, [])
        normalized_atoms: list[dict[str, Any]] = []
        for index, value in enumerate(ir.get("atoms", []), 1):
            if not isinstance(value, Mapping):
                normalized_atoms.append({"invalid_value": deepcopy(value)})
                continue
            atom = deepcopy(dict(value))
            atom.setdefault("atom_id", f"ATOM-{index:03d}")
            if "text_or_lossless_paraphrase" not in atom:
                atom["text_or_lossless_paraphrase"] = atom.get("statement") or atom.get("text")
            atom.setdefault("source_id", None)
            atom.setdefault("source_locator", f"chat-requirement-{index}")
            atom.setdefault("modality", "MUST")
            for field in (
                "qualifiers",
                "order_constraints",
                "units",
                "defaults",
                "error_semantics",
                "cancel_retry_timeout",
                "compatibility_constraints",
                "explicit_non_goals",
            ):
                atom.setdefault(field, [])
            atom.setdefault("owner", "MAIN_HARNESS_BUILD")
            atom.setdefault("verification_mode", "HUMAN_REVIEW")
            normalized_atoms.append(atom)
        ir["atoms"] = normalized_atoms
        ir.setdefault(
            "automation",
            {
                "execution_mode": "AUTHORING_ONLY",
                "auto_start_generated_workpacks": False,
                "execution_started": False,
            },
        )
        return normalize_ir_coverage(ir)

    def _sync_ir_metadata(
        self,
        snapshot: dict[str, Any],
        *,
        open_questions: list[dict[str, Any]] | None = None,
    ) -> None:
        ir = self._canonicalize_ir(snapshot["requirement_ir"], snapshot["program_id"])
        ir["sources"] = deepcopy(snapshot.get("source_registry", []))
        default_source_id = (
            ir["sources"][0].get("source_id")
            if ir["sources"] and isinstance(ir["sources"][0], Mapping)
            else None
        )
        for atom in ir.get("atoms", []):
            if isinstance(atom, dict) and not atom.get("source_id"):
                atom["source_id"] = default_source_id
        ir["decisions"] = _merge_json_records(
            ir.get("decisions", []), snapshot.get("decisions", [])
        )
        snapshot["decisions"] = deepcopy(ir["decisions"])
        if open_questions is not None:
            domain_questions = [
                item
                for item in ir.get("open_questions", [])
                if isinstance(item, Mapping)
                and item.get("origin") != "FACTORY_GAP"
            ]
            ir["open_questions"] = _merge_questions(
                domain_questions, open_questions
            )
        snapshot["requirement_ir"] = ir

    def _requirement_gaps(self, snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
        ir = snapshot.get("requirement_ir")
        if not isinstance(ir, Mapping):
            ir = {}
        target = ir.get("target") if isinstance(ir.get("target"), Mapping) else {}
        questions: list[dict[str, Any]] = []

        target_fields = (
            ("id", "REQ-TARGET-ID", "What stable target ID should this Start Package use?"),
            ("name", "REQ-TARGET-NAME", "What is the human-readable target name?"),
            ("type", "REQ-TARGET-TYPE", "Is the target an AGENT, HARNESS, or HYBRID?"),
            ("profile", "REQ-PROFILE", "Which FULL, STANDARD, or LITE profile is required?"),
            ("output_root", "REQ-OUTPUT-ROOT", "What absolute output root should own the target package?"),
            ("mission", "REQ-MISSION", "What bounded mission must the target accomplish?"),
            ("scope", "REQ-SCOPE", "What implementation scope is included?"),
            ("non_goals", "REQ-NON-GOALS", "Which non-goals are explicitly excluded?"),
            ("primary_runtime", "REQ-RUNTIME", "What is the primary runtime or executable surface?"),
        )
        for field, question_id, prompt in target_fields:
            value = target.get(field)
            present = value is not None and value != ""
            if field in {"scope", "non_goals"}:
                present = isinstance(value, list)
                if field == "scope":
                    present = present and bool(value)
            if not present:
                questions.append(_question(question_id, prompt, f"requirement_ir.target.{field}"))

        target_type = str(target.get("type", "")).upper()
        if target.get("type") and target_type not in {"AGENT", "HARNESS", "HYBRID"}:
            questions.append(
                _question(
                    "REQ-TARGET-TYPE-INVALID",
                    "Target type must be AGENT, HARNESS, or HYBRID.",
                    "requirement_ir.target.type",
                )
            )
        profile = str(target.get("profile", "")).upper()
        if target.get("profile") and profile not in {"FULL", "STANDARD", "LITE"}:
            questions.append(
                _question(
                    "REQ-PROFILE-INVALID",
                    "Profile must be FULL, STANDARD, or LITE.",
                    "requirement_ir.target.profile",
                )
            )
        target_id = target.get("id")
        if isinstance(target_id, str) and (
            not SAFE_ID_RE.fullmatch(target_id) or ".." in target_id
        ):
            questions.append(
                _question(
                    "REQ-TARGET-ID-UNSAFE",
                    "Target ID must be a path-safe identifier using letters, digits, dot, underscore, or hyphen.",
                    "requirement_ir.target.id",
                )
            )
        output_root = target.get("output_root")
        if isinstance(output_root, str) and output_root and not Path(output_root).expanduser().is_absolute():
            questions.append(
                _question(
                    "REQ-OUTPUT-ROOT-NOT-ABSOLUTE",
                    "Target output_root must be an absolute path.",
                    "requirement_ir.target.output_root",
                )
            )
        production_semantics_mode = target.get("production_semantics_mode")
        if production_semantics_mode not in (None, "", EXPLICIT_PRODUCTION_MODE):
            questions.append(
                _question(
                    "REQ-PRODUCTION-SEMANTICS-MODE-INVALID",
                    f"production_semantics_mode must be {EXPLICIT_PRODUCTION_MODE} when present.",
                    "requirement_ir.target.production_semantics_mode",
                )
            )
        for key, question_id, prompt in (
            ("atoms", "REQ-ATOMS", "Provide at least one atomic normative requirement."),
            ("acceptance_cases", "REQ-ACCEPTANCE", "Provide at least one positive acceptance case."),
            ("negative_cases", "REQ-NEGATIVE", "Provide at least one negative false-success case."),
        ):
            if not isinstance(ir.get(key), list) or not ir.get(key):
                questions.append(_question(question_id, prompt, f"requirement_ir.{key}"))
        source_ids = {
            item.get("source_id")
            for item in ir.get("sources", [])
            if isinstance(item, Mapping)
        }
        atoms = [item for item in ir.get("atoms", []) if isinstance(item, Mapping)]
        atom_ids = [item.get("atom_id") for item in atoms]
        atom_id_set = set(atom_ids)
        if (
            len(atoms) != len(ir.get("atoms", []))
            or len(set(atom_ids)) != len(atom_ids)
            or any(
                not atom.get("atom_id")
                or not atom.get("text_or_lossless_paraphrase")
                or atom.get("source_id") not in source_ids
                or not atom.get("source_locator")
                or not atom.get("verification_mode")
                for atom in atoms
            )
        ):
            questions.append(
                _question(
                    "REQ-ATOM-TRACEABILITY",
                    "Every Atom needs a unique ID, registered source, locator, lossless text, and verification mode.",
                    "requirement_ir.atoms",
                )
            )
        if explicit_production_enabled(ir):
            production_findings = validate_explicit_production_contracts(ir)
            if production_findings:
                questions.append(
                    _question(
                        "REQ-EXPLICIT-PRODUCTION-CONTRACTS",
                        "Every routed Atom must define an exact Workpack Task Bundle, portable Artifact Obligations, schemas, production and validation rules, Oracle, and failure return. "
                        f"Current findings: {[item['code'] for item in production_findings[:8]]}",
                        "requirement_ir.atoms[*].production_contract",
                    )
                )
        coverage_edges = [
            item
            for item in ir.get("coverage_edges", [])
            if isinstance(item, Mapping)
        ]
        coverage_atom_ids = [item.get("atom_id") for item in coverage_edges]
        if (
            len(coverage_edges) != len(ir.get("coverage_edges", []))
            or len(set(coverage_atom_ids)) != len(coverage_atom_ids)
            or set(coverage_atom_ids) != atom_id_set
            or any(
                not item.get("workpack_ids")
                or not set(item.get("workpack_ids", [])).issubset(WORKPACK_PROJECTS)
                or not item.get("stage_ids")
                or not set(item.get("stage_ids", [])).issubset(PHASE_ORDER)
                or not set(item.get("release_step_ids", [])).issubset(
                    RELEASE_STEP_ORDER
                )
                or set(item.get("owner_project_ids", []))
                != {
                    WORKPACK_PROJECTS[workpack_id]
                    for workpack_id in item.get("workpack_ids", [])
                }
                or not item.get("routing_basis")
                for item in coverage_edges
            )
        ):
            questions.append(
                _question(
                    "REQ-ATOM-COVERAGE-ROUTING",
                    "Every Atom needs explicit, resolvable Workpack, Stage, and optional Release Step coverage before freeze.",
                    "requirement_ir.coverage_edges",
                )
            )
        for key, question_id in (
            ("acceptance_cases", "REQ-ACCEPTANCE-TRACEABILITY"),
            ("negative_cases", "REQ-NEGATIVE-TRACEABILITY"),
        ):
            cases = ir.get(key, [])
            structured = [item for item in cases if isinstance(item, Mapping)]
            case_ids = [item.get("case_id") for item in structured]
            covered = {
                atom_id
                for item in structured
                for atom_id in item.get("atom_ids", [])
                if isinstance(item.get("atom_ids"), list)
            }
            invalid = (
                len(structured) != len(cases)
                or len(set(case_ids)) != len(case_ids)
                or any(
                    not item.get("case_id")
                    or not item.get("description")
                    or not isinstance(item.get("atom_ids"), list)
                    or not item.get("atom_ids")
                    or not set(item.get("atom_ids", [])).issubset(atom_id_set)
                    for item in structured
                )
                or covered != atom_id_set
            )
            if invalid:
                questions.append(
                    _question(
                        question_id,
                        f"Every Atom needs structured, uniquely identified {key} coverage with resolvable atom_ids.",
                        f"requirement_ir.{key}",
                    )
                )
        for conflict in ir.get("source_conflicts", []):
            if (
                isinstance(conflict, Mapping)
                and str(conflict.get("status", "OPEN")).upper()
                not in {"RESOLVED", "CLOSED"}
            ):
                questions.append(
                    {
                        "question_id": str(
                            conflict.get("conflict_id") or "REQ-SOURCE-CONFLICT"
                        ),
                        "blocking": True,
                        "field": "requirement_ir.source_conflicts",
                        "prompt": str(
                            conflict.get("description")
                            or "Resolve the declared source authority conflict."
                        ),
                        "origin": "SOURCE_CONFLICT",
                    }
                )
        for item in ir.get("open_questions", []):
            if (
                isinstance(item, Mapping)
                and item.get("origin") != "FACTORY_GAP"
                and item.get("blocking") is True
                and str(item.get("status", "OPEN")).upper() not in {"RESOLVED", "CLOSED"}
            ):
                questions.append(
                    {
                        **dict(item),
                        "question_id": str(
                            item.get("question_id") or item.get("id") or "REQ-OPEN-QUESTION"
                        ),
                        "prompt": str(
                            item.get("prompt") or item.get("question") or "Resolve the blocking open question."
                        ),
                        "field": str(item.get("field") or "requirement_ir.open_questions"),
                        "blocking": True,
                        "origin": "DOMAIN_OPEN_QUESTION",
                    }
                )
        return questions

    def _source_records(
        self,
        sources: Any,
        now: str,
        *,
        snapshot_root: Path | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(sources, (str, os.PathLike, Mapping)):
            sources = [sources]
        if not isinstance(sources, list):
            raise RequestValidationError("sources must be a path, object, or array")
        records: list[dict[str, Any]] = []
        for source in sources:
            if isinstance(source, Mapping):
                raw_path = source.get("path") or source.get("path_or_uri")
                authority_rank = source.get("authority_rank") or source.get(
                    "authority_level"
                )
                source_id = source.get("source_id")
            else:
                raw_path = source
                authority_rank = None
                source_id = None
            if not isinstance(raw_path, (str, os.PathLike)):
                raise RequestValidationError("each source requires path or path_or_uri")
            raw_location = str(raw_path)
            if "://" in raw_location:
                if not raw_location.startswith("chat://"):
                    raise RequestValidationError(
                        "v0.1 accepts only internal chat:// URIs; URLs and connectors are out of scope"
                    )
                if not isinstance(source, Mapping):
                    raise RequestValidationError(
                        "URI sources require an object with a sha256 binding"
                    )
                sha256 = source.get("sha256")
                if not isinstance(sha256, str) or len(sha256) != 64:
                    raise RequestValidationError(
                        "URI sources require a 64-character sha256"
                    )
                if source.get("copy_policy") == "COPY_IMMUTABLE_SNAPSHOT":
                    raise RequestValidationError(
                        "chat URI sources are already event-bound and cannot be copied as local snapshots"
                    )
                records.append(
                    {
                        "source_id": source_id or f"SRC-{sha256[:16].upper()}",
                        "path_or_uri": raw_location,
                        "sha256": sha256.lower(),
                        "file_count": source.get("file_count", 1),
                        "authority_level": authority_rank or "HUMAN_PROVIDED",
                        "scope": source.get("scope", "Declared requirement source"),
                        "loaded_completely": bool(
                            source.get("loaded_completely", True)
                        ),
                        "copy_policy": source.get("copy_policy", "REFERENCE_ONLY"),
                        "access_mode": "HASH_BOUND_REFERENCE",
                        "registered_at": now,
                    }
                )
                continue
            path = Path(raw_location).expanduser().resolve()
            if not path.exists():
                raise RequestValidationError(
                    "source path does not exist", details={"path": str(path)}
                )
            sha256, file_count = _path_hash(path)
            copy_policy = (
                source.get("copy_policy", "REFERENCE_ONLY")
                if isinstance(source, Mapping)
                else "REFERENCE_ONLY"
            )
            if copy_policy not in {"REFERENCE_ONLY", "COPY_IMMUTABLE_SNAPSHOT"}:
                raise RequestValidationError("unsupported source copy_policy")
            snapshot_path = None
            if copy_policy == "COPY_IMMUTABLE_SNAPSHOT":
                if snapshot_root is None:
                    raise RequestValidationError("snapshot_root is required for immutable source copies")
                snapshot_path = _copy_immutable_snapshot(path, snapshot_root, sha256)
            records.append(
                {
                    "source_id": source_id or f"SRC-{sha256[:16].upper()}",
                    "path_or_uri": str(path),
                    "kind": "DIRECTORY" if path.is_dir() else "FILE",
                    "sha256": sha256,
                    "file_count": file_count,
                    "authority_level": authority_rank or "HUMAN_PROVIDED",
                    "scope": source.get("scope", "Local read-only source")
                    if isinstance(source, Mapping)
                    else "Local read-only source",
                    "loaded_completely": True,
                    "copy_policy": copy_policy,
                    "snapshot_path": str(snapshot_path) if snapshot_path else None,
                    "access_mode": "READ_ONLY_HASH_REGISTERED",
                    "registered_at": now,
                }
            )
        return records

    def _chat_source_record(self, request: ChatRequest, now: str) -> dict[str, Any]:
        sha256 = content_sha256(request.as_dict())
        return {
            "source_id": f"SRC-CHAT-{sha256[:16].upper()}",
            "path_or_uri": (
                f"chat://{request.actor.chat_thread_id}/{request.actor.turn_id}"
            ),
            "sha256": sha256,
            "file_count": 1,
            "authority_level": "HUMAN_VIA_CODEX_CHAT",
            "scope": f"{request.intent} request envelope and payload",
            "loaded_completely": True,
            "copy_policy": "EVENT_LEDGER_REFERENCE",
            "access_mode": "HASH_BOUND_EVENT_REFERENCE",
            "registered_at": now,
        }

    @staticmethod
    def _merge_source_records(
        existing: Iterable[Mapping[str, Any]],
        incoming: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for value in [*existing, *incoming]:
            item = dict(value)
            key = str(item.get("path_or_uri", ""))
            records[key] = item
        return sorted(
            records.values(),
            key=lambda item: (str(item.get("path_or_uri", "")), str(item.get("sha256", ""))),
        )

    def _source_conflicts(
        self, snapshot: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        for source in snapshot.get("source_registry", []):
            if not isinstance(source, Mapping):
                continue
            location = source.get("path_or_uri") or source.get("path")
            if not isinstance(location, str) or "://" in location:
                continue
            path = Path(location).expanduser().resolve()
            if not path.exists():
                conflicts.append(
                    {
                        "code": "HF28_SOURCE_MISSING",
                        "source_id": source.get("source_id"),
                        "path": str(path),
                    }
                )
                continue
            current_sha256, current_file_count = _path_hash(path)
            if (
                current_sha256 != source.get("sha256")
                or current_file_count != source.get("file_count")
            ):
                conflicts.append(
                    {
                        "code": "HF28_SOURCE_CHANGED",
                        "source_id": source.get("source_id"),
                        "path": str(path),
                        "locked_sha256": source.get("sha256"),
                        "current_sha256": current_sha256,
                    }
                )
        return conflicts

    def _export_program_views(self, program_id: str) -> None:
        """Regenerate non-authoritative JSON/JSONL views from SQLite state."""

        record = self.store.get_program(program_id)
        root = self.runs_root / program_id
        for relative in (
            "sources",
            "requirement_ir",
            "decisions",
            "staging",
            "validation",
            "readback",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        snapshot = record.snapshot
        _atomic_write_json(root / "FACTORY_STATE.json", record.as_status())
        _atomic_write_json(
            root / "sources/SOURCE_REGISTRY.json",
            {"program_id": program_id, "sources": snapshot.get("source_registry", [])},
        )
        _atomic_write_json(
            root / "requirement_ir/CURRENT_REQUIREMENT_IR.json",
            snapshot.get("requirement_ir", {}),
        )
        _atomic_write_json(
            root / "decisions/DECISIONS.json",
            {"program_id": program_id, "decisions": snapshot.get("decisions", [])},
        )
        _atomic_write_json(
            root / "readback/READBACK.json",
            {
                "program_id": program_id,
                "factory_state": record.factory_state,
                "state_hash": record.state_hash,
                "requirement_epoch": snapshot.get("requirement_epoch"),
                "freeze": snapshot.get("freeze"),
                "candidate": snapshot.get("candidate"),
                "blockers": snapshot.get("blockers", []),
            },
        )
        events = self.store.list_events(program_id)
        _atomic_write_text(
            root / "readback/EVENTS.jsonl",
            "".join(canonical_json(event) + "\n" for event in events),
        )
        validation = snapshot.get("candidate", {}).get("validation_report")
        if isinstance(validation, Mapping):
            _atomic_write_json(
                root / "validation/CANDIDATE_VALIDATION.json", validation
            )

    def _candidate_boundary_errors(self, root: Path) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        start_context_path = root / "START_CONTEXT.json"
        if not start_context_path.is_file():
            return [
                {
                    "code": "START_CONTEXT_MISSING",
                    "path": str(start_context_path),
                }
            ]
        try:
            context = json.loads(start_context_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [{"code": "START_CONTEXT_INVALID", "detail": str(exc)}]
        expected = {
            "execution_mode": "AUTHORING_ONLY",
            "execution_started": False,
            "install_started": False,
            "certification_started": False,
            "auto_start_generated_workpacks": False,
            "program_driver_started": False,
        }
        for key, value in expected.items():
            if context.get(key) != value:
                errors.append(
                    {
                        "code": "AUTHORING_BOUNDARY_VIOLATION",
                        "field": key,
                        "expected": value,
                        "actual": context.get(key),
                    }
                )
        if context.get("current_state") != TARGET_CANDIDATE_STATE:
            errors.append(
                {
                    "code": "TARGET_CANDIDATE_STATE_MISMATCH",
                    "expected": TARGET_CANDIDATE_STATE,
                    "actual": context.get("current_state"),
                }
            )
        return errors

    @staticmethod
    def _next_allowed_intents(factory_state: str) -> list[str]:
        return {
            "INTAKE_OPEN": ["ADD_SOURCES", "UPDATE_REQUIREMENTS", "ANSWER", "PREPARE_READBACK"],
            "CLARIFYING": ["ADD_SOURCES", "UPDATE_REQUIREMENTS", "ANSWER", "PREPARE_READBACK"],
            "BLOCKED_REQUIREMENT_GAP": ["UPDATE_REQUIREMENTS", "ANSWER", "REOPEN"],
            "BLOCKED_SOURCE_CONFLICT": ["REOPEN"],
            "BLOCKED_AUTHORING_RISK": ["REOPEN"],
            "OUTPUT_COLLISION": ["REOPEN"],
            "REQUIREMENTS_READBACK_READY": ["REQUEST_FREEZE", "UPDATE_REQUIREMENTS", "ANSWER"],
            "WAITING_REQUIREMENTS_FREEZE": ["CONFIRM_FREEZE", "REOPEN"],
            "REQUIREMENTS_FROZEN": [
                "PREPARE_ARCHITECTURE_READBACK",
                "REQUEST_ARCHITECTURE_LOCK",
                "CONFIRM_ARCHITECTURE_LOCK",
                "GENERATE",
                "REOPEN",
            ],
            TERMINAL_CANDIDATE_STATE: ["REOPEN"],
        }.get(factory_state, [])


def _question(question_id: str, prompt: str, field: str) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "blocking": True,
        "field": field,
        "prompt": prompt,
        "origin": "FACTORY_GAP",
    }


def _merge_json_records(
    existing: Iterable[Any], incoming: Iterable[Any]
) -> list[Any]:
    records: dict[str, Any] = {}
    for value in [*existing, *incoming]:
        records[content_sha256(value)] = deepcopy(value)
    return list(records.values())


def _merge_questions(
    existing: Iterable[Mapping[str, Any]], incoming: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for value in [*existing, *incoming]:
        item = dict(value)
        key = str(item.get("question_id") or item.get("id") or content_sha256(item))
        records[key] = item
    return list(records.values())


def _deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _has_material_requirement_patch(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value) and any(
            _has_material_requirement_patch(item) for item in value.values()
        )
    return True


def _path_hash(path: Path) -> tuple[str, int]:
    if path.is_symlink():
        digest = hashlib.sha256(f"SYMLINK:{os.readlink(path)}".encode("utf-8")).hexdigest()
        return digest, 1
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), 1
    if not path.is_dir():
        raise RequestValidationError(
            "source path is not a regular file or directory", details={"path": str(path)}
        )
    digest = hashlib.sha256()
    count = 0
    for child in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        if child.is_dir():
            continue
        relative = child.relative_to(path).as_posix()
        child_hash, child_count = _path_hash(child)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(child_hash.encode("ascii"))
        digest.update(b"\n")
        count += child_count
    return digest.hexdigest(), count


def _copy_immutable_snapshot(path: Path, snapshot_root: Path, sha256: str) -> Path:
    snapshot_root.mkdir(parents=True, exist_ok=True)
    destination = snapshot_root / f"{sha256}-{path.name}"
    if destination.exists():
        existing_hash, _count = _path_hash(destination)
        if existing_hash != sha256:
            raise RequestValidationError(
                "existing immutable snapshot Hash mismatch",
                details={"snapshot_path": str(destination)},
            )
        return destination
    if path.is_dir():
        shutil.copytree(path, destination, symlinks=True)
    else:
        shutil.copy2(path, destination, follow_symlinks=False)
    for child in [destination, *destination.rglob("*")] if destination.is_dir() else [destination]:
        if child.is_file() and not child.is_symlink():
            child.chmod(child.stat().st_mode & ~0o222)
    copied_hash, _count = _path_hash(destination)
    if copied_hash != sha256:
        raise RequestValidationError(
            "immutable snapshot verification failed",
            details={"snapshot_path": str(destination)},
        )
    return destination


def _tree_hash(root: Path) -> tuple[str, int]:
    if not root.is_dir():
        raise SpecVerificationError(
            "spec_root is not a directory", details={"spec_root": str(root)}
        )
    digest = hashlib.sha256()
    count = 0
    excluded_names = {".DS_Store"}
    excluded_parts = {".git", "__pycache__"}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_dir() or path.name in excluded_names:
            continue
        relative_path = path.relative_to(root)
        if any(part in excluded_parts for part in relative_path.parts):
            continue
        file_hash, file_count = _path_hash(path)
        digest.update(relative_path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
        count += file_count
    return digest.hexdigest(), count


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left in right.parents or right in left.parents


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
