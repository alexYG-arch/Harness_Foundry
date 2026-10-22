# Foundry generic build workspace

Use the repo-local `harness-foundry-build` Skill for Harness construction.
The Agent reasons, designs and implements; Foundry binds inputs, scope, dependencies,
independent checks and durable progress. Local Python stages are allowed when declared.

Read and follow [the clear communication policy](docs/CLEAR_COMMUNICATION.md) for
human-facing dialogue and documents. Explain results, limits and next actions in
the user's language; preserve exact machine protocols and evidence. This adds no
approval gate. `read-build --human` summarizes state; `--json` retains full facts.

Every build starts with clarification and a saved, displayed, versioned build document.
Wait for the user's actual confirmation of that document and scope before creating a
Program or target. Background validation and the source documents themselves are not
approval. When the full contract and runtime scope are ready, `preview-build` can save nonexecuting host preparation; after one real message explicitly confirms both, `materialize-build-preview` records the reviewed proposal, sources, prepared scope and approval. Otherwise use the original document-review then runtime-approval route.
Within it, proceed through implementation, checking, repair and resume without per-task
approvals. Changed requirements, expanded authority, exhausted budget, expiry and
unresolved side effects stop affected work.

The CLI is `python3 tools/hffactory.py`. Read `docs/GENERIC_BUILD_PLAN.md` and
`docs/GENERIC_BUILD_CLI.md` for the public fields. Use one revision control database
outside target write roots. Never edit that database, invent a human message or turn,
alter accepted history, or treat a model's completion message as acceptance.

This distribution contains only the generic build route. It does not execute historical
Candidate/epoch or fixed-project workflows, and it needs no sibling specification.
Do not fetch the author's checkout or private files to fill a runtime dependency.
Its manifest records contents and declared capability, not acceptance or execution authority.

For evidenced same-scope checker corrections or technical false blocks, use the trusted-host correction entries in the CLI guide; retain the original human approval, old reports and consumed budget. Host review is not a fabricated human message. Only explicitly marked new checker-only rounds avoid a new production charge; old charges remain. Source revocation/expiry stops dependent new dispatch, not historical report reads.
