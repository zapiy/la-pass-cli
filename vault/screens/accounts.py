import hashlib
import hmac
from functools import partial
from math import ceil
import time

import pyperclip
from rich.text import Text
from sqlcipher3 import dbapi2 as sqlcipher
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Button, Input, Static

from .widgets import ArrowScreen, FormInput, lap_logo


def mask_email(email: str) -> str:
    name, domain = email.rsplit('@', 1)
    if len(name) > 2:
        name = name[0] + '*' * (len(name) - 2) + name[-1]
    else:
        name = name[0] + '*' * (len(name) - 1)
    return f'{name}@{domain}'


class AccountsScreen(ArrowScreen):
    clipboard_digest: bytes | None = None
    clipboard_timer: Timer | None = None

    COPIED_MESSAGE = 'Copied. Clipboard clears in 30 seconds'
    SEARCH_DELAY = 0.4
    _search_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id='accounts-header'):
            yield Static(lap_logo(), id='lock-icon', markup=False)
            yield FormInput(placeholder='Search', id='search')
            with Horizontal(id='accounts-actions'):
                yield Button('+ Add', id='add', variant='primary')
                yield Button('', id='lock-timer', tooltip='Auto-lock interval')
        with VerticalScroll(id='accounts'):
            for index, email in enumerate(self.app.session.emails()):
                with Horizontal(classes='account'):
                    yield Static(mask_email(email), markup=False, classes='email')
                    yield Button('Copy', id=f'copy-{index}', name=email)
                    yield Button('◉', id=f'show-{index}', name=email, classes='show-email', tooltip='Show email')
                    yield Button(Text('_[]_\n|  |\n|__|'), id=f'delete-{index}',
                                 name=email, classes='delete-account', tooltip='Delete account')
        yield Static('', id='status', markup=False)
        yield Static('↑↓ Select  ←→ Cursor  Enter OK  Esc Lock', id='hint')

    def on_mount(self):
        self.update_lock_timer()
        self.set_interval(1, self.update_lock_timer)
        email = self.app.last_added
        self.app.last_added = None
        buttons = list(self.query(Button))
        next((b for b in buttons if b.name == email and b.id.startswith('copy-')),
             self.query_one('#add', Button)).focus()

    def copy_password(self, email: str):
        if not self.app.ensure_unlocked():
            return
        password = self.app.session.password(email)
        pyperclip.copy(password)
        self.clipboard_digest = hashlib.sha256(password.encode('utf-8')).digest()
        del password
        if self.clipboard_timer:
            self.clipboard_timer.stop()
        self.clipboard_timer = self.set_timer(30, self.clear_clipboard)

    def clear_clipboard(self):
        if self.clipboard_timer is not None:
            self.clipboard_timer.stop()
            self.clipboard_timer = None
        if self.clipboard_digest is not None:
            try:
                current = pyperclip.paste()
                if hmac.compare_digest(hashlib.sha256(current.encode('utf-8')).digest(), self.clipboard_digest):
                    pyperclip.copy('')
            except pyperclip.PyperclipException:
                pass
            finally:
                self.clipboard_digest = None
                for status in self.query('#status').results(Static):
                    if str(status.render()) == self.COPIED_MESSAGE:
                        status.update('')

    def on_unmount(self):
        self.clear_clipboard()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == 'search':
            if self._search_timer is not None:
                self._search_timer.stop()
            self._search_timer = self.set_timer(self.SEARCH_DELAY, self.apply_search)

    def action_left(self):
        field = self.focused
        if isinstance(field, Input) and field.id == 'search' and field.cursor_position == 0:
            self.focus_previous('Button, Input')
        else:
            super().action_left()

    def action_right(self):
        field = self.focused
        if isinstance(field, Input) and field.id == 'search' and field.cursor_position == len(field.value):
            self.focus_next('Button, Input')
        else:
            super().action_right()

    def apply_search(self):
        self._search_timer = None
        query = self.query_one('#search', Input).value.casefold()
        for row in self.query('.account'):
            row.display = query in row.query_one(Button).name.casefold()

    def update_lock_timer(self):
        minutes = max(0, ceil((self.app.lock_seconds - (time.time() - self.app.unlocked_at)) / 60))
        timer = self.query_one('#lock-timer', Button)
        icon = '✎' if timer.has_focus else ' '
        timer.label = f'{minutes} min {icon}'

    def on_descendant_focus(self):
        self.update_lock_timer()

    def on_descendant_blur(self):
        self.update_lock_timer()

    def on_button_pressed(self, event: Button.Pressed):
        if not self.app.ensure_unlocked():
            return
        if event.button.id == 'add':
            self.app.push_screen(AddAccountModal())
        elif event.button.id == 'lock-timer':
            self.app.push_screen(LockIntervalScreen(), self.interval_closed)
        elif event.button.has_class('show-email'):
            showing = str(event.button.label) == '⊘'
            event.button.parent.query_one('.email', Static).update(
                mask_email(event.button.name) if showing else event.button.name)
            event.button.label = '◉' if showing else '⊘'
            event.button.tooltip = 'Show email' if showing else 'Hide email'
        elif event.button.has_class('delete-account'):
            masked_email = str(event.button.parent.query_one('.email', Static).render())
            self.app.push_screen(DeleteAccountModal(masked_email),
                                 partial(self.delete_account, event.button.name))
        elif event.button.name:
            try:
                self.copy_password(event.button.name)
                self.query_one('#status', Static).update(self.COPIED_MESSAGE)
            except pyperclip.PyperclipException:
                self.query_one('#status', Static).update('Clipboard unavailable: check your system backend')

    def interval_closed(self, saved: bool):
        if self.app.session is not None:
            self.update_lock_timer()

    def delete_account(self, email: str, confirmed: bool):
        if not confirmed or not self.app.ensure_unlocked():
            return
        try:
            self.app.session.delete(email)
        except sqlcipher.Error:
            self.query_one('#status', Static).update('Cannot delete account. Check database access and try again')
            return
        self.app.switch_screen(AccountsScreen())


