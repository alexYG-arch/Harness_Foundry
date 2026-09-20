"""Synthetic review input for temporary test Programs, never a real approval."""

from pathlib import Path


def reviewed_document(root, *, path=None, source_id="PROJECT-BRIEF"):
    path = Path(path) if path is not None else Path(root) / "TEST_BUILD_DOCUMENT.md"
    if not path.exists():
        path.write_text("TEST ONLY build document. Preserve the declared scope and independent checks.\n", encoding="utf-8")
    return {
        "document_id": "TEST-BUILD-DOCUMENT", "version": "test-v1",
        "documents": [{"source_id": source_id, "path": str(path.resolve()), "text": path.read_bytes().decode("utf-8")}],
        "presentation": {"chat_thread_id": "TEST-REVIEW-THREAD", "turn_id": "TEST-PRESENTATION"},
        "decision": {"action": "CONFIRM_BUILD_DOCUMENT", "actor": {
            "type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "TEST-REVIEW-THREAD", "turn_id": "TEST-CONFIRMATION"},
            "user_message": "TEST FIXTURE ONLY: confirm displayed test build document; no real user permission"},
    }
