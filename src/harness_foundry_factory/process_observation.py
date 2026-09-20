"""Host-owned command attachments, not another authorization/acceptance store.

The controller binds the directory before dispatch. Only complete durable
captures can supply a missing observation; partial bytes never authorize replay.
"""

import json
import os
from pathlib import Path


class CommandObservation:
    def __init__(self, root, command_id, executor, on_started=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.streams = {}
        self.on_started = on_started
        self._save("binding.json", {"command_id": command_id, "executor": executor})

    def _save(self, name, value):
        pending = self.root / (name + ".pending")
        with pending.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, self.root / name)
        directory = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def started(self, pid):
        self._save("started.json", {"pid": pid})
        if self.on_started:
            self.on_started(pid)

    def write(self, name, chunk):
        if name not in self.streams:
            self.streams[name] = (self.root / (name + ".bin")).open("xb")
        self.streams[name].write(chunk)

    def captured(self, result):
        for stream in self.streams.values():
            stream.flush()
            os.fsync(stream.fileno())
        self._save("capture.json", result)

    def finished(self, result):
        self._save("result.json", result)

    def close(self):
        for stream in self.streams.values():
            stream.close()

    @staticmethod
    def inspect(root):
        """Read-only diagnostic, never permission to replay or kill a PID.

        PID presence alone cannot prove identity after a host restart. Absence
        likewise cannot prove what the original command did before it exited.
        """
        root = Path(root)
        if (root / "capture.json").exists() or (root / "result.json").exists():
            return {"observation_state": "DURABLE_RESULT_AVAILABLE", "next_action": "RECONCILE_OBSERVATION"}
        if not (root / "started.json").exists():
            return {"observation_state": "START_NOT_OBSERVED", "next_action": "RECONCILE_DISPATCH_WINDOW"}
        try:
            pid = json.loads((root / "started.json").read_text())["pid"]
            if type(pid) is not int or pid <= 0:
                raise ValueError("invalid observed PID")
            os.kill(pid, 0)
            probe = "PID_PRESENT_IDENTITY_UNCONFIRMED"
        except ProcessLookupError:
            probe = "PID_ABSENT_EFFECTS_UNKNOWN"
        except (OSError, ValueError, KeyError, TypeError):
            probe = "PROCESS_PROBE_UNAVAILABLE"
        return {"observation_state": "COMPLETION_NOT_OBSERVED", "process_probe": probe,
                "next_action": "OBSERVE_OR_RECONCILE_PROCESS", "replay_allowed": False}

    @staticmethod
    def recover(root, command_id, executor):
        root = Path(root)
        if not (root / "binding.json").exists():
            return None
        binding = json.loads((root / "binding.json").read_text())
        if binding != {"command_id": command_id, "executor": executor}:
            raise ValueError("command observation binding differs from the dispatch")
        if (root / "result.json").exists():
            return json.loads((root / "result.json").read_text())
        if not (root / "capture.json").exists():
            return None  # May be running or effects may be unknown. Never rerun.
        capture = json.loads((root / "capture.json").read_text())
        if executor == "CODEX":
            from .coding_process import classify_coding_capture
            from .coding_protocol import CodingEventObserver
            observer = CodingEventObserver()
            count = 0
            if (root / "stdout.bin").exists():
                with (root / "stdout.bin").open("rb") as stream:
                    while chunk := stream.read(65536):
                        count += len(chunk)
                        if count > 128 * 1024 * 1024:
                            raise ValueError("command observation exceeds stream limit")
                        observer.feed(chunk)
            if count != capture.get("stream_bytes", {}).get("stdout", 0):
                raise ValueError("command stdout attachment is incomplete")
            return classify_coding_capture(capture, observer)
        from .local_process import classify_local_capture
        return classify_local_capture(capture)