class LockIntervalScreen(ArrowScreen, ModalScreen):
    def compose(self) -> ComposeResult:
        with Vertical(id='interval-dialog'):
            yield Static('Auto-lock interval', id='interval-title')
            for seconds, label in ((1800, '30 min'), (3600, '1h'), (10800, '3h')):
                marker = '●' if self.app.lock_seconds == seconds else ' '
                yield Button(f'{marker} {label}', id=f'interval-{seconds}')
            yield Static('', id='interval-status', markup=False)
            yield Static('↑↓ Select  Enter Save\nEsc Cancel', id='interval-hint')

    def on_mount(self):
        self.query_one(f'#interval-{self.app.lock_seconds}', Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if not self.app.ensure_unlocked():
            return
        try:
            self.app.set_lock_interval(int(event.button.id.removeprefix('interval-')))
        except sqlcipher.Error:
            self.query_one('#interval-status', Static).update('Cannot save interval. Check database access and try again')
            return
        self.dismiss(True)

    def action_back(self):
        self.dismiss(False)


class DeleteAccountModal(ArrowScreen, ModalScreen):
    def __init__(self, masked_email: str):
        super().__init__()
        self.masked_email = masked_email

    def compose(self) -> ComposeResult:
        with VerticalScroll(id='clear-dialog'):
            yield Static('Delete this account?', classes='modal-title')
            yield Static(self.masked_email, id='delete-email', markup=False)
            yield Static('The selected account will be removed from the vault.')
            with Horizontal(id='clear-actions'):
                yield Button('Cancel', id='cancel-clear')
                yield Button('Delete', id='confirm-clear')
            yield Static('←→ Cursor  Enter OK  Esc Cancel', classes='modal-hint')

    def on_mount(self):
        self.query_one('#cancel-clear', Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.dismiss(event.button.id == 'confirm-clear')

    def action_back(self):
        self.dismiss(False)


class AddAccountModal(ArrowScreen, ModalScreen):
    def compose(self) -> ComposeResult:
        with VerticalScroll(id='add-form'):
            yield Static('ADD ACCOUNT', classes='modal-title')
            yield FormInput(placeholder='alice@example.com', id='email')
            with Horizontal(id='add-actions'):
                yield Button('Add', id='save', variant='primary')
                yield Button('Cancel', id='cancel')
            yield Static('', id='status', markup=False)
            yield Static('↑↓ Select  ←→ Cursor  Enter OK  Esc Cancel', classes='modal-hint')

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
        self.app.pop_screen()
        self.app.switch_screen(AccountsScreen())

    async def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == 'cancel':
            self.action_back()
        else:
            await self.submit()

    def action_back(self):
        self.app.pop_screen()


