"""Deterministic password vault; algorithm v1 is documented in README.md."""

try:
    import pyperclip
    from .crypto import (ALPHABET, DIGITS, LOWER, SYMBOLS, UPPER, canonical_email,
                         derive_generation_key, derive_keys, generate_password, wipe)
    from .storage import VaultError, VaultSession
    from .screens import AccountsScreen, AddAccountModal, LoginScreen
    from .app import DEFAULT_DB, LOCK_SECONDS, VaultApp
except ImportError as error:
    raise SystemExit("Install dependencies: python -m pip install -r requirements.txt") from error
