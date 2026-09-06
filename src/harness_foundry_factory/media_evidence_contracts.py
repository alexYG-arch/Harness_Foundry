"""Pure reference checks for media evidence, not a renderer or target Lab.

The caller owns byte resolution. Audio callbacks must independently extract or
replay packet payloads; this module never runs a subprocess or creates a file.
Unit-test callbacks prove contract behavior, not real media execution.
"""

from hashlib import sha256
import json
import re

from .contract_references import pointer_values


MEDIA_OPERANDS = {
    "RENDER_OBJECT_BINDINGS_V1": ["/rendered_semantic_bindings", "/motion_ir_ref"],
    "OBSERVED_OBJECT_BINDINGS_V1": ["/observed_motion_objects", "/render_receipt_ref"],
    "REFERENCED_JSON_FIELD_EQUALITY_V1": ["/video_sha256", "/ffprobe_receipt_ref"],
    "RENDER_INPUT_ASSET_SET_EQUALITY_V1": ["/render_input_manifest_ref", "/asset_plan_ref"],
    "AUDIO_FILE_PACKET_LINEAGE_V2": ["/audio_stream_present", "/video_ref", "/video_sha256",
                                     "/audio_sha256", "/render_command_receipt_ref"],
}


def media_contract_errors(contract):
    """Independent, bounded contract shape check for media operators."""
    algorithm = contract.get("algorithm")
    expected = MEDIA_OPERANDS.get(algorithm)
    if expected is None:
        return ["MEDIA_ALGORITHM_UNSUPPORTED"]
    errors = []
    if (contract.get("operand_refs") != expected or contract.get("quantifier") != "SINGLE"
            or contract.get("branch_selector") != {"mode": "ANY_JSON_SCHEMA_VALID_BRANCH"}):
        errors.append("MEDIA_OPERAND_BINDING_INVALID")
    if algorithm in {"RENDER_OBJECT_BINDINGS_V1", "OBSERVED_OBJECT_BINDINGS_V1"} and (
        contract.get("operand_types") != ["array", "ref"]
        or contract.get("subject_selector") != expected[0]
    ):
        errors.append("MEDIA_OBJECT_COLLECTION_BINDING_INVALID")
    parameters = contract.get("parameters", {})
    required = {
        "RENDER_OBJECT_BINDINGS_V1": {},
        "OBSERVED_OBJECT_BINDINGS_V1": {},
        "REFERENCED_JSON_FIELD_EQUALITY_V1": {"value_pointer": "/input_sha256"},
        "RENDER_INPUT_ASSET_SET_EQUALITY_V1": {
            "assets_pointer": "/assets", "member_fields": ["asset_ref", "asset_sha256"]},
        "AUDIO_FILE_PACKET_LINEAGE_V2": {
            "transform_pointer": "/audio_transform",
            "source_identity_domain": "WHOLE_AUDIO_FILE_BYTES",
            "output_identity_domain": "SELECTED_AUDIO_PACKET_PAYLOAD_BYTES",
            "packet_canonicalization": "CONCAT_PAYLOAD_BYTES_IN_DEMUX_ORDER_EXCLUDE_CONTAINER_AND_TIMESTAMPS",
            "stream_selection": "FIRST_DEFAULT_AUDIO_ELSE_LOWEST_AUDIO_INDEX",
            "replay": "INDEPENDENT_FROM_SOURCE_WITH_RECORDED_ENCODER_PARAMETERS"},
    }[algorithm]
    if not isinstance(parameters, dict) or any(parameters.get(k) != v for k, v in required.items()):
        errors.append("MEDIA_PARAMETERS_INVALID")
    return errors


def _one(document, pointer):
    values = pointer_values(document, pointer)
    if len(values) != 1:
        raise ValueError("media operand requires one value")
    return values[0]


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("expected an exact lowercase SHA-256 digest")
    return value


def _bytes(resolver, ref):
    if not isinstance(ref, str) or not ref:
        raise ValueError("missing evidence reference")
    data = resolver(ref)
    if not isinstance(data, bytes):
        raise ValueError("resolver must return bytes")
    return data


def _asset_set(document, parameters):
    assets = _one(document, parameters["assets_pointer"])
    if not isinstance(assets, list) or not assets:
        raise ValueError("asset membership must be nonempty")
    pairs = []
    for asset in assets:
        ref, digest = (asset[field] for field in parameters["member_fields"])
        if not isinstance(ref, str) or not ref:
            raise ValueError("asset reference is missing")
        pairs.append((ref, _digest(digest)))
    # Object rows may reuse a materialized asset. A set deduplicates identical
    # identities; only conflicting identities for the same reference are invalid.
    if len({ref for ref, _ in pairs}) != len(set(pairs)):
        raise ValueError("one asset reference has conflicting digests")
    return set(pairs)


