"""Authorized acceptance-host probe, not an alternative runtime or approval.

The caller must supply the existing approved controller and its native runner.
This source-owned probe replaces the historical ad-hoc script; old runs stay intact.
"""
import json
import os


def after_observation_runner(native, workpack_id, *, terminate=os._exit):
    def run(invocation, before_dispatch):
        result = native(invocation, before_dispatch)  # Native stores its completion first.
        if (invocation["phase"] == "IMPLEMENTATION" and invocation["workpack_id"] == workpack_id
                and invocation["executor"] == "CODEX" and result.get("status") == "MODEL_TURN_COMPLETED"
                and result.get("exit_code") == 0):
            print(json.dumps({"status": "PLANNED_HOST_STOP_AFTER_NATIVE_OBSERVATION",
                              "workpack_id": workpack_id}), flush=True)
            terminate(86)
            raise RuntimeError("host termination unexpectedly returned; refusing successor dispatch")
        return result
    return run


def advance_with_probe(controller, prepared_event_id, workpack_id, *, terminate=os._exit):
    controller.runner = after_observation_runner(controller.runner, workpack_id, terminate=terminate)
    result = controller.advance(prepared_event_id)
    print(json.dumps(result))
    # Ordinary completion cannot prove this probe's interruption window.
    return 6
