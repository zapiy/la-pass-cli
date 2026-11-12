# Deterministic Password Vault

A Python terminal application that generates reproducible passwords from one master password and an email address. Only email addresses are stored in an encrypted SQLCipher database next to `vault.py`. Master passwords and generated passwords are never saved to the database.

## Setup and launch

Python 3.10+ is required; Python 3.13 is recommended.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python vault.py
```

Alternatively, activate the environment first:

```sh
source .venv/bin/activate
python vault.py
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\activate` instead.
Use a Unicode terminal of at least 80 columns by 24 rows. On macOS, clipboard access uses `pbcopy` and `pbpaste`. On Linux, install a backend supported by pyperclip, such as xclip or xsel, and run within a graphical session.

## Usage

On first launch, enter and confirm a master password. The application then creates `vault.db` alongside the script. Subsequent launches use the master password to open that file. Failed attempts do not recreate the database. The script directory must be writable.

The master password is masked with asterisks. Select **Show password** and press Enter to toggle visibility. After unlocking, use **+ Add account** to add an email, or select the **Copy** button to the right of an existing email to generate and copy its password.

| Key | Action |
| --- | --- |
| Up / Down | Select the previous / next control or account |
| Left / Right | Move the cursor inside a text field; select controls elsewhere |
| Enter | Submit a field, toggle the checkbox, or press the selected button |
| Esc | Close the add-account screen; lock the account list; exit from the login screen |

Use ordinary characters to enter text and Backspace/Delete to correct it. Tab and action shortcuts are disabled.

The application automatically locks 30 minutes after unlocking, regardless of activity. The timeout is checked once per second. Locking closes the database, wipes the application's mutable generation-key buffer, hides the account list, and shows an empty, masked login field. Esc locks the account list immediately.

Copied passwords are cleared from the clipboard after 30 seconds if its contents have not changed. Locking and normal shutdown also attempt to clear the application's copied value. Clipboard history managers may retain copies; cleanup cannot be guaranteed after a crash or forced termination.

## Reproducibility and backups

The same master password and canonical email produce the same 24-character password on any device running algorithm v1. No random salt, device identifier, or database contents affect generation. The SQLCipher database has its own random encryption salt, which is separate from password generation.

To move the account list, close the application and copy `vault.db`. To reproduce an individual password, only the same algorithm, master password, and email are needed. Keep a backup of the script or algorithm specification.

Changing the master password, the case of the email's local part, or the algorithm changes the generated password. Passwords on websites are not changed automatically. There is no master-password recovery or per-site password generation: the same email uses the same generated password everywhere.

## Algorithm v1 — keep unchanged

1. Encode the exact master-password string as UTF-8, without trimming or Unicode normalization.
2. Derive `root = scrypt(master, salt=b'', n=131072, r=8, p=1, dklen=32, maxmem=268435456)`.
3. Derive the generation key with HMAC-SHA256(root, `b'vault:v1:generation'`) and the database key with HMAC-SHA256(root, `b'vault:v1:database'`). Wipe the temporary mutable root buffer.
4. Canonicalize the email by trimming surrounding whitespace and lowercasing its domain; preserve the local part's case. Common ASCII addresses are supported; quoted local parts and internationalized addresses are not.
5. Generate blocks using HMAC-SHA256(generation key, `b'vault:v1:password\0' + email_utf8 + b'\0' + counter_uint64_big_endian`), starting the counter at zero.
6. Use the alphabet `ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()-_=+`. Reject bytes greater than or equal to `256 - 256 % len(alphabet)`; map the remaining bytes to symbols using modulo. Collect a 24-character candidate and discard the rest of its final block. If the candidate lacks uppercase letters, lowercase letters, digits, or symbols, generate the next candidate with the continuing counter.
7. Pass the database key to SQLCipher as a hex-text passphrase. SQLCipher applies its own random salt and key derivation, independently of generated passwords.

Test vector — do not use this master password for real accounts:

```text
Master:   test master phrase
Email:    Alice@example.com
Password: WZUf-1GTVFDrUsDPGbcT1Oc)
```

## Memory and security limits

The original master password is removed from application state after unlocking. The session retains a derived generation key and an open SQLCipher connection. The Python database-key buffer is wiped after opening; SQLCipher retains the key material it needs to operate. A stolen generation key can generate all account passwords without the original master password.

Python, OpenSSL, the terminal, and clipboard tools may retain temporary copies; physical erasure cannot be guaranteed. Generated passwords briefly exist in memory when copied. Unsalted generation allows attackers to reuse master-password guessing work across users with identical master passwords. Use a long, unique master passphrase.

This application has not undergone an independent security audit.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

Tests use temporary encrypted databases and synthetic credentials. Keyboard flows run through Textual's headless test pilot. Clipboard ownership and cleanup are tested with an in-memory backend without overwriting the user's system clipboard.

At startup, the CLI requests at least 80 columns and 24 rows, preserving dimensions already above the minimum. Terminals that ignore window resize requests retain their current size; the interface remains responsive. Redirected output sends no resize sequence.

## Project layout

```text
vault.py          Launcher (python vault.py)
vault/crypto.py   Password derivation, generation, and email validation
vault/storage.py  Encrypted SQLCipher storage and session
vault/screens/login.py    Login screen and secret input
vault/screens/accounts.py Account list and add account screen
vault/screens/common.py   Shared input and keyboard navigation
vault/app.py      Application lifecycle, locking, and clipboard
vault/styles.tcss Responsive terminal layout and styles
vault/__main__.py Module launcher (python -m vault)
requirements.txt Pinned application dependencies
README.md         Setup, controls, algorithm, and security limits
tests/            Vault tests
docs/             Vault design and implementation records
.venv/            Application virtual environment
_archive/         Unrelated scripts, documentation, tests, and previous environment
```

Archived files are preserved as they were and are excluded from active test discovery. The previous unrelated environment is in `_archive/.venv`; it is an archival copy, not the active environment.
