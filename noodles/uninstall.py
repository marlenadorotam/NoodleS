"""Remove a source installation of NoodleS from the current Windows account."""
import argparse
from pathlib import Path
import shutil
import sys

from . import install_bridge, install_file_association


def uninstall(project_root, destination=None):
    project_root = project_root.resolve()
    environment = project_root / ".venv"
    if environment.resolve() != environment or (environment.exists() and not environment.is_dir()):
        raise OSError(f"Expected a local virtual environment folder: {environment}")

    if install_bridge.uninstall(project_root, destination):
        print("Removed NoodleSBridge.")
    else:
        print("No NoodleSBridge registered to this checkout.")
    if install_file_association.uninstall(environment / "Scripts" / "pythonw.exe"):
        print("Removed the Windows file association for this checkout.")
    if environment.is_dir():
        shutil.rmtree(environment)
        print("Removed the local Python environment.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, help="Serpentine3D plugin folder used at installation")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    if sys.platform != "win32" or not (project_root / "NoodleS.pyw").is_file():
        parser.error("Run this command from a Windows source checkout of NoodleS.")
    if sys.prefix != sys.base_prefix and Path(sys.prefix).resolve() == project_root / ".venv":
        parser.error("Run with the system Python: py -3.12 -m noodles.uninstall")
    try:
        uninstall(project_root, args.destination)
    except (OSError, ValueError) as exc:
        print(f"Unable to uninstall NoodleS: {exc}", file=sys.stderr)
        return 1
    print("NoodleS removed. Source files and saved documents are still in place.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
