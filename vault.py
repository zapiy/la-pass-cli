#!/usr/bin/env python3
"""Deterministic password vault. Algorithm v1: see README.md before changing crypto."""
from __future__ import annotations

import hashlib
import inspect
import hmac
import re
import string
import time
from pathlib import Path

try:
    import pyperclip
    from sqlcipher3 import dbapi2 as sqlcipher
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, VerticalScroll
    from textual.screen import Screen
    from textual.widgets import Button, Checkbox, Input, Static
except ImportError as error:
    raise SystemExit('Install dependencies: python -m pip install -r requirements.txt') from error

UPPER = string.ascii_uppercase
LOWER = string.ascii_lowercase
DIGITS = string.digits
SYMBOLS = '!@#$%^&*()-_=+'
ALPHABET = UPPER + LOWER + DIGITS + SYMBOLS
LOCK_SECONDS = 1800
DEFAULT_DB = Path(__file__).resolve().with_name('vault.db')


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


def derive_keys(master: str) -> tuple[bytearray, bytearray]:
    if not master:
        raise ValueError('Enter your master password')
    root = bytearray(hashlib.scrypt(master.encode('utf-8'), salt=b'', n=2**17,
                                   r=8, p=1, dklen=32, maxmem=256 * 1024**2))
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


class VaultError(Exception):
    pass


class VaultSession:
    def __init__(self, connection, generation_key: bytearray):
        self.connection = connection
        self.generation_key = generation_key

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


class FormInput(Input, inherit_bindings=False):
    BINDINGS = [Binding("backspace", "delete_left", show=False),
                Binding("delete", "delete_right", show=False)]


class SecretInput(FormInput):
    """Do not offer clipboard-copy shortcuts or selection on focus for secrets."""
    def on_unmount(self):
        self.value = ""

    @property
    def _value(self):
        if self.password:
            return Text("*" * len(self.value), no_wrap=True, overflow="ignore")
        return super()._value


class ArrowScreen(Screen):
    BINDINGS = [Binding('up', 'previous', show=False, priority=True),
                Binding('down', 'next', show=False, priority=True),
                Binding('left', 'left', show=False, priority=True),
                Binding('right', 'right', show=False, priority=True),
                Binding('enter', 'activate', show=False, priority=True),
                Binding('escape', 'back', show=False, priority=True),
                Binding('tab,shift+tab', 'noop', show=False, priority=True),
                Binding('space', 'space', show=False, priority=True)]

    def action_noop(self):
        pass

    def action_space(self):
        if isinstance(self.focused, Input):
            self.focused.insert_text_at_cursor(" ")

    def action_previous(self):
        self.focus_previous()

    def action_next(self):
        self.focus_next()

    def action_left(self):
        if isinstance(self.focused, Input):
            self.focused.action_cursor_left()
        else:
            self.focus_previous()

    def action_right(self):
        if isinstance(self.focused, Input):
            self.focused.action_cursor_right()
        else:
            self.focus_next()

    async def action_activate(self):
        if isinstance(self.focused, Checkbox):
            self.focused.toggle()
        elif isinstance(self.focused, Button):
            self.focused.press()
        elif isinstance(self.focused, Input):
            result = self.submit()
            if inspect.isawaitable(result):
                await result

    def submit(self):
        pass

    def action_back(self):
        self.app.lock()


