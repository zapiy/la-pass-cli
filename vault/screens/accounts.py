import pyperclip
from sqlcipher3 import dbapi2 as sqlcipher
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static

from .widgets import ArrowScreen, FormInput


class AccountsScreen(ArrowScreen):
    def compose(self) -> ComposeResult:
        yield Static('ACCOUNTS', classes='title')
        yield Button('+ Account', id='add', variant='primary')
        with VerticalScroll(id='accounts'):
            for index, email in enumerate(self.app.session.emails()):
                with Horizontal(classes='account'):
                    yield Static(email, markup=False, classes='email')
                    yield Button('Copy', id=f'copy-{index}', name=email)
        yield Static('', id='status', markup=False)
        yield Static('↑↓ Select  Enter OK  Esc Lock', id='hint')

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


