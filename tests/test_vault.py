import tempfile
import unittest
from pathlib import Path
import vault
from unittest.mock import patch


class CryptoTests(unittest.TestCase):
    def test_canonical_email(self):
        self.assertEqual(vault.canonical_email(' Alice@EXAMPLE.COM '), 'Alice@example.com')
        for value in ('', 'abc', 'a@@b.com', 'a b@c.com', 'a@', '@example.com'):
            with self.assertRaises(ValueError):
                vault.canonical_email(value)

    def test_deterministic_and_separate(self):
        gen, db = vault.derive_keys('test master phrase')
        self.assertNotEqual(gen, db)
        again, _ = vault.derive_keys('test master phrase')
        self.assertEqual(gen, again)
        password = vault.generate_password(gen, 'Alice@example.com')
        self.assertEqual(password, vault.generate_password(again, ' Alice@EXAMPLE.COM '))
        self.assertNotEqual(password, vault.generate_password(gen, 'bob@example.com'))
        self.assertEqual(password, 'WZUf-1GTVFDrUsDPGbcT1Oc)')
        self.assertEqual(len(password), 24)
        for chars in (vault.UPPER, vault.LOWER, vault.DIGITS, vault.SYMBOLS):
            self.assertTrue(any(c in chars for c in password))

    def test_encrypted_database_and_session_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault.db'
            session = vault.VaultSession.open(path, 'test master phrase')
            session.add('alice@example.com')
            with self.assertRaises(ValueError):
                session.add('alice@example.com')
            password = session.password('alice@example.com')
            key = session.generation_key
            session.close()
            self.assertFalse(any(key))
            self.assertIsNone(session.connection)
            with self.assertRaises(RuntimeError):
                session.password('alice@example.com')
            data = path.read_bytes()
            self.assertNotIn(b'alice@example.com', data)
            self.assertNotIn(b'SQLite format', data)
            with self.assertRaises(vault.VaultError):
                vault.VaultSession.open(path, 'wrong password')
            reopened = vault.VaultSession.open(path, 'test master phrase')
            self.assertEqual(reopened.emails(), ['alice@example.com'])
            self.assertEqual(reopened.password('alice@example.com'), password)
            reopened.close()


