from __future__ import annotations

import hashlib
import hmac
import re
import string

UPPER = string.ascii_uppercase
LOWER = string.ascii_lowercase
DIGITS = string.digits
SYMBOLS = '!@#$%^&*()-_=+'
ALPHABET = UPPER + LOWER + DIGITS + SYMBOLS
def wipe(value: bytearray | None) -> None:
    if value is not None:
        value[:] = b'\0' * len(value)


def canonical_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", value):
        raise ValueError('Enter an email, e.g. alice@example.com')
    local, domain = value.rsplit('@', 1)
    if (len(local) > 64 or local.startswith('.') or local.endswith('.') or '..' in local
            or '.' not in domain or any(not label or len(label) > 63 or label.startswith('-')
                                      or label.endswith('-') for label in domain.split('.'))):
        raise ValueError('Invalid email address')
    return local + '@' + domain.lower()


def _derive_root(master: str) -> bytearray:
    if len(master) < 3:
        raise ValueError('Master password must contain at least 3 characters')
    return bytearray(hashlib.scrypt(master.encode('utf-8'), salt=b'', n=2**17,
                                    r=8, p=1, dklen=32, maxmem=256 * 1024**2))


def derive_generation_key(master: str) -> bytearray:
    root = _derive_root(master)
    try:
        return bytearray(hmac.digest(root, b'vault:v1:generation', 'sha256'))
    finally:
        wipe(root)


def derive_keys(master: str) -> tuple[bytearray, bytearray]:
    root = _derive_root(master)
    try:
        return (bytearray(hmac.digest(root, b'vault:v1:generation', 'sha256')),
                bytearray(hmac.digest(root, b'vault:v1:database', 'sha256')))
    finally:
        wipe(root)


def generate_password(key: bytearray, email: str) -> str:
    email_bytes = canonical_email(email).encode('utf-8')
    # Rejection sampling avoids modulo bias; reject whole candidates lacking a class.
    counter = 0
    while True:
        chars = []
        while len(chars) < 24:
            block = hmac.digest(key, b'vault:v1:password\0' + email_bytes
                                + b'\0' + counter.to_bytes(8, 'big'), 'sha256')
            counter += 1
            for value in block:
                if value < 256 - 256 % len(ALPHABET):
                    chars.append(ALPHABET[value % len(ALPHABET)])
                    if len(chars) == 24:
                        break
        password = ''.join(chars)
        if all(any(c in group for c in password) for group in (UPPER, LOWER, DIGITS, SYMBOLS)):
            return password


