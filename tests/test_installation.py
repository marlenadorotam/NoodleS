from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from noodles import install_bridge, install_file_association, uninstall


ROOT = Path(__file__).resolve().parents[1]


class BridgeUninstallTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.plugins = Path(folder.name) / "plugins"
        self.target = install_bridge.install(self.plugins)
        self.runtime = self.plugins / install_bridge.RUNTIME

    def test_remove_own_installation_preserves_other_plugins(self):
        other = self.plugins / "OtherPlugin.py"
        other.touch()
        backup = self.plugins / "NoodleSBridge.py.001.bak"
        backup.touch()
        extra = self.runtime / "local-notes.txt"
        extra.touch()
        cache = self.runtime / "__pycache__"
        cache.mkdir()
        (cache / "arithmetic.cpython-312.pyc").touch()

        self.assertTrue(install_bridge.uninstall(ROOT, self.plugins))
        self.assertFalse(install_bridge.uninstall(ROOT, self.plugins))
        self.assertEqual(set(self.plugins.iterdir()), {self.runtime, backup, other})
        self.assertEqual(list(self.runtime.iterdir()), [extra])

    def test_legacy_installation_without_manifest(self):
        (self.runtime / install_bridge.MANIFEST).unlink()
        self.assertTrue(install_bridge.uninstall(ROOT, self.plugins))
        self.assertEqual(list(self.plugins.iterdir()), [])

    def test_install_archives_known_retired_entry_point_and_preserves_edits(self):
        retired = self.plugins / "grid_rectangle.py"
        edited = self.plugins / "grid_triangle.py"
        original = b"# Old bundled plugin.\r\n"
        retired.write_bytes(original)
        edited.write_bytes(b"# Locally edited.\n")
        digest = install_bridge._hash(original.replace(b"\r\n", b"\n"))
        with patch.object(install_bridge, "RETIRED_ENTRY_POINTS",
                          {retired.name: digest, edited.name: digest}):
            install_bridge.install(self.plugins)
            install_bridge.install(self.plugins)
        self.assertFalse(retired.exists())
        backup, = self.plugins.glob(retired.name + ".*.bak")
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(edited.read_bytes(), b"# Locally edited.\n")

    def test_other_checkout_and_modified_bridge_are_preserved(self):
        self.assertFalse(install_bridge.uninstall(ROOT / "other-checkout", self.plugins))
        self.assertTrue(self.target.is_file())
        self.target.write_text("# Locally edited.")
        with self.assertRaisesRegex(OSError, "modified file"):
            install_bridge.uninstall(ROOT, self.plugins)
        self.assertEqual(self.target.read_text(), "# Locally edited.")
        self.assertTrue((self.runtime / "editor-path.txt").is_file())

    def test_cleanup_removes_only_the_local_virtual_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            checkout = Path(folder)
            environment = checkout / ".venv"
            environment.mkdir()
            (environment / "pyvenv.cfg").touch()
            graph = checkout / "Design.noodles"
            graph.touch()
            with (patch.object(install_bridge, "uninstall", return_value=True),
                  patch.object(install_file_association, "uninstall", return_value=True)):
                uninstall.uninstall(checkout, self.plugins)
            self.assertFalse(environment.exists())
            self.assertTrue(graph.is_file())


@unittest.skipUnless(sys.platform == "win32", "Tests Windows registry cleanup.")
class AssociationUninstallTests(unittest.TestCase):
    def test_remove_registration_preserves_another_application(self):
        import winreg

        registry = rf"Software\NoodleSInstallationTest_{uuid.uuid4().hex}"
        root = winreg.HKEY_CURRENT_USER
        written_keys = set()

        def set_value(path, name, value):
            with winreg.CreateKey(root, path) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            while path.startswith(registry):
                written_keys.add(path)
                path = path.rsplit("\\", 1)[0]

        interpreter = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        with patch.multiple(install_file_association, CLASSES=rf"{registry}\Classes",
                            CAPABILITIES=rf"{registry}\App\Capabilities",
                            REGISTERED_APPS=rf"{registry}\RegisteredApplications"):
            try:
                values = install_file_association._application_values(interpreter)
                for (path, name), value in values.items():
                    set_value(path, name, value)
                extension = rf"{registry}\Classes\.noodles"
                set_value(extension, "", "Other.Graph")
                open_with = rf"{extension}\OpenWithProgids"
                set_value(open_with, "Other.Graph", "")
                self.assertFalse(install_file_association.uninstall(interpreter.with_name("other.exe")))
                self.assertTrue(install_file_association.uninstall(interpreter))
                self.assertFalse(install_file_association.uninstall(interpreter))
                with winreg.OpenKey(root, extension) as key:
                    self.assertEqual(winreg.QueryValueEx(key, "")[0], "Other.Graph")
                with winreg.OpenKey(root, open_with) as key:
                    self.assertEqual(winreg.QueryValueEx(key, "Other.Graph")[0], "")
                    with self.assertRaises(FileNotFoundError):
                        winreg.QueryValueEx(key, "NoodleS.Graph")
                with self.assertRaises(FileNotFoundError):
                    winreg.OpenKey(root, rf"{registry}\Classes\NoodleS.Graph")
            finally:
                for path in sorted(written_keys, key=lambda item: item.count("\\"), reverse=True):
                    try:
                        winreg.DeleteKey(root, path)
                    except FileNotFoundError:
                        pass