class LoginScreen(ArrowScreen):
    def __init__(self):
        super().__init__()
        self.pending_keys = None

    def compose(self) -> ComposeResult:
        yield Static('   .----.\n  / .--. \\\n  | |  | |\n .--------.\n |   ()   |\n \'--------\'', id='lock-icon', markup=False)
        yield Static('MASTER PASSWORD', id='login-title')
        yield SecretInput(password=True, id='master', select_on_focus=False)
        yield Checkbox('Show password', id='visible')
        yield Button('Unlock', id='unlock', variant='primary')
        yield Static('', id='status', markup=False)
        yield Static('↑ ↓ Select   ← → Cursor / select   Enter Confirm   Esc Exit', id='hint')

    def on_mount(self):
        self.position_login()
        self.query_one('#master', Input).focus()
        if not self.app.db_path.exists():
            self.query_one('#status', Static).update('First run: set your master password')

    def on_resize(self):
        if self.query('#master'):
            self.position_login()

    def position_login(self):
        middle = self.region.height // 2
        distance = 4 if self.region.height >= 30 else 2
        field_y = middle - distance - 1
        check_y = middle + distance - 1
        positions = {'login-title': field_y - 2, 'master': field_y,
                     'visible': check_y, 'unlock': check_y + 3, 'status': check_y + 6}
        for identity, y in positions.items():
            self.query_one('#' + identity).styles.offset = (0, max(0, y - 2))
        self.query_one('#lock-icon').styles.offset = (max(0, self.region.width - 21), 0)

    def on_checkbox_changed(self, event: Checkbox.Changed):
        self.query_one('#master', Input).password = not event.value

    def on_button_pressed(self, event: Button.Pressed):
        self.submit()

    def submit(self):
        field = self.query_one('#master', Input)
        status = self.query_one('#status', Static)
        try:
            keys = derive_keys(field.value)
            field.value = ''
            field.password = True
            self.query_one('#visible', Checkbox).value = False
            if not self.app.db_path.exists() and self.pending_keys is None:
                self.pending_keys = keys
                status.update('Enter your master password again to confirm')
                field.focus()
                return
            if self.pending_keys is not None:
                matches = hmac.compare_digest(keys[0], self.pending_keys[0])
                self.clear_pending()
                if not matches:
                    for key in keys:
                        wipe(key)
                    status.update('Passwords do not match. Start again')
                    field.focus()
                    return
            self.app.session = VaultSession.from_keys(self.app.db_path, *keys)
            self.app.unlocked_at = time.time()
            self.app.switch_screen(AccountsScreen())
        except (ValueError, VaultError, OSError, sqlcipher.Error):
            field.value = ''
            field.password = True
            self.query_one('#visible', Checkbox).value = False
            status.update('Cannot unlock. Check your master password and file access')
            field.focus()

    def clear_pending(self):
        if self.pending_keys:
            for key in self.pending_keys:
                wipe(key)
            self.pending_keys = None

    def on_unmount(self):
        self.clear_pending()

    def action_back(self):
        self.clear_pending()
        self.query_one('#master', Input).value = ''
        self.app.exit()


class AccountsScreen(ArrowScreen):
    def compose(self) -> ComposeResult:
        yield Static('ACCOUNTS', classes='title')
        yield Button('+ Add account', id='add', variant='primary')
        with VerticalScroll(id='accounts'):
            for index, email in enumerate(self.app.session.emails()):
                with Horizontal(classes='account'):
                    yield Static(email, markup=False, classes='email')
                    yield Button('Copy', id=f'copy-{index}', name=email)
        yield Static('', id='status', markup=False)
        yield Static('↑ ↓ Select   ← → Select   Enter Confirm   Esc Lock', id='hint')

    def on_mount(self):
        email = self.app.last_added
        self.app.last_added = None
        buttons = list(self.query(Button))
        next((b for b in buttons if b.name == email), self.query_one('#add', Button)).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if not self.app.ensure_unlocked():
            return
        if event.button.id == 'add':
            self.app.push_screen(AddScreen())
        elif event.button.name:
            try:
                self.app.copy_password(event.button.name)
                self.query_one('#status', Static).update('Copied. Clipboard clears in 30 seconds')
            except pyperclip.PyperclipException:
                self.query_one('#status', Static).update('Clipboard unavailable: check your system backend')


