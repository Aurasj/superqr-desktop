# superqr-desktop Agent Guide

## General Guardrails
- Stay strictly within task scope.
- Inspect git status before making edits.
- Do not commit, push, or create branches unless explicitly requested by the user.
- Avoid unrelated refactoring.
- Do not change dependencies, licenses, or protocol semantics without explicit request.
- Use focused verification.
- Report any verification not performed by the agent.

## Repository Architecture & Guidelines
- This is the standalone desktop SuperQR application.
- Python package root is `src/superqr_desktop`.
- Shared protocol semantics must come from `superqr-protocol`.
- The vendored `visual_contract.json` is a synchronized snapshot, not an independent source of truth. Do not silently modify the contract to make desktop behavior convenient.
- Keep V6 rendering code modular.
- Do not resurrect V4/V5 code.

## Verification & Testing
- Prefer targeted tests; full pytest is acceptable because the suite is currently small.
- Do not build or package installers unless explicitly requested.

## Multi-Repository Coordination

When this repository is opened as part of the SuperQR multi-repository workspace:

- An agent assigned to this repository has write ownership only here by default.
- It may inspect the other SuperQR repositories read-only for context.
- It must not modify another SuperQR repository unless the current user task explicitly grants cross-repository write scope.
- Different agents may work concurrently when each agent writes to a different repository.
- Multiple agents must not write to the same repository concurrently unless the user explicitly provides isolated Git worktrees/branches.
- Shared protocol changes must be finalized in `superqr-protocol` before client adaptation begins.