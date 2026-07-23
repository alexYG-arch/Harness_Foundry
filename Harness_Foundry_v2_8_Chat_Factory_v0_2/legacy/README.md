# Legacy migration inputs

This directory preserves v0.1 execution-evidence behavior for read-only
migration analysis. Generic static checks may be reused by the v0.2 validator,
but target-specific runtime-state recognizers are never invoked for a v0.2
candidate PASS and cannot grant authorization, validate a live runtime, or
alter a legacy Program.

The exported patch is Hash-bound by `PATCH_MANIFEST.json`. Its target-specific
states and receipts are fixtures for the separate Controlled Execution Runtime,
not accepted branches in the v0.2 static candidate validator.
