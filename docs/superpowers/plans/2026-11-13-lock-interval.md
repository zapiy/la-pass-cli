# Auto-lock interval

Approved behavior: focusable countdown opens a small overlay with 30 min / 1h / 3h.
The saved choice has a dot; focus highlights the candidate. Enter saves and restarts
the countdown; Escape cancels. Default is 30 minutes; persist inside the encrypted database.

Implementation: VaultSession creates settings(lock_seconds INTEGER) without field
constraints, loads the interval after unlocking, and saves changes in a transaction.
Python validates supported intervals. VaultApp uses the session interval for timeout
checks. AccountsScreen uses a Button countdown and an ArrowScreen modal.
No new dependencies or JSON settings. Failed database writes preserve the old interval.

- [x] Add tests for settings validation, selection, cancel, save failure,
  countdown updates, responsive placement, persistence, and selected timeout.
- [x] Implement settings and modal; preserve existing keyboard controls.
- [x] Run the complete unittest suite and inspect the final diff: 19 tests passed.
