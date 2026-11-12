from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path
import pyperclip
from textual.app import App

from .screens import LoginScreen

LOCK_SECONDS = 1800
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


