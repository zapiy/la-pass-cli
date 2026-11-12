import inspect

from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..app import VaultApp


class FormInput(Input, inherit_bindings=False):
    BINDINGS = [Binding("backspace", "delete_left", show=False),
                Binding("delete", "delete_right", show=False)]


class ArrowScreen(Screen):
    app: "VaultApp"

    BINDINGS = [Binding('up', 'previous', show=False, priority=True),
                Binding('down', 'next', show=False, priority=True),
                Binding('left', 'left', show=False, priority=True),
                Binding('right', 'right', show=False, priority=True),
                Binding('enter', 'activate', show=False, priority=True),
                Binding('escape', 'back', show=False, priority=True),
                Binding('tab,shift+tab', 'noop', show=False, priority=True),
                Binding('space', 'space', show=False, priority=True)]

    def on_resize(self):
        self.set_class(self.size.width < 60, 'narrow')
        self.set_class(self.size.height < 24, 'short')

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
