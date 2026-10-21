"""Host-owned command attachments, not another authorization/acceptance store.

The controller binds the directory before dispatch. Only complete durable
captures can supply a missing observation; partial bytes never authorize replay.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class CommandObservation:
    def __init__(self, root, command_id, executor, on_started=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.streams = {}
        self.on_started = on_started
        self.binding = {"command_id": command_id, "executor": executor}
        self._save("binding.json", self.binding)

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

    def model_configuration(self, configuration):
        """Persist the non-secret dispatch selection before a client can start."""
        if self.binding["executor"] != "CODEX" or not isinstance(configuration, dict):
            raise ValueError("model configuration requires a CODEX command")
        receipt = {"binding": self.binding, "configuration": configuration}
        path = self.root / "model-configuration.json"
        if path.exists():
            if json.loads(path.read_text()) != receipt:
                raise ValueError("command model configuration is already bound")
            return
        self._save("model-configuration.json", receipt)

    @staticmethod
    def _checked_configuration(root, binding, result):
        path = root / "model-configuration.json"
        present = "model_configuration" in result
        capture = result.get("capture")
        nested = isinstance(capture, dict) and "model_configuration" in capture
        if not path.exists():
            if present or nested:
                raise ValueError("model configuration has no bound receipt")
            return result  # Legacy commands remain recoverable without invented configuration.
        receipt = json.loads(path.read_text())
        if (binding["executor"] != "CODEX" or not isinstance(receipt, dict)
                or receipt.get("binding") != binding or not isinstance(receipt.get("configuration"), dict)):
            raise ValueError("model configuration receipt binding differs from the dispatch")
        configuration = receipt["configuration"]
        if not present or result["model_configuration"] != configuration:
            raise ValueError("command model configuration differs from its receipt")
        if isinstance(capture, dict) and (not nested or capture["model_configuration"] != configuration):
            raise ValueError("captured model configuration differs from its receipt")
        return result

    def started(self, pid):
        self._save("started.json", {"pid": pid, "started_at": datetime.now(timezone.utc).isoformat()})
        if self.on_started:
            self.on_started(pid)

    def write(self, name, chunk):
        if name not in self.streams:
            self.streams[name] = (self.root / (name + ".bin")).open("xb")
        self.streams[name].write(chunk)
        self.streams[name].flush()  # Visible progress, not durable completion/acceptance.

    def captured(self, result):
        self._checked_configuration(self.root, self.binding, result)
        for stream in self.streams.values():
            stream.flush()
            os.fsync(stream.fileno())
        self._save("capture.json", result)

    def finished(self, result):
        self._checked_configuration(self.root, self.binding, result)
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
        progress = {"stream_bytes": {}, "latest_output_at": None, "elapsed_seconds": None,
                    "progress_is_diagnostic_only": True, "acceptance_verified": False}
        outputs = [root / (name + ".bin") for name in ("stdout", "stderr")]
        for output in outputs:
            if output.exists():
                stat = output.stat()
                progress["stream_bytes"][output.stem] = stat.st_size
                timestamp = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                progress["latest_output_at"] = max(progress["latest_output_at"] or timestamp, timestamp)
        started_file = root / "started.json"
        if started_file.exists():
            try:
                started_at = json.loads(started_file.read_text()).get("started_at")
                if started_at:
                    completed = next((root / name for name in ("capture.json", "result.json")
                                      if (root / name).exists()), None)
                    end = datetime.fromtimestamp(completed.stat().st_mtime, timezone.utc) if completed else datetime.now(timezone.utc)
                    progress["elapsed_seconds"] = max(0, (end - datetime.fromisoformat(started_at)).total_seconds())
            except (OSError, ValueError, TypeError):
                pass
        if (root / "capture.json").exists() or (root / "result.json").exists():
            return {**progress, "observation_state": "DURABLE_RESULT_AVAILABLE", "next_action": "RECONCILE_OBSERVATION"}
        if not (root / "started.json").exists():
            return {**progress, "observation_state": "START_NOT_OBSERVED", "next_action": "RECONCILE_DISPATCH_WINDOW"}
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
        return {**progress, "observation_state": "COMPLETION_NOT_OBSERVED", "process_probe": probe,
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
            return CommandObservation._checked_configuration(root, binding, json.loads((root / "result.json").read_text()))
        if not (root / "capture.json").exists():
            return None  # May be running or effects may be unknown. Never rerun.
        capture = CommandObservation._checked_configuration(root, binding, json.loads((root / "capture.json").read_text()))
        if executor == "CODEX":
            from .coding_process import classify_coding_capture
            from .coding_events import CodingEventObserver
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
