# Deterministic password vault

Approved in conversation: one master password; deterministic 24-character passwords per email; no generation salt; derived keys retained instead of master password. Python terminal UI, arrow/Enter/Esc navigation, email-only encrypted SQLite beside script. Mask input with asterisks, visibility checkbox symmetric around screen middle, ASCII lock at top right. First-run confirmation. Separate copy button for every account. Lock 1800 seconds after unlock regardless of activity. Clear own clipboard after 30 seconds if unchanged. Esc closes dialog, locks list, exits login.

Approach: Textual + SQLCipher, rather than GUI toolkit (terminal requested) or encrypted columns (whole database required). scrypt(empty salt, N=131072,r=8,p=1,dklen=32), domain-separated HMAC keys. SQLCipher uses passphrase bytes encoded as hex text, with its own random internal salt and KDF. Generation never depends on database salt. Fixed UTF-8 master bytes, trim email edges and lowercase ASCII domain; preserve local part. Fixed rejection-sampling encoder guarantees upper/lower/digit/symbol without modulo bias. Algorithm v1 never silently changes.

Limits: Python cannot promise erasure; derived generation key grants generation capability. Clipboard needs OS backend. No site-specific passwords, reset/recovery, synchronization or automatic password rotation.


## Update — 2026-11-14: optional PIN

The login header now has shuffled digit buttons on the left and the logo on the right. A display accepts up to four digits through buttons only, preserves leading zeros, stays compact when empty, and marks 1–3 digits red. The `<` button removes the last digit. Incomplete PINs block Unlock and Once, including submission from the master-password field.

An empty PIN preserves the original v1 derivation exactly. For a complete PIN, the scrypt input is `len(master_utf8).to_bytes(4, 'big') + master_utf8 + pin_ascii`. The prefix encodes the byte length and adds no salt. Existing scrypt parameters and HMAC labels remain unchanged. Both the database and generation keys depend on the PIN; Once uses the same generation key as the vault for identical credentials.

First-run confirmation compares keys derived from the entire master-password/PIN pair. Both inputs are cleared for confirmation, after unlock attempts, when entering Once, and when deleting vault data. PINs are not stored in the database. Existing vaults are not migrated: a vault created without a PIN requires an empty PIN. Changing credentials or recovering a forgotten PIN is not implemented; changing the PIN also changes generated passwords.
