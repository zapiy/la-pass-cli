import hmac
import time

from rich.text import Text
from sqlcipher3 import dbapi2 as sqlcipher
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Checkbox, Input, Static

from ..crypto import derive_keys, wipe
from ..storage import VaultError, VaultSession
from .accounts import AccountsScreen
from .widgets import ArrowScreen, FormInput


class SecretInput(FormInput):
    """Do not offer clipboard-copy shortcuts or selection on focus for secrets."""
    def on_unmount(self):
        self.value = ""

    @property
    def _value(self):
        if self.password:
            return Text("*" * len(self.value), no_wrap=True, overflow="ignore")
        return super()._value


class LoginScreen(ArrowScreen):
    def __init__(self):
        super().__init__()
        self.pending_keys = None

    def compose(self) -> ComposeResult:
        yield Static('ℓ', id='lock-icon', markup=False)
        with VerticalScroll(id='login-form'):
            yield Static('MASTER PASSWORD', id='login-title')
            yield SecretInput(password=True, id='master', select_on_focus=False)
            yield Checkbox('Show password', id='visible')
            yield Button('Unlock', id='unlock', variant='primary')
            yield Static('', id='status', markup=False)
        yield Static('↑↓ Select  ←→ Cursor  Enter OK  Esc Exit', id='hint')

    def on_mount(self):
        self.query_one('#master', Input).focus()
        if not self.app.db_path.exists():
            self.query_one('#status', Static).update('First run: set your master password')

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