def _object_bindings(objects, *, motion=False):
    if not isinstance(objects, list) or not objects:
        raise ValueError("object membership must be nonempty")
    result = {}
    for obj in objects:
        key = obj["object_id"]
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("object IDs must be nonempty and unique")
        fields = {field: obj[field] for field in ("asset_id", "visual_intent_id", "audio_anchor_id")}
        for field in ("sentence_ids", "claim_ids", "motion_segment_ids", "motion_curve_ids"):
            if motion and field.startswith("motion_"):
                segment_key = "segment_id" if field == "motion_segment_ids" else "curve_id"
                values = [segment[segment_key] for segment in obj["motion_segments"]]
            else:
                values = obj[field]
            if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
                raise ValueError("object binding requires nonempty ID arrays")
            fields[field] = frozenset(values)
        result[key] = fields
    return result


def _motion_bindings(document):
    return _object_bindings([obj for shot in document["shots"] for obj in shot["objects"]], motion=True)


def evaluate_media_evidence_contract(contract, document, resolver, *,
                                     packet_reader=None, audio_transform_replay=None):
    """Evaluate content relations; missing extraction/replay is never a PASS."""
    errors = media_contract_errors(contract)
    if errors:
        return {"passed": False, "status": "INCONCLUSIVE", "failure_code": errors[0]}
    try:
        values = [_one(document, ref) for ref in contract["operand_refs"]]
        algorithm, parameters = contract["algorithm"], contract["parameters"]
        if algorithm == "RENDER_OBJECT_BINDINGS_V1":
            bindings, motion_ref = values
            passed = _object_bindings(bindings) == _motion_bindings(json.loads(_bytes(resolver, motion_ref)))
        elif algorithm == "OBSERVED_OBJECT_BINDINGS_V1":
            observed, render_ref = values
            render = json.loads(_bytes(resolver, render_ref))
            motion = json.loads(_bytes(resolver, render["motion_ir_ref"]))
            passed = (_object_bindings(observed) == _object_bindings(render["rendered_semantic_bindings"])
                      == _motion_bindings(motion))
        elif algorithm == "REFERENCED_JSON_FIELD_EQUALITY_V1":
            expected, receipt_ref = values
            receipt = json.loads(_bytes(resolver, receipt_ref))
            passed = _digest(expected) == _digest(_one(receipt, parameters["value_pointer"]))
        elif algorithm == "RENDER_INPUT_ASSET_SET_EQUALITY_V1":
            manifest, plan = (json.loads(_bytes(resolver, ref)) for ref in values)
            passed = _asset_set(manifest, parameters) == _asset_set(plan, parameters)
        else:
            if packet_reader is None or audio_transform_replay is None:
                return {"passed": False, "status": "INCONCLUSIVE",
                        "failure_code": "AUDIO_EXTRACTION_OR_REPLAY_UNAVAILABLE"}
            present, video_ref, video_digest, audio_digest, command_ref = values
            transform = _one(json.loads(_bytes(resolver, command_ref)), parameters["transform_pointer"])
            source = _bytes(resolver, transform["input_audio_ref"])
            video = _bytes(resolver, video_ref)
            mode, encoder = transform["mode"], transform["encoder_parameters"]
            if mode not in {"COPY", "TRANSCODE"} or not isinstance(encoder, dict) or not encoder:
                raise ValueError("audio transform requires explicit mode and encoder parameters")
            source_digest = sha256(source).hexdigest()
            passed = (present is True and source_digest == _digest(audio_digest)
                      and source_digest == _digest(transform["input_audio_sha256"])
                      and video_ref == transform["output_video_ref"]
                      and sha256(video).hexdigest() == _digest(video_digest))
            if passed:
                # The callback protocol selects the stream and concatenates its
                # payload bytes in demux order, excluding container/timestamps.
                actual = packet_reader(video)
                replay = audio_transform_replay(source, mode, encoder)
                if not isinstance(actual, bytes) or not actual or not isinstance(replay, bytes) or not replay:
                    raise ValueError("packet extraction and replay must return nonempty bytes")
                passed = (actual == replay and sha256(actual).hexdigest()
                          == _digest(transform["packet_payload_sha256"]))
        return {"passed": passed, "status": "COMPLETED",
                "failure_code": None if passed else "MEDIA_EVIDENCE_RELATION_FAILED"}
    except (KeyError, ValueError, TypeError, UnicodeError) as exc:
        return {"passed": False, "status": "INCONCLUSIVE",
                "failure_code": "MEDIA_EVIDENCE_INVALID", "detail": str(exc)}
