# Clear vault implementation plan

**Goal:** Implement the approved login-screen deletion proposal.
**Design:** ASCII trash button immediately right of Unlock, #E53935, no text. Confirmation defaults to Cancel; Escape cancels. Confirm deletes the local database and SQLite sidecars, clears login secrets, and returns to first-run state. Missing storage disables the button; errors remain visible.
**Architecture:** Reuse ArrowScreen for confirmation and existing Textual styling. No new dependencies.

## Task 1
- [x] Add UI tests for cancel, Escape, confirmed deletion, failure, and first-run state; run them before implementation.
- [x] Update login.py and styles.tcss with the button, confirmation, and deletion handling.
- [x] Run the complete unittest suite and inspect the diff.

**Validation:** `.venv/bin/python -m unittest discover -s tests` — 11 tests passed. Initial new tests failed because the deletion button did not exist. Tests use temporary databases only.

**Review focus:** Preserve Unlock dispatch; do not touch the real vault during tests; retain error feedback; support narrow terminal layouts.
