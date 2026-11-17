"""Register .noodles files with Windows for the current user."""
import ctypes
from pathlib import Path
import sys


EXTENSION = '.noodles'
PROG_ID = 'NoodleS.Graph'
CLASSES = r'Software\Classes'
CAPABILITIES = r'Software\NoodleS\Capabilities'
REGISTERED_APPS = r'Software\RegisteredApplications'
SHCNE_ASSOCCHANGED = 0x08000000


def _application_values(interpreter):
    package = Path(__file__).resolve().parent
    icon = package / 'noodles-icon.ico'
    launcher = package.parent / 'NoodleS.pyw'
    entry_point = f'"{launcher}"' if launcher.is_file() else '-m noodles'
    command = f'"{interpreter}" -E {entry_point} -- "%1"'
    icon_location = f'"{icon}",0'

    graph_type = rf'{CLASSES}\{PROG_ID}'
    extension = rf'{CLASSES}\{EXTENSION}'
    return {
        (graph_type, ''): 'NoodleS Graph',
        (rf'{graph_type}\DefaultIcon', ''): icon_location,
        (rf'{graph_type}\Application', 'ApplicationName'): 'NoodleS',
        (rf'{graph_type}\Application', 'ApplicationIcon'): icon_location,
        (CAPABILITIES, 'ApplicationName'): 'NoodleS',
        (CAPABILITIES, 'ApplicationDescription'): 'Parametric graph editor for Serpentine3D.',
        (CAPABILITIES, 'ApplicationIcon'): icon_location,
        (rf'{CAPABILITIES}\FileAssociations', EXTENSION): PROG_ID,
        (REGISTERED_APPS, 'NoodleS'): CAPABILITIES,
        (rf'{extension}\OpenWithProgids', PROG_ID): '',
        (rf'{graph_type}\shell\open\command', ''): command,
    }


def install():
    if sys.platform != 'win32':
        raise OSError('File association setup requires Windows.')
    import winreg

    interpreter = Path(sys.executable).with_name('pythonw.exe')
    icon = Path(__file__).resolve().with_name('noodles-icon.ico')
    for required in (interpreter, icon):
        if not required.is_file():
            raise FileNotFoundError(f'Required file is missing: {required}')

    def set_value(path, name, value):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    for (path, name), value in _application_values(interpreter).items():
        set_value(path, name, value)

    extension = rf'{CLASSES}\{EXTENSION}'
    # Provide a fallback for this private extension only when it has no class.
    # Windows retains control of any explicit Default Apps selection.
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, EXTENSION) as key:
            existing_class, _ = winreg.QueryValueEx(key, '')
    except FileNotFoundError:
        existing_class = None
    if not existing_class:
        set_value(extension, '', PROG_ID)

    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, 0, None, None)


def uninstall(interpreter):
    """Remove this checkout's current-user registration and leave other defaults."""
    import winreg

    root = winreg.HKEY_CURRENT_USER
    graph_type = rf'{CLASSES}\{PROG_ID}'
    command = rf'{graph_type}\shell\open\command'
    values = _application_values(interpreter)

    def read(path, name):
        try:
            with winreg.OpenKey(root, path) as key:
                return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None

    if read(command, '') != values[command, '']:
        return False

    extension = rf'{CLASSES}\{EXTENSION}'
    for (path, name), value in {(extension, ''): PROG_ID, **values}.items():
        if read(path, name) == value:
            with winreg.OpenKey(root, path, access=winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
    keys = {path for path, _ in values if path != REGISTERED_APPS}
    keys.update((extension, rf'{graph_type}\shell\open', rf'{graph_type}\shell'))
    for path in sorted(keys, key=lambda path: path.count('\\'), reverse=True):
        try:
            with winreg.OpenKey(root, path) as key:
                subkeys, value_count, _ = winreg.QueryInfoKey(key)
            if not subkeys and not value_count:
                winreg.DeleteKey(root, path)
        except FileNotFoundError:
            pass
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, 0, None, None)
    return True


def main():
    try:
        install()
    except OSError as exc:
        print(f'Unable to register NoodleS graphs: {exc}', file=sys.stderr)
        return 1
    print('Registered .noodles files for this Windows account.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