class UITests(unittest.IsolatedAsyncioTestCase):
    async def test_menu_resizes_without_hiding_controls(self):
        from textual.widgets import Button, Input
        with tempfile.TemporaryDirectory() as directory:
            app = vault.VaultApp(Path(directory) / 'vault.db')
            async with app.run_test(size=(100, 32)) as pilot:
                for width, height in ((100, 32), (40, 18), (28, 14), (80, 24)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    field = app.screen.query_one('#master', Input)
                    button = app.screen.query_one('#unlock', Button)
                    button.focus()
                    await pilot.pause()
                    self.assertGreaterEqual(button.region.x, 0)
                    self.assertLessEqual(button.region.right, width)
                    self.assertLessEqual(button.region.bottom, height)
                    self.assertLessEqual(field.region.right, width)
                    self.assertLessEqual(button.region.width, 11)
                    self.assertEqual(str(app.screen.query_one('#lock-icon').render()), 'ℓ')
                app.session = vault.VaultSession.open(app.db_path, 'test master phrase')
                app.session.add('long.account.name@example.com')
                await app.switch_screen(vault.AccountsScreen())
                for screen in (app.screen, vault.AddScreen()):
                    if screen is not app.screen:
                        await app.push_screen(screen)
                    for width, height in ((28, 14), (40, 18), (100, 32)):
                        await pilot.resize_terminal(width, height)
                        await pilot.pause()
                        for button in screen.query(Button):
                            button.focus()
                            await pilot.pause()
                            self.assertLessEqual(button.region.width, 12)
                            self.assertGreaterEqual(button.region.x, 0)
                            self.assertLessEqual(button.region.right, width)
                            self.assertLessEqual(button.region.bottom, height)

    async def test_keyboard_create_add_lock(self):
        from textual.widgets import Input, Checkbox
        with tempfile.TemporaryDirectory() as directory:
            app = vault.VaultApp(Path(directory) / 'vault.db')
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                self.assertTrue(app.screen.query_one('#master', Input).password)
                await pilot.press('down')
                self.assertIsInstance(app.focused, Checkbox)
                await pilot.press('enter')
                self.assertFalse(app.screen.query_one('#master', Input).password)
                await pilot.press('up')
                app.screen.query_one('#master', Input).value = 'test master phrase'
                await pilot.press('enter')
                await pilot.pause()
                self.assertTrue(app.screen.query_one('#master', Input).password)
                app.screen.query_one('#master', Input).value = 'test master phrase'
                await pilot.press('enter')
                await pilot.pause()
                self.assertIsNotNone(app.session)
                await pilot.press('enter')
                await pilot.pause()
                app.screen.query_one('#email', Input).value = 'alice@example.com'
                await pilot.press('enter')
                await pilot.pause()
                self.assertTrue(app.focused.id.startswith('copy-'))
                app.unlocked_at -= 1801
                app.check_timeout()
                await pilot.pause()
                self.assertIsNone(app.session)
                self.assertEqual(app.screen.query_one('#master', Input).value, '')
                self.assertTrue(app.screen.query_one('#master', Input).password)

    async def test_timeout_from_add_and_clipboard_ownership(self):
        from textual.widgets import Input
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault.db'
            session = vault.VaultSession.open(path, 'test master phrase')
            session.add('alice@example.com')
            session.close()
            app = vault.VaultApp(path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                app.screen.query_one('#master', Input).value = 'test master phrase'
                await pilot.press('enter')
                await pilot.pause()
                clipboard = {'value': ''}
                with patch.object(vault.pyperclip, 'copy', side_effect=lambda v: clipboard.update(value=v)), patch.object(vault.pyperclip, 'paste', side_effect=lambda: clipboard['value']):
                    app.copy_password('alice@example.com')
                    self.assertEqual(len(clipboard['value']), 24)
                    app.clear_clipboard()
                    self.assertEqual(clipboard['value'], '')
                    app.copy_password('alice@example.com')
                    clipboard['value'] = 'user replacement'
                    app.clear_clipboard()
                    self.assertEqual(clipboard['value'], 'user replacement')
                await pilot.press('enter')
                await pilot.pause()
                self.assertIsInstance(app.screen, vault.AddScreen)
                key = app.session.generation_key
                app.unlocked_at -= 1801
                app.check_timeout()
                await pilot.pause()
                self.assertIsInstance(app.screen, vault.LoginScreen)
                self.assertFalse(any(key))
                self.assertFalse(any(isinstance(s, vault.AccountsScreen) for s in app.screen_stack))

    async def test_only_navigation_keys_and_mask(self):
        from textual.widgets import Input, Checkbox
        with tempfile.TemporaryDirectory() as directory:
            app = vault.VaultApp(Path(directory) / 'vault.db')
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                field = app.screen.query_one('#master', Input)
                checkbox_region = app.screen.query_one('#visible', Checkbox).region
                self.assertGreater(checkbox_region.y, field.region.bottom)
                self.assertEqual(app.screen.query_one('#lock-icon').styles.text_align, 'right')
                await pilot.press('a', 'b', 'c', 'left', 'backspace')
                self.assertEqual(field.value, 'ac')
                self.assertEqual(field._value.plain, '**')
                await pilot.press('down')
                checkbox = app.focused
                self.assertIsInstance(checkbox, Checkbox)
                await pilot.press('space')
                self.assertFalse(checkbox.value)
                await pilot.press('tab')
                self.assertIs(app.focused, checkbox)
                await pilot.press('enter')
                self.assertTrue(checkbox.value)
                await pilot.press('escape')
                self.assertFalse(app.is_running)

if __name__ == '__main__':
    unittest.main()
