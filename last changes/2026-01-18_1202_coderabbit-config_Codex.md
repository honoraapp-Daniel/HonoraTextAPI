# Change
- Change title: Add CodeRabbit configuration for strict AI reviews
- Intent: Enable automatic, high-signal CodeRabbit reviews on every PR with assertive tone and focused priorities.
- Method: Added `coderabbit.yml` with assertive profile, auto-review settings, high-level summary + review status, and path filters to ignore generated and dependency artifacts.
- Reason: Provide production-ready CodeRabbit defaults aligned with review quality and noise constraints.
- Files touched: coderabbit.yml
- Tests: Not run (configuration-only change).
- Agent signature: Codex
