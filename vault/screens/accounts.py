from functools import partial

import pyperclip
from rich.text import Text
from sqlcipher3 import dbapi2 as sqlcipher
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static

from .widgets import ArrowScreen, FormInput, lap_logo


class AccountsScreen(ArrowScreen):
    def compose(self) -> ComposeResult:
        with Horizontal(id='accounts-header'):
            yield Static(lap_logo(), id='lock-icon', markup=False)
            yield Button('+ Add', id='add', variant='primary')
        with VerticalScroll(id='accounts'):
            for index, email in enumerate(self.app.session.emails()):
                name, domain = email.rsplit('@', 1)
                if len(name) > 2:
                    masked_name = name[0] + '*' * (len(name) - 2) + name[-1]
                else:
                    masked_name = name[0] + '*' * (len(name) - 1)
                with Horizontal(classes='account'):
                    yield Static(f'{masked_name}@{domain}', markup=False, classes='email')
                    yield Button('Copy', id=f'copy-{index}', name=email)
                    yield Button(Text('_[]_\n|><|\n|__|'), id=f'delete-{index}',
                                 name=email, classes='delete-account', tooltip='Delete account')
        yield Static('', id='status', markup=False)
        yield Static('↑↓ Select  Enter OK  Esc Lock', id='hint')

    def on_mount(self):
        email = self.app.last_added
        self.app.last_added = None
        buttons = list(self.query(Button))
        next((b for b in buttons if b.name == email and b.id.startswith('copy-')),
             self.query_one('#add', Button)).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if not self.app.ensure_unlocked():
            return
        if event.button.id == 'add':
            self.app.push_screen(AddScreen())
        elif event.button.has_class('delete-account'):
            masked_email = str(event.button.parent.query_one('.email', Static).render())
            self.app.push_screen(DeleteAccountScreen(masked_email),
                                 partial(self.delete_account, event.button.name))
        elif event.button.name:
            try:
                self.app.copy_password(event.button.name)
                self.query_one('#status', Static).update('Copied. Clipboard clears in 30 seconds')
            except pyperclip.PyperclipException:
                self.query_one('#status', Static).update('Clipboard unavailable: check your system backend')

    def delete_account(self, email: str, confirmed: bool):
        if not confirmed or not self.app.ensure_unlocked():
            return
        try:
            self.app.session.delete(email)
        except sqlcipher.Error:
            self.query_one('#status', Static).update('Cannot delete account. Check database access and try again')
            return
        self.app.switch_screen(AccountsScreen())


class DeleteAccountScreen(ArrowScreen):
    def __init__(self, masked_email: str):
        super().__init__()
        self.masked_email = masked_email

    def compose(self) -> ComposeResult:
        with Horizontal(id='logo-header'):
            yield Static(lap_logo(), id='lock-icon', markup=False)
        with VerticalScroll(id='clear-dialog'):
            yield Static('Delete this account?', classes='title')
            yield Static(self.masked_email, id='delete-email', markup=False)
            yield Static('The selected account will be removed from the vault.')
            with Horizontal(id='clear-actions'):
                yield Button('Cancel', id='cancel-clear')
                yield Button('Delete', id='confirm-clear')
        yield Static('↑↓ Select  ←→ Cursor  Enter OK  Esc Cancel', id='hint')

    def on_mount(self):
        self.query_one('#cancel-clear', Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.dismiss(event.button.id == 'confirm-clear')

    def action_back(self):
        self.dismiss(False)


class AddScreen(ArrowScreen):
    def compose(self) -> ComposeResult:
        with Horizontal(id='logo-header'):
            yield Static(lap_logo(), id='lock-icon', markup=False)
        with VerticalScroll(id='add-form'):
            yield Static('ADD ACCOUNT', classes='title')
            yield FormInput(placeholder='alice@example.com', id='email')
            with Horizontal(id='add-actions'):
                yield Button('Add', id='save', variant='primary')
                yield Button('Cancel', id='cancel')
            yield Static('', id='status', markup=False)
        yield Static('↑↓ Select  ←→ Cursor  Enter OK  Esc Cancel', id='hint')

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
        if event.button.id == 'cancel':
            self.action_back()
        else:
            await self.submit()

    def action_back(self):
        self.app.pop_screen()


