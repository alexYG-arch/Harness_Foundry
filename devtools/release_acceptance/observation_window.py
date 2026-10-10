"""Example bounded event observation for project adapters, never acceptance.

Subscribe before the action so a short-lived state is not missed. The adapter
owns readiness/subscription semantics; this does not change a product lease.
"""
from threading import Event, Lock
from time import monotonic


def observe_window(*, ready, subscribe, trigger, matches, timeout_seconds):
    if not 0 < timeout_seconds <= 60:
        raise ValueError("declare an observation window in (0, 60] seconds")
    if not ready():
        return {"status": "NOT_READY", "triggered": False, "accepted": False}
    done, lock, observations = Event(), Lock(), []

    def on_event(value):
        with lock:
            observations.append(value)
            if matches(value):
                done.set()

    start = monotonic()
    unsubscribe = subscribe(on_event)
    try:
        # The trigger must be a bounded/nonblocking adapter operation.
        trigger()
        observed = done.wait(max(0, timeout_seconds - (monotonic() - start)))
    finally:
        unsubscribe()
    return {"status": "OBSERVED" if observed else "OBSERVATION_INCOMPLETE", "triggered": True,
            "events": observations, "elapsed_seconds": monotonic() - start, "accepted": False}
