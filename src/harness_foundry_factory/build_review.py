"""Human-reviewed build input shared by generic and compatibility authoring.

The trusted chat host authenticates presentation and the later human message;
JSON labels cannot authenticate people or prove semantic coverage. Store the
complete reviewed text in the existing proposal/event, not another ledger.
No hashes, tokens, model calls or target writes are needed for this boundary.
"""

from pathlib import Path

from .models import RequestValidationError


def _require(condition, message):
    if not condition:
        raise RequestValidationError(message, details={"reason_code": "BUILD_DOCUMENT_REVIEW_REQUIRED"})


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_build_review(review, *, check_files=True):
    """Validate a host-recorded decision and, by default, the current document."""
    _require(isinstance(review, dict) and set(review) == {
        "document_id", "version", "documents", "presentation", "decision"},
        "a displayed build document and actual human confirmation are required")
    _require(_text(review["document_id"]) and _text(review["version"]), "review requires document identity/version")
    presentation, decision = review["presentation"], review["decision"]
    _require(isinstance(presentation, dict) and set(presentation) == {"chat_thread_id", "turn_id"}
             and all(_text(value) for value in presentation.values()), "bind the actual document presentation turn")
    _require(isinstance(decision, dict) and set(decision) == {"action", "actor", "user_message"},
             "review requires the original human decision")
    actor = decision["actor"]
    _require(decision["action"] == "CONFIRM_BUILD_DOCUMENT" and _text(decision["user_message"])
             and isinstance(actor, dict) and set(actor) == {"type", "chat_thread_id", "turn_id"}
             and actor["type"] == "HUMAN_VIA_CODEX_CHAT"
             and all(_text(actor[key]) for key in ("chat_thread_id", "turn_id"))
             and actor["chat_thread_id"] == presentation["chat_thread_id"]
             and actor["turn_id"] != presentation["turn_id"],
             "the trusted host must record a later human document confirmation, not an agent decision or runtime grant")
    documents = review["documents"]
    _require(isinstance(documents, list) and bool(documents), "review must bind complete displayed documents")
    ids, paths = set(), set()
    for document in documents:
        _require(isinstance(document, dict) and set(document) == {"source_id", "path", "text"}
                 and all(_text(document[key]) for key in document), "invalid reviewed document binding")
        path = Path(document["path"])
        _require(path.is_absolute() and ".." not in path.parts, "reviewed document path must be absolute")
        _require(document["source_id"] not in ids and str(path) not in paths, "duplicate reviewed document")
        ids.add(document["source_id"])
        paths.add(str(path))
        if check_files:
            try:
                _require(path.is_file(), "reviewed document is unavailable")
                current = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise RequestValidationError("reviewed document cannot be read", details={
                    "reason_code": "BUILD_DOCUMENT_REVIEW_REQUIRED"}) from exc
            _require(current == document["text"], "reviewed document changed; show the new content for human review")
    return review


def validate_review_reuse(review, previous):
    """A repeated human message cannot approve a substituted body or version."""
    if previous and review["decision"]["actor"] == previous["decision"]["actor"]:
        _require(review == previous, "the same human confirmation cannot be rebound to another document/version")


def validate_review_sources(review, requirement_ir, *, source_root=None, snapshot=None):
    sources = {source["source_id"]: source for source in requirement_ir["sources"]}
    for document in review["documents"]:
        source_id = document["source_id"]
        _require(source_id in sources, "reviewed build documents must remain declared requirement sources")
        if snapshot is not None:
            loaded = next((row for row in snapshot["sources"] if row["source_id"] == source_id), None)
            _require(loaded is not None and loaded["text"] == document["text"]
                     and (Path(source_root) / loaded["path_or_uri"]).resolve() == Path(document["path"]).resolve(),
                     "captured build input differs from the human-reviewed document")


def review_summary(review):
    if review is None:
        return {"status": "BUILD_DOCUMENT_REVIEW_REQUIRED", "runtime_authorized": False}
    return {"status": "HUMAN_DOCUMENT_CONFIRMATION_RECORDED", "document_id": review["document_id"],
            "version": review["version"], "documents": [{key: value for key, value in row.items() if key != "text"}
                                                        for row in review["documents"]],
            "presentation": review["presentation"], "decision": review["decision"],
            "current_files_checked": False, "runtime_authorized": False}
