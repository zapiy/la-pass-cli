# Deterministic password vault

Approved in conversation: one master password; deterministic 24-character passwords per email; no generation salt; derived keys retained instead of master password. Python terminal UI, arrow/Enter/Esc navigation, email-only encrypted SQLite beside script. Mask input with asterisks, visibility checkbox symmetric around screen middle, ASCII lock at top right. First-run confirmation. Separate copy button for every account. Lock 1800 seconds after unlock regardless of activity. Clear own clipboard after 30 seconds if unchanged. Esc closes dialog, locks list, exits login.

Approach: Textual + SQLCipher, rather than GUI toolkit (terminal requested) or encrypted columns (whole database required). scrypt(empty salt, N=131072,r=8,p=1,dklen=32), domain-separated HMAC keys. SQLCipher uses passphrase bytes encoded as hex text, with its own random internal salt and KDF. Generation never depends on database salt. Fixed UTF-8 master bytes, trim email edges and lowercase ASCII domain; preserve local part. Fixed rejection-sampling encoder guarantees upper/lower/digit/symbol without modulo bias. Algorithm v1 never silently changes.

Limits: Python cannot promise erasure; derived generation key grants generation capability. Clipboard needs OS backend. No site-specific passwords, reset/recovery, synchronization or automatic password rotation.