class AddScreen(ArrowScreen):
    def compose(self) -> ComposeResult:
        yield Static('ADD ACCOUNT', classes='title')
        yield FormInput(placeholder='alice@example.com', id='email')
        with Horizontal(id='add-actions'):
            yield Button('Add', id='save', variant='primary')
            yield Button('Cancel', id='cancel')
        yield Static('', id='status', markup=False)

    def on_mount(self):
        self.query_one(Input).focus()

    async def submit(self):
        if not self.app.ensure_unlocked():
            return
        try:
            email = self.app.session.add(self.query_one(Input).value)
        except ValueError as error:
            self.query_one('#status', Static).update(str(error))
            return
        except sqlcipher.Error:
            self.query_one('#status', Static).update('Cannot save email. Check database access and disk space')
            return
        self.app.last_added = email
        await self.app.pop_screen()
        await self.app.switch_screen(AccountsScreen())

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == 'cancel':
            self.action_back()
        else:
            await self.submit()

    def action_back(self):
        self.app.pop_screen()


class VaultApp(App, inherit_bindings=False):
    BINDINGS = []
    CSS = '''
    Screen { background: #101820; color: #e2e8f0; padding: 2 4; }
    Input { width: 48; max-width: 95%; }
    Input:focus, Button:focus, Checkbox:focus { border: heavy #57d8bc; }
    Button { min-width: 16; margin: 0 1 0 0; }
    .title { height: 3; text-style: bold; color: #57d8bc; }
    #lock-icon { position: absolute; offset: 0 0; width: 13; height: 7; color: #57d8bc; }
    #login-title { position: absolute; offset: 0 0; height: 1; }
    #master { position: absolute; offset: 0 0; }
    #visible { position: absolute; offset: 0 0; }
    #unlock { position: absolute; offset: 0 0; }
    #status { height: auto; min-height: 2; color: #f0c878; margin-top: 1; }
    LoginScreen #status { position: absolute; offset: 0 0; width: 90%; }
    #hint { dock: bottom; height: 1; color: #9aaebd; }
    #accounts { height: 1fr; margin-top: 1; }
    .account { height: 3; }
    .email { width: 1fr; padding-top: 1; }
    .account Button { width: 18; }
    #add-actions { height: 3; margin-top: 1; }
    '''

    def __init__(self, db_path: Path = DEFAULT_DB):
        super().__init__()
        self.db_path = db_path
        self.session = None
        self.unlocked_at = 0.0
        self.last_added = None
        self.clipboard_digest = None
        self.clipboard_timer = None

    def on_mount(self):
        self.push_screen(LoginScreen())
        self.set_interval(1, self.check_timeout)

    def ensure_unlocked(self):
        if self.session is None:
            return False
        if time.time() - self.unlocked_at >= LOCK_SECONDS:
            self.lock()
            return False
        return True

    def check_timeout(self):
        if self.session is not None:
            self.ensure_unlocked()

    def copy_password(self, email: str):
        if not self.ensure_unlocked():
            return
        password = self.session.password(email)
        pyperclip.copy(password)
        self.clipboard_digest = hashlib.sha256(password.encode('utf-8')).digest()
        del password
        if self.clipboard_timer:
            self.clipboard_timer.stop()
        self.clipboard_timer = self.set_timer(30, self.clear_clipboard)

    def clear_clipboard(self):
        if self.clipboard_digest is not None:
            try:
                current = pyperclip.paste()
                if hmac.compare_digest(hashlib.sha256(current.encode('utf-8')).digest(), self.clipboard_digest):
                    pyperclip.copy('')
            except pyperclip.PyperclipException:
                pass
            finally:
                self.clipboard_digest = None

    def lock(self):
        if self.session is None:
            return
        self.session.close()
        self.session = None
        self.last_added = None
        self.clear_clipboard()
        # Remove any add dialog together with the account screen underneath it.
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.switch_screen(LoginScreen())

    def on_unmount(self):
        if self.session:
            self.session.close()
            self.session = None
        self.clear_clipboard()


if __name__ == '__main__':
    VaultApp().run()
