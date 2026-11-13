from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from textual.app import App

from .screens import LoginScreen
from .storage import LOCK_SECONDS

DEFAULT_DB = Path(__file__).resolve().parent.parent / "vault.db"


class VaultApp(App, inherit_bindings=False):
    BINDINGS = []
    CSS_PATH = 'styles.tcss'

    def __init__(self, db_path: Path = DEFAULT_DB):
        super().__init__()
        self.db_path = db_path
        self.session = None
        self.unlocked_at = 0.0
        self.last_added = None

    def on_mount(self):
        self.push_screen(LoginScreen())
        self.set_interval(1, self.check_timeout)

    def ensure_unlocked(self):
        if self.session is None:
            return False
        if time.time() - self.unlocked_at >= self.lock_seconds:
            self.lock()
            return False
        return True

    def set_lock_interval(self, seconds: int):
        if self.session is None:
            raise RuntimeError('Vault is locked')
        self.session.set_lock_interval(seconds)
        self.unlocked_at = time.time()

    @property
    def lock_seconds(self):
        return self.session.lock_seconds if self.session is not None else LOCK_SECONDS

    def check_timeout(self):
        if self.session is not None:
            self.ensure_unlocked()

    def lock(self):
        if self.session is None:
            return
        self.session.close()
        self.session = None
        self.last_added = None
        # Remove any add dialog together with the account screen underneath it.
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.switch_screen(LoginScreen())

    def on_unmount(self):
        if self.session:
            self.session.close()
            self.session = None


def resize_terminal() -> None:
    """Request a minimum startup size when the terminal supports XTWINOPS."""
    try:
        if not sys.stdout.isatty():
            return
        columns, lines = os.get_terminal_size(sys.stdout.fileno())
        if columns < 80 or lines < 24:
            sys.stdout.write(f'\x1b[8;{max(lines, 24)};{max(columns, 80)}t')
            sys.stdout.flush()
    except OSError:
        pass


def main() -> None:
    resize_terminal()
    VaultApp().run()
