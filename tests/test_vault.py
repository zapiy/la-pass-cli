import tempfile
import unittest
from pathlib import Path
import vault
from unittest.mock import patch


class TerminalTests(unittest.TestCase):
    def test_resize_only_grows_dimensions_below_minimum(self):
        import os
        from vault.app import resize_terminal
        for size, expected in (((40, 14), '\x1b[8;24;80t'),
                               ((120, 14), '\x1b[8;24;120t'),
                               ((40, 40), '\x1b[8;40;80t'),
                               ((80, 24), None), ((120, 40), None)):
            with self.subTest(size=size), patch('vault.app.sys.stdout') as output, patch(
                    'vault.app.os.get_terminal_size', return_value=os.terminal_size(size)):
                output.isatty.return_value = True
                resize_terminal()
                if expected is None:
                    output.write.assert_not_called()
                else:
                    output.write.assert_called_once_with(expected)
                    output.flush.assert_called_once()

    def test_resize_skips_redirected_output_and_unavailable_terminal(self):
        from vault.app import resize_terminal
        with patch('vault.app.sys.stdout') as output, patch(
                'vault.app.os.get_terminal_size', side_effect=OSError) as get_size:
            output.isatty.return_value = False
            resize_terminal()
            get_size.assert_not_called()
            output.isatty.return_value = True
            resize_terminal()
            output.write.assert_not_called()


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
    async def test_clear_vault_requires_confirmation_and_resets_login(self):
        from textual.widgets import Button, Input, Static
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault.db'
            session = vault.VaultSession.open(path, 'test master phrase')
            session.add('alice@example.com')
            session.close()
            app = vault.VaultApp(path)
            async with app.run_test(size=(80, 24)) as pilot:
                login = app.screen
                clear = login.query_one('#clear-data', Button)
                unlock = login.query_one('#unlock', Button)
                self.assertGreaterEqual(clear.region.x, unlock.region.right)
                self.assertEqual(clear.styles.color.hex, '#E53935')
                for cancel in ('enter', 'escape'):
                    await pilot.click('#clear-data')
                    self.assertEqual(app.focused.id, 'cancel-clear')
                    self.assertTrue(path.exists())
                    await pilot.press(cancel)
                    self.assertIs(app.screen, login)
                    self.assertTrue(path.exists())
                login.query_one('#master', Input).value = 'secret'
                for suffix in ('-wal', '-shm', '-journal'):
                    Path(str(path) + suffix).write_bytes(b'sidecar')
                await pilot.click('#clear-data')
                await pilot.click('#confirm-clear')
                self.assertIs(app.screen, login)
                self.assertFalse(path.exists())
                for suffix in ('-wal', '-shm', '-journal'):
                    self.assertFalse(Path(str(path) + suffix).exists())
                self.assertEqual(login.query_one('#master', Input).value, '')
                self.assertTrue(clear.disabled)
                self.assertIn('First run', str(login.query_one('#status', Static).render()))
                for _ in range(2):
                    login.query_one('#master', Input).value = 'new master phrase'
                    await pilot.press('enter')
                self.assertIsNotNone(app.session)
                self.assertEqual(app.session.emails(), [])

    async def test_clear_vault_failure_and_missing_storage(self):
        from textual.widgets import Button, Static
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault.db'
            app = vault.VaultApp(path)
            async with app.run_test(size=(28, 14)) as pilot:
                clear = app.screen.query_one('#clear-data', Button)
                self.assertTrue(clear.disabled)
                self.assertLessEqual(clear.region.right, 28)
            path.write_bytes(b'encrypted data')
            app = vault.VaultApp(path)
            async with app.run_test(size=(28, 14)) as pilot:
                login = app.screen
                login.query_one('#clear-data', Button).focus()
                await pilot.pause()
                await pilot.press('enter')
                with patch.object(Path, 'unlink', side_effect=PermissionError):
                    await pilot.press('right', 'enter')
                self.assertTrue(path.exists())
                self.assertIs(app.screen, login)
                self.assertIn('Cannot delete', str(login.query_one('#status', Static).render()))

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
                    self.assertEqual(button.region.width, 17)
                    self.assertEqual(field.region.x, app.screen.query_one('#visible').region.x)
                    self.assertEqual(button.styles.background.hex, '#29B6F6')
                    self.assertEqual(app.screen.query_one('#lock-icon').region.height, 4)
                    self.assertEqual(str(app.screen.query_one('#lock-icon').render()).splitlines()[1].rstrip(), '| |    / \\  | _ \\')
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
