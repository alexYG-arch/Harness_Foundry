# Security reporting and support

The canonical repository is `alexYG-arch/Harness_Foundry`. The v0.2.0 portable
distribution is the supported release candidate; historical Candidate/epoch
workflows are retired, not a second supported production route.

For a suspected vulnerability, use the repository's **Security → Report a
vulnerability** private channel once available. Do not post exploit details,
credentials, private requirements, controller databases or raw session logs in a
public issue. Ordinary non-sensitive defects belong in Issues with a minimal,
sanitized reproduction and version information.

If the private-report button is unavailable, do not submit sensitive details
publicly. A neutral issue may request that maintainers enable the private channel;
wait for that channel before sending the report. No response-time SLA or unverified
contact address is promised.

Publication checklist: enable and verify private vulnerability reporting before
publishing v0.2.0. As checked on 2026-09-21 during local release preparation, it was
not yet enabled; this policy file does not change repository settings.

Native execution requires the displayed, user-approved model/tool/path/budget scope
and a working native sandbox. Never bypass isolation or replay unknown side effects.
The current macOS receiver cannot enforce the required read-only boundary in shared
`/tmp`; Foundry rejects that layout. Use the documented supported directory layout.
This limitation is not fixed by changing a permission label or disabling the sandbox.

Use a new product version for a published defect fix. Do not overwrite release
assets, move an existing tag, silently migrate old control databases or imply that
code rollback reverses external effects.
