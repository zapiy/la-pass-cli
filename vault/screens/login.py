import hmac
import time

import pyperclip
from rich.text import Text
from sqlcipher3 import dbapi2 as sqlcipher
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Static

from ..crypto import canonical_email, derive_generation_key, derive_keys, generate_password, wipe
from ..storage import VaultError, VaultSession
from .accounts import AccountsScreen
from .widgets import ArrowScreen, FormInput, lap_logo


class SecretInput(FormInput):
    """Do not offer clipboard-copy shortcuts or selection on focus for secrets."""
    def on_unmount(self):
        self.value = ""

    @property
    def _value(self):
        if self.password:
            return Text("*" * len(self.value), no_wrap=True, overflow="ignore")
        return super()._value


class ClearDataModal(ArrowScreen, ModalScreen):
    def compose(self) -> ComposeResult:
        with VerticalScroll(id='clear-modal'):
            yield Static('Delete all vault data?', id='clear-title')
            yield Static('All saved accounts will be deleted.\nThis cannot be undone.')
            with Horizontal(id='clear-actions'):
                yield Button('Cancel', id='cancel-clear')
                yield Button('Delete', id='confirm-clear')
            yield Static('←→ Cursor  Enter OK  Esc Cancel', id='clear-hint')

    def on_mount(self):
        self.query_one('#cancel-clear', Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.dismiss(event.button.id == 'confirm-clear')

    def action_back(self):
        self.dismiss(False)


class OnceModal(ArrowScreen, ModalScreen):
    def __init__(self, generation_key: bytearray):
        super().__init__()
        self.generation_key = generation_key

    def compose(self) -> ComposeResult:
        with VerticalScroll(id='once-form'):
            yield Static('GENERATE ONCE', classes='modal-title')
            yield FormInput(placeholder='alice@example.com', id='once-email')
            with Horizontal(id='once-actions'):
                yield Button('Copy', id='once-copy')
            yield Static('', id='status', markup=False)
            yield Static('↑↓ Select  Enter Copy  Esc Close', classes='modal-hint')

    def on_mount(self):
        self.query_one(Input).focus()

    def submit(self):
        status = self.query_one('#status', Static)
        try:
            email = canonical_email(self.query_one(Input).value)
            pyperclip.copy(generate_password(self.generation_key, email))
        except ValueError as error:
            status.update(str(error))
            return
        except pyperclip.PyperclipException:
            status.update('Clipboard unavailable: check your system backend')
            return
        status.update('Copied')

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.submit()

    def action_back(self):
        self.dismiss()

    def on_unmount(self):
        wipe(self.generation_key)


class LoginScreen(ArrowScreen):
    def __init__(self):
        super().__init__()
        self.pending_keys = None

    def compose(self) -> ComposeResult:
        with Horizontal(id='logo-header'):
            yield Static(lap_logo(), id='lock-icon', markup=False)
        with VerticalScroll(id='login-form'):
            yield Static('MASTER PASSWORD', id='login-title')
            yield SecretInput(password=True, id='master', select_on_focus=False)
            yield Static('', id='status', markup=False)
            yield Checkbox('Show password', id='visible')
            with Horizontal(id='login-actions'):
                yield Button('Unlock', id='unlock', variant='primary')
                yield Button('Once', id='once')
                yield Button(Text('_[]_\n|  |\n|__|'), id='clear-data',
                             tooltip='Clear data', disabled=not self.app.db_path.exists())
        yield Static('↑↓ Select  ←→ Cursor  Enter OK  Esc Exit', id='hint')

    def on_resize(self):
        super().on_resize()
        if self.focused is not None:
            self.call_after_refresh(self.focused.scroll_visible, animate=False)

    def on_mount(self):
        self.query_one('#master', Input).focus()
        if not self.app.db_path.exists():
            self.query_one('#status', Static).update('First run: set your master password')

    def on_checkbox_changed(self, event: Checkbox.Changed):
        self.query_one('#master', Input).password = not event.value

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == 'unlock':
            self.submit()
        elif event.button.id == 'once':
            field = self.query_one('#master', Input)
            try:
                generation_key = derive_generation_key(field.value)
            except ValueError as error:
                self.query_one('#status', Static).update(str(error))
                field.focus()
                return
            field.value = ''
            field.password = True
            self.query_one('#visible', Checkbox).value = False
            self.app.push_screen(OnceModal(generation_key))
        elif event.button.id == 'clear-data':
            self.app.push_screen(ClearDataModal(), self.clear_data)

    def clear_data(self, confirmed: bool):
        if not confirmed:
            return
        status = self.query_one('#status', Static)
        try:
            path = self.app.db_path
            for suffix in ('-wal', '-shm', '-journal'):
                path.with_name(path.name + suffix).unlink(missing_ok=True)
            path.unlink(missing_ok=True)
        except OSError:
            status.update('Cannot delete vault data. Check file access and try again')
            return
        self.clear_pending()
        field = self.query_one('#master', Input)
        field.value = ''
        field.password = True
        self.query_one('#visible', Checkbox).value = False
        self.query_one('#clear-data', Button).disabled = True
        self.app.last_added = None
        status.update('First run: set your master password')
        field.focus()

    def submit(self):
        field = self.query_one('#master', Input)
        status = self.query_one('#status', Static)
        if len(field.value) < 3:
            status.update('Master password must contain at least 3 characters')
            field.focus()
            return
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
