# Roadmap: <target-name>

| Phase | Objective | Entry lock/checkpoint | Local Gate | Output lock | Explicitly not proven |
|---|---|---|---|---|---|
| G0/C0 | Control foundation and Conformance Interface | Charter Lock | G0/C0 | G0 Control Lock | Business runtime |
| P1/C1 | Architecture, StageSpec and Runtime contracts | G0 Control Lock | P1/C1 | P1 Build Lock | Representative business slice |
| P2/C2 | Minimum representative vertical slice | P1 Build Lock | P2/C2 | P2 Build Lock | General runner/release |
| P3/C3 | Expansion or approved N/A decision | P2 Build Lock | P3/C3 | P3 Build/N/A Lock | Installed release |
| P4 | Integration and build input closure | P3 Lock + C3 PASS | P4 Local Gate | P4 Build Input Lock | Certificate/real install |
| C4 | Installed external certification | Candidate + D PASS | External Lab C4 | Certificate/Certified Lock | Real target applied |

The machine-readable `PHASE_DEPENDENCY_MANIFEST.json` is authoritative if this roadmap conflicts.
