"""Normal-path translation regressions; no target execution or media tools."""

from copy import deepcopy
from hashlib import sha256
import json
import re
import unittest

from harness_foundry_factory.invariant_contracts import evaluate_predicate_ast_v1
from harness_foundry_factory.semantic_contracts import (
    _strengthen_artifact_schema, public_skill_job_interface,
    oracle_evaluator_registry,
)
from harness_foundry_factory.validator import (
    _independent_invariant_contract_findings, _oracle_registry_is_independently_consistent,
    _public_entrypoint_pattern_is_complete,
)


def schema(kind):
    return _strengthen_artifact_schema(kind, {"type": "object", "properties": {}})


def contract(kind, name):
    return schema(kind)["x-invariant-contracts"][name]


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class Epoch24SemanticRepairsTests(unittest.TestCase):
    def test_nonzero_motion_uses_threshold_not_self_comparison(self):
        c = contract("MEDIA_ACCEPTANCE_RECEIPT", "EACH_DECLARED_OBJECT_HAS_NONZERO_PROBED_MOTION")
        for counts, expected in (([1, 30], True), ([1, 0], False), ([0, 30], False)):
            result = evaluate_predicate_ast_v1(c["predicate_ast"], {
                "observed_motion_objects": [{"changed_frame_count": n} for n in counts]})
            with self.subTest(counts=counts):
                self.assertEqual(result["passed"], expected, result)
        self.assertEqual(c["operand_refs"], ["/observed_motion_objects/*/changed_frame_count"])

    def test_independent_validator_rejects_binary_threshold_projection(self):
        s = schema("MEDIA_ACCEPTANCE_RECEIPT")
        c = s["x-invariant-contracts"]["EACH_DECLARED_OBJECT_HAS_NONZERO_PROBED_MOTION"]
        for obj in (c, c["predicate_ast"]):
            obj["operand_refs"] = ["/observed_motion_objects/*/changed_frame_count"] * 2
            obj["operand_types"] = ["scalar"] * 2
            obj["parameters"]["operand_scopes"] = ["SUBJECT"] * 2
            obj["cardinality"]["operand_count"] = 2
        findings = _independent_invariant_contract_findings(s, "media")
        self.assertIn("INVARIANT_THRESHOLD_OPERAND_CONFLICT", {f["code"] for f in findings})

    def test_denied_gate_skips_every_authorized_only_predicate(self):
        s = schema("TARGET_SKILL_EXECUTION_GATE_RECEIPT")
        d = {key: None for key in s["properties"]}
        d["status"] = "DENIED_NO_SIDE_EFFECT"
        for name, c in s["x-invariant-contracts"].items():
            if name.startswith("DENIED_"):
                continue
            with self.subTest(invariant=name):
                self.assertEqual(c["branch_selector"], {
                    "mode": "REQUIRE_DISCRIMINATOR_CONST", "discriminator_ref": "/status",
                    "const": "AUTHORIZED_EXECUTION_RECEIPT_VALID"})
                if c["evaluation_contract_kind"] == "TYPED_KERNEL_V1":
                    r = evaluate_predicate_ast_v1(c["predicate_ast"], d)
                    self.assertTrue(r["passed"] and r["skipped"], r)

    def test_authorized_gate_still_checks_real_bytes_and_current_hashes(self):
        s = schema("TARGET_SKILL_EXECUTION_GATE_RECEIPT")
        digest = sha256(b"receipt").hexdigest()
        d = {key: ("memory://receipt" if key.endswith("_ref") else digest)
             for key in s["properties"]}
        d["status"] = "AUTHORIZED_EXECUTION_RECEIPT_VALID"
        for name, c in s["x-invariant-contracts"].items():
            if c["evaluation_contract_kind"] != "TYPED_KERNEL_V1":
                continue
            with self.subTest(invariant=name):
                r = evaluate_predicate_ast_v1(c["predicate_ast"], d, resolver=lambda _: b"receipt")
                self.assertTrue(r["passed"] and not r["skipped"], r)
        d["execution_receipt_sha256"] = "0" * 64
        c = s["x-invariant-contracts"]["TARGET_EXECUTION_RECEIPT_HASH_MATCHES_REFERENCED_BYTES"]
        self.assertFalse(evaluate_predicate_ast_v1(c["predicate_ast"], d,
                                                 resolver=lambda _: b"receipt")["passed"])

    def test_render_member_binding_is_distinct_from_document_hash(self):
        s = schema("LOCAL_RENDER_RECEIPT")
        names = ("RENDER_INPUT_MANIFEST_BINDS_EXACT_ASSET_REFS_AND_SHA256S",
                 "RENDER_INPUT_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES")
        semantic, byte_check = [s["x-invariant-contracts"][n] for n in names]
        self.assertNotEqual(semantic["predicate_ast"], byte_check["predicate_ast"])
        from harness_foundry_factory.media_evidence_contracts import evaluate_media_evidence_contract
        from harness_foundry_factory.mutation_contracts import prepare_referenced_document_mutation
        assets = [{"asset_ref": "memory://asset", "asset_sha256": sha256(b"asset").hexdigest()}]
        data = {"memory://plan": json_bytes({"assets": assets}),
                "memory://manifest": json_bytes({"assets": assets})}
        d = {"asset_plan_ref": "memory://plan", "render_input_manifest_ref": "memory://manifest",
             "render_input_manifest_sha256": sha256(data["memory://manifest"]).hexdigest()}
        self.assertTrue(evaluate_media_evidence_contract(semantic, d, data.__getitem__)["passed"])
        registry = oracle_evaluator_registry({"LOCAL_RENDER_RECEIPT"}, [{"artifact_kind": "LOCAL_RENDER_RECEIPT", "schema": s}])
        case = next(v for v in registry["invariant_negative_case_matrix"] if v["invariant_id"] == names[0])
        mutated, overlay = prepare_referenced_document_mutation(d, case["mutation"]["derivation_recipe"], data.__getitem__)
        resolver = {**data, **overlay}.__getitem__
        self.assertFalse(evaluate_media_evidence_contract(semantic, mutated, resolver)["passed"])
        self.assertTrue(evaluate_predicate_ast_v1(byte_check["predicate_ast"], mutated, resolver=resolver)["passed"])
        d["render_input_manifest_sha256"] = "0" * 64
        self.assertTrue(evaluate_media_evidence_contract(semantic, d, data.__getitem__)["passed"])
        self.assertFalse(evaluate_predicate_ast_v1(byte_check["predicate_ast"], d, resolver=data.__getitem__)["passed"])

    def test_ffprobe_identity_reads_receipt_contents(self):
        c = contract("MEDIA_ACCEPTANCE_RECEIPT", "FFPROBE_INPUT_SHA256_EQUALS_VIDEO_SHA256")
        self.assertIn("/ffprobe_receipt_ref", c["operand_refs"])
        from harness_foundry_factory.media_evidence_contracts import evaluate_media_evidence_contract
        digest = sha256(b"video").hexdigest()
        d = {"video_sha256": digest, "ffprobe_receipt_ref": "memory://probe"}
        for body, expected in (({"input_sha256": digest}, True), ({"input_sha256": "0" * 64}, False), ({}, False)):
            reads = []
            def resolver(ref):
                reads.append(ref)
                return json_bytes(body)
            self.assertEqual(evaluate_media_evidence_contract(c, d, resolver)["passed"], expected)
            self.assertEqual(reads, ["memory://probe"])

    def test_audio_file_identity_is_not_packet_identity(self):
        c = contract("LOCAL_RENDER_RECEIPT", "VIDEO_BYTES_INCLUDE_THE_REFERENCED_AUDIO_STREAM")
        self.assertEqual(c["algorithm"], "AUDIO_FILE_PACKET_LINEAGE_V2")
        from harness_foundry_factory.media_evidence_contracts import evaluate_media_evidence_contract
        audio, packets, video = b"file-header+pcm", b"encoded-packets", b"model-video"
        data = {"memory://audio": audio, "memory://video": video}
        transform = {"input_audio_ref": "memory://audio", "input_audio_sha256": sha256(audio).hexdigest(),
                     "output_video_ref": "memory://video", "packet_payload_sha256": sha256(packets).hexdigest(),
                     "mode": "TRANSCODE", "encoder_parameters": {"codec": "aac", "sample_rate_hz": 48000, "channels": 2}}
        d = {"audio_stream_present": True, "audio_sha256": sha256(audio).hexdigest(),
             "video_ref": "memory://video", "video_sha256": sha256(video).hexdigest(),
             "render_command_receipt_ref": "memory://command"}
        def check(body, replay_packets=packets):
            data["memory://command"] = json_bytes({"audio_transform": body})
            return evaluate_media_evidence_contract(c, d, data.__getitem__,
                packet_reader=lambda content: packets,
                audio_transform_replay=lambda content, mode, parameters: replay_packets)
        self.assertTrue(check(transform)["passed"])
        self.assertFalse(check(transform, b"different-audio-packets")["passed"])
        wrong = deepcopy(transform); wrong["input_audio_sha256"] = "0" * 64
        self.assertFalse(check(wrong)["passed"])
        self.assertFalse(evaluate_media_evidence_contract(c, d, data.__getitem__)["passed"])

    def test_root_and_nested_entrypoints_are_accepted_without_traversal(self):
        interface = public_skill_job_interface({"target": {}})
        pattern = interface["job_request_schema"]["properties"]["skill_entrypoint_ref"]["pattern"]
        for value in ("SKILL.md", "skills/example/SKILL.md", "skills/.system/skill-creator/SKILL.md"):
            self.assertIsNotNone(re.fullmatch(pattern, value), value)
        for value in ("/SKILL.md", "../SKILL.md", "skills/../SKILL.md", "README.md"):
            self.assertIsNone(re.fullmatch(pattern, value), value)

    def test_old_projection_does_not_override_new_producer_semantics(self):
        s = schema("MEDIA_ACCEPTANCE_RECEIPT")
        old = s["x-invariant-contracts"]["FFPROBE_INPUT_SHA256_EQUALS_VIDEO_SHA256"]
        old.update(algorithm="HASH_AND_BYTE_LINEAGE_V1", input_refs=["/video_sha256", "artifact://self"], parameters={})
        rebuilt = _strengthen_artifact_schema("MEDIA_ACCEPTANCE_RECEIPT", s)
        c = rebuilt["x-invariant-contracts"]["FFPROBE_INPUT_SHA256_EQUALS_VIDEO_SHA256"]
        self.assertIn("/ffprobe_receipt_ref", c["operand_refs"])
        self.assertNotEqual(c["algorithm"], "HASH_AND_BYTE_LINEAGE_V1")

    def test_independent_validator_rejects_obsolete_media_semantics(self):
        cases = [
            ("MEDIA_ACCEPTANCE_RECEIPT", "FFPROBE_INPUT_SHA256_EQUALS_VIDEO_SHA256", "HASH_AND_BYTE_LINEAGE_V1"),
            ("LOCAL_RENDER_RECEIPT", "RENDER_INPUT_MANIFEST_BINDS_EXACT_ASSET_REFS_AND_SHA256S", "HASH_AND_BYTE_LINEAGE_V1"),
            ("LOCAL_RENDER_RECEIPT", "VIDEO_BYTES_INCLUDE_THE_REFERENCED_AUDIO_STREAM", "VIDEO_AUDIO_STREAM_BYTE_BINDING_V1"),
        ]
        for kind, name, algorithm in cases:
            s = schema(kind)
            with self.subTest(name=name):
                self.assertFalse(_independent_invariant_contract_findings(s, kind))
                c = s["x-invariant-contracts"][name]
                c["algorithm"] = c["predicate_ast"]["algorithm"] = algorithm
                codes = {f["code"] for f in _independent_invariant_contract_findings(s, kind)}
                self.assertIn("MEDIA_INVARIANT_SEMANTIC_PROJECTION_MISMATCH", codes)

    def test_independent_validator_rejects_wrong_media_field_and_audio_domain(self):
        for kind, name, key, value in [
            ("MEDIA_ACCEPTANCE_RECEIPT", "FFPROBE_INPUT_SHA256_EQUALS_VIDEO_SHA256", "value_pointer", "/receipt_sha256"),
            ("LOCAL_RENDER_RECEIPT", "VIDEO_BYTES_INCLUDE_THE_REFERENCED_AUDIO_STREAM", "output_identity_domain", "WHOLE_AUDIO_FILE_BYTES"),
        ]:
            s = schema(kind); c = s["x-invariant-contracts"][name]
            c["parameters"][key] = c["predicate_ast"]["parameters"][key] = value
            self.assertIn("MEDIA_PARAMETERS_INVALID", {
                f["code"] for f in _independent_invariant_contract_findings(s, kind)})

    def test_independent_validator_rejects_unscoped_authorized_gate(self):
        s = schema("TARGET_SKILL_EXECUTION_GATE_RECEIPT")
        self.assertFalse(_independent_invariant_contract_findings(s, "gate"))
        for name in s["x-invariants"]:
            if name.startswith("DENIED_"):
                continue
            mutated = deepcopy(s)
            for obj in (mutated["x-invariant-contracts"][name], mutated["x-invariant-contracts"][name]["predicate_ast"]):
                obj["branch_selector"] = {"mode": "ANY_JSON_SCHEMA_VALID_BRANCH"}
                obj["branch_precondition"] = "ANY_JSON_SCHEMA_VALID_BRANCH"
            self.assertIn("INVARIANT_BRANCH_PRECONDITION_INCOMPATIBLE", {
                f["code"] for f in _independent_invariant_contract_findings(mutated, "gate")})

    def test_independent_entrypoint_check_rejects_root_exclusion(self):
        good = public_skill_job_interface({"target": {}})["job_request_schema"]["properties"]["skill_entrypoint_ref"]["pattern"]
        self.assertTrue(_public_entrypoint_pattern_is_complete(good))
        for bad in (r".+/SKILL\.md", r".*SKILL\.md", "[", None):
            self.assertFalse(_public_entrypoint_pattern_is_complete(bad), bad)

    def test_render_membership_reorder_passes_but_duplicate_empty_and_changed_fail(self):
        from harness_foundry_factory.media_evidence_contracts import evaluate_media_evidence_contract
        c = contract("LOCAL_RENDER_RECEIPT", "RENDER_INPUT_MANIFEST_BINDS_EXACT_ASSET_REFS_AND_SHA256S")
        assets = [{"asset_ref": f"memory://asset-{i}", "asset_sha256": sha256(bytes([i])).hexdigest()} for i in range(2)]
        d = {"render_input_manifest_ref": "memory://manifest", "asset_plan_ref": "memory://plan"}
        for variant, expected in ((assets[::-1], True), (assets[:1], False), ([], False), ([assets[0]] * 2, False)):
            data = {"memory://plan": json_bytes({"assets": assets}), "memory://manifest": json_bytes({"assets": variant})}
            self.assertEqual(evaluate_media_evidence_contract(c, d, data.__getitem__)["passed"], expected)

    def test_registry_requires_content_mutation_and_manifest_rebinding(self):
        s = schema("LOCAL_RENDER_RECEIPT")
        artifacts = {"render": {"artifact_kind": "LOCAL_RENDER_RECEIPT", "schema": s}}
        registry = oracle_evaluator_registry({"LOCAL_RENDER_RECEIPT"}, list(artifacts.values()))
        self.assertTrue(_oracle_registry_is_independently_consistent(registry, artifacts))
        case = next(c for c in registry["invariant_negative_case_matrix"]
                    if c["invariant_id"] == "RENDER_INPUT_MANIFEST_BINDS_EXACT_ASSET_REFS_AND_SHA256S")
        case["mutation"]["derivation_recipe"].pop("referenced_document_mutation")
        self.assertFalse(_oracle_registry_is_independently_consistent(registry, artifacts))

    def test_gate_negative_base_selects_the_predicate_branch(self):
        s = schema("TARGET_SKILL_EXECUTION_GATE_RECEIPT")
        artifacts = {"gate": {"artifact_kind": "TARGET_SKILL_EXECUTION_GATE_RECEIPT", "schema": s}}
        registry = oracle_evaluator_registry({"TARGET_SKILL_EXECUTION_GATE_RECEIPT"}, list(artifacts.values()))
        for case in registry["invariant_negative_case_matrix"]:
            if case["artifact_kind"] != "TARGET_SKILL_EXECUTION_GATE_RECEIPT":
                continue
            expected = case["invariant_contract"]["branch_selector"]["const"]
            self.assertEqual(case["base_precondition"]["required_branch"], expected)
        case["base_precondition"]["required_branch"] = "ANY_PASSING_BRANCH"
        self.assertFalse(_oracle_registry_is_independently_consistent(registry, artifacts))

    def test_audio_copy_binds_source_video_and_packet_identity(self):
        from harness_foundry_factory.media_evidence_contracts import evaluate_media_evidence_contract
        c = contract("LOCAL_RENDER_RECEIPT", "VIDEO_BYTES_INCLUDE_THE_REFERENCED_AUDIO_STREAM")
        source, video, packets = b"container+source-packets", b"video-container+source-packets", b"source-packets"
        transform = {"input_audio_ref": "audio", "input_audio_sha256": sha256(source).hexdigest(),
                     "output_video_ref": "video", "packet_payload_sha256": sha256(packets).hexdigest(),
                     "mode": "COPY", "encoder_parameters": {"codec": "copy"}}
        d = {"audio_stream_present": True, "audio_sha256": sha256(source).hexdigest(),
             "video_ref": "video", "video_sha256": sha256(video).hexdigest(), "render_command_receipt_ref": "command"}
        data = {"audio": source, "video": video, "command": json_bytes({"audio_transform": transform})}
        calls = []
        def replay(content, mode, parameters):
            calls.append((content, mode, parameters))
            return packets
        def check():
            return evaluate_media_evidence_contract(c, d, data.__getitem__,
                packet_reader=lambda content: packets, audio_transform_replay=replay)
        self.assertTrue(check()["passed"])
        self.assertEqual(calls, [(source, "COPY", {"codec": "copy"})])
        for key, wrong in (("audio", b"other-source"), ("video", b"other-video")):
            saved = data[key]; data[key] = wrong
            self.assertFalse(check()["passed"])
            data[key] = saved
        transform["packet_payload_sha256"] = sha256(b"other-packets").hexdigest()
        data["command"] = json_bytes({"audio_transform": transform})
        self.assertFalse(check()["passed"])

    def test_recompilation_upgrades_all_known_old_shapes_and_is_idempotent(self):
        for kind in ("LOCAL_RENDER_RECEIPT", "MEDIA_ACCEPTANCE_RECEIPT", "TARGET_SKILL_EXECUTION_GATE_RECEIPT"):
            current = schema(kind); legacy = deepcopy(current)
            for name, c in legacy["x-invariant-contracts"].items():
                if name in {"FFPROBE_INPUT_SHA256_EQUALS_VIDEO_SHA256", "RENDER_INPUT_MANIFEST_BINDS_EXACT_ASSET_REFS_AND_SHA256S"}:
                    c.update(algorithm="HASH_AND_BYTE_LINEAGE_V1", input_refs=[c["target_ref"], "artifact://self"], parameters={})
                elif name == "VIDEO_BYTES_INCLUDE_THE_REFERENCED_AUDIO_STREAM":
                    c.update(algorithm="VIDEO_AUDIO_STREAM_BYTE_BINDING_V1", parameters={})
                elif name == "EACH_DECLARED_OBJECT_HAS_NONZERO_PROBED_MOTION":
                    c["input_refs"] = [c["target_ref"], "/observed_motion_objects/*/changed_frame_count"]
                if kind == "TARGET_SKILL_EXECUTION_GATE_RECEIPT" and not name.startswith("DENIED_"):
                    c["branch_selector"] = {"mode": "ANY_JSON_SCHEMA_VALID_BRANCH"}
                    c["branch_precondition"] = "ANY_JSON_SCHEMA_VALID_BRANCH"
            saved = deepcopy(legacy)
            rebuilt = _strengthen_artifact_schema(kind, legacy)
            self.assertEqual(legacy, saved)
            self.assertEqual(rebuilt, current)
            self.assertEqual(_strengthen_artifact_schema(kind, rebuilt), rebuilt)


if __name__ == "__main__":
    unittest.main()
