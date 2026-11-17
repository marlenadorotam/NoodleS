"""Install and remove the Serpentine3D adapter for NoodleS."""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import time


LICENSE_FILES = ("LICENSE", "THIRD_PARTY_NOTICES.md")
ENTRY_POINT = "NoodleSBridge.py"
RUNTIME = "_noodles_core"
MANIFEST = "installation.json"
# SHA-256 of the last shipped copies, with LF line endings.
RETIRED_ENTRY_POINTS = {
    "NoodleSBridgeRefresh.py": "4f30613ba94e2df7726622a6bbb5694f250b4333a0f9ffa12057ce2ba035e137",
    "NoodleSPrimitives.py": "252860f76a49b3c9a174e29cad33a89d7de9e375798885bdbb6ed00a0ecf9c1e",
    "NoodleSPreviews.py": "2a6d8d9d3652eded8328a9a2056a3eccccdd1a4f86fc2224e65bdca85ad3b8b4",
    "NoodleSOperations.py": "1176c13c69b4a7530989deb38f60e9b0588102e6180905a88733a028de284238",
    "grid_rectangle.py": "b0baf1210fa06007911de261569d78e6fcd1deefd312960a847303bf92e3fe98",
    "grid_triangle.py": "5387740873b638f0e690c0924a676e171e5c1203e8d384da0d4834df590f2791",
    "grid_hexagon.py": "b76acaf730f8c7c4a823019a822259e02fe091021da3547946deeb8f56836e8a",
    "grid_radial.py": "d1bc2f6da5f27f8785d37c046c8f17c5cf4f4ae7ae0f2428dbe83abea31949c0",
}


def _license_paths(project_root):
    if (project_root / "pyproject.toml").is_file():
        return tuple(project_root / name for name in LICENSE_FILES)

    packaged_licenses = {
        path.name: path.locate()
        for path in metadata.files("noodles") or ()
        if path.parent.name == "licenses" and path.parent.parent.name.endswith(".dist-info")
    }
    missing = [name for name in LICENSE_FILES if name not in packaged_licenses]
    if missing:
        raise FileNotFoundError(f"The NoodleS package is missing license files: {', '.join(missing)}")
    return tuple(packaged_licenses[name] for name in LICENSE_FILES)


def plugin_directory(destination=None):
    if destination is None:
        destination = os.environ.get("SERP3D_PLUGIN_DIR", Path.home() / ".serpentine3d" / "plugins")
    return Path(destination).resolve()


def _sources(project_root):
    source = Path(__file__).with_name("serpentine_plugin") / ENTRY_POINT
    backend = source.parent.parent / "backend"
    return {
        f"{RUNTIME}/editor-path.txt": str(project_root).encode("utf-8"),
        **{f"{RUNTIME}/{path.name}": path.read_bytes()
           for path in (*_license_paths(project_root), *backend.glob("*.py"))},
        ENTRY_POINT: source.read_bytes(),
    }


def _hash(content):
    return hashlib.sha256(content).hexdigest()


def install(destination=None):
    directory = plugin_directory(destination)
    source = Path(__file__).with_name("serpentine_plugin") / ENTRY_POINT
    target = directory / source.name
    files = _sources(source.resolve().parents[2])
    runtime = directory / RUNTIME
    runtime.mkdir(parents=True, exist_ok=True)
    for name, file_content in files.items():
        destination_file = directory / name
        if destination_file.exists() and destination_file.read_bytes() == file_content:
            continue
        if destination_file == target and target.exists():
            backup = target.with_name(target.name + f".{time.time_ns()}.bak")
            shutil.copy2(target, backup)
        pending = destination_file.with_suffix(".tmp")
        pending.write_bytes(file_content)
        os.replace(pending, destination_file)
    manifest = runtime / MANIFEST
    pending = manifest.with_suffix(".tmp")
    pending.write_text(json.dumps({name: _hash(data) for name, data in files.items()}), encoding="utf-8")
    os.replace(pending, manifest)
    # Keep locally edited plugins and archive the known superseded scripts.
    for name, digest in RETIRED_ENTRY_POINTS.items():
        old = directory / name
        if old.is_file() and _hash(old.read_bytes().replace(b"\r\n", b"\n")) == digest:
            os.replace(old, old.with_name(name + f'.{time.time_ns()}.bak'))
    return target


def uninstall(project_root, destination=None):
    """Remove the bridge belonging to this checkout and preserve other plugins."""
    directory = plugin_directory(destination)
    runtime = directory / RUNTIME
    launcher = runtime / "editor-path.txt"
    if not launcher.is_file() or Path(launcher.read_text(encoding="utf-8")).resolve() != project_root:
        return False
    manifest = runtime / MANIFEST
    if runtime.resolve() != runtime or manifest.is_symlink():
        raise OSError(f"Unexpected link in the NoodleSBridge folder: {runtime}")
    if manifest.exists():
        files = json.loads(manifest.read_text(encoding="utf-8"))
    else:
        # The previous installer tracked the editor path but did not write a manifest.
        files = {name: _hash(data) for name, data in _sources(project_root).items()}
    if not isinstance(files, dict) or not {ENTRY_POINT, f"{RUNTIME}/{launcher.name}"} <= files.keys():
        raise OSError(f"Invalid NoodleSBridge installation manifest: {manifest}")
    for name, digest in files.items():
        path = directory / name
        valid_runtime_file = (path.parent == runtime and
                              (path.suffix == ".py" or path.name in (*LICENSE_FILES, launcher.name)))
        if (path != directory / ENTRY_POINT and not valid_runtime_file) or path.resolve() != path:
            raise OSError(f"Invalid path in the NoodleSBridge installation: {name}")
        if path.exists() and _hash(path.read_bytes()) != digest:
            raise OSError(f"NoodleSBridge has a modified file. Review it before removing the bridge: {path}")
    (directory / ENTRY_POINT).unlink(missing_ok=True)
    for name in files:
        path = directory / name
        if path not in (directory / ENTRY_POINT, launcher):
            path.unlink(missing_ok=True)
    # Cache files are generated by Python. Remove only the known modules' bytecode.
    for folder, names in ((directory, ("NoodleSBridge",)),
                          (runtime, tuple(Path(name).stem for name in files if name.endswith(".py")))):
        cache = folder / "__pycache__"
        if cache.is_dir() and cache.resolve() == cache:
            for name in names:
                for bytecode in cache.glob(f"{name}.cpython-*.pyc"):
                    bytecode.unlink()
            if not any(cache.iterdir()):
                cache.rmdir()
    manifest.unlink(missing_ok=True)
    launcher.unlink()
    if not any(runtime.iterdir()):
        runtime.rmdir()
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    print("Installed: " + str(install(args.destination)))
    print("Start Serpentine3D, or run its plugins command to load the adapter.")


if __name__ == "__main__":
    main()
