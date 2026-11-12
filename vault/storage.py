from __future__ import annotations

from pathlib import Path
from sqlcipher3 import dbapi2 as sqlcipher

from .crypto import canonical_email, derive_keys, generate_password, wipe

LOCK_SECONDS = 1800


class VaultError(Exception):
    pass


class VaultSession:
    def __init__(self, connection, generation_key: bytearray):
        self.connection = connection
        self.generation_key = generation_key
        row = connection.execute('SELECT lock_seconds FROM settings LIMIT 1').fetchone()
        value = row[0] if row else None
        self.lock_seconds = value if type(value) is int and value in (1800, 3600, 10800) else LOCK_SECONDS

    @classmethod
    def open(cls, path: Path, master: str) -> VaultSession:
        generation, database = derive_keys(master)
        return cls.from_keys(path, generation, database)

    @classmethod
    def from_keys(cls, path: Path, generation: bytearray, database: bytearray) -> VaultSession:
        connection = None
        try:
            connection = sqlcipher.connect(str(path))
            if not connection.execute('PRAGMA cipher_version').fetchone():
                raise VaultError('SQLCipher is unavailable: unencrypted databases are not allowed')
            # Hex is used as a passphrase, NOT raw x-key: SQLCipher retains its random salt/KDF.
            connection.execute("PRAGMA key = '" + database.hex() + "'")
            connection.execute('PRAGMA cipher_memory_security = ON')
            connection.execute('PRAGMA temp_store = MEMORY')
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise VaultError('Unsupported database version')
            connection.execute('CREATE TABLE IF NOT EXISTS accounts (email TEXT PRIMARY KEY NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS settings (lock_seconds INTEGER)')
            connection.execute('PRAGMA user_version = 1')
            connection.commit()
            path.chmod(0o600)
            return cls(connection, generation)
        except (sqlcipher.Error, OSError) as error:
            if connection:
                connection.close()
            wipe(generation)
            raise VaultError('Cannot open database: incorrect master password, corruption, or access error') from error
        except Exception:
            if connection:
                connection.close()
            wipe(generation)
            raise
        finally:
            wipe(database)

    def set_lock_interval(self, seconds: int) -> None:
        if self.connection is None:
            raise RuntimeError('Vault is locked')
        if type(seconds) is not int or seconds not in (1800, 3600, 10800):
            raise ValueError('Invalid lock interval')
        with self.connection:
            self.connection.execute(
                'INSERT INTO settings (rowid, lock_seconds) VALUES (1, ?) '
                'ON CONFLICT(rowid) DO UPDATE SET lock_seconds = excluded.lock_seconds',
                (seconds,))
        self.lock_seconds = seconds

    def emails(self) -> list[str]:
        if self.connection is None:
            raise RuntimeError('Vault is locked')
        return [row[0] for row in self.connection.execute('SELECT email FROM accounts ORDER BY email')]

    def add(self, email: str) -> str:
        email = canonical_email(email)
        if self.connection is None:
            raise RuntimeError('Vault is locked')
        try:
            with self.connection:
                self.connection.execute('INSERT INTO accounts(email) VALUES (?)', (email,))
        except sqlcipher.IntegrityError:
            raise ValueError('This email has already been added') from None
        return email

    def delete(self, email: str) -> None:
        if self.connection is None:
            raise RuntimeError('Vault is locked')
        with self.connection:
            self.connection.execute('DELETE FROM accounts WHERE email = ?', (email,))

    def password(self, email: str) -> str:
        if self.connection is None:
            raise RuntimeError('Vault is locked')
        return generate_password(self.generation_key, email)

    def close(self) -> None:
        try:
            if self.connection is not None:
                self.connection.close()
        finally:
            self.connection = None
            wipe(self.generation_key)
