# Contributing to NoodleS

## Report an issue

Open a GitHub issue with the NoodleS version or commit, your Windows and Python versions, and your Serpentine3D version when relevant. Tell us what you expected, what happened, and how to reproduce it. For a graph or geometry issue, a reduced `.noodles` graph and its matching `.serp` model are useful when you can share them. Include only the relevant log excerpt and remove private paths or credentials. If you report a viewport performance issue, include the geometry type, element count, and CAD View setting.

## Run tests

Set up the editor as described in the [Windows setup guide](docs/getting-started.md). In PowerShell, run the Python and Qt tests from the repository root.

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Some tests open loopback TCP sockets for the bridge. The suite needs permission to use local sockets. Native CAD tests are skipped when the optional Serpentine3D test runtime is absent.

### Native CAD tests

Use a separate Python 3.12 environment for these tests so the editor setup stays reproducible. Download the source ZIP for Serpentine3D 0.13.0 and extract it. Point the test runner at the directory that contains the `serpentine3d` Python package. [Serpentine3D 0.13.0](https://github.com/chisomobanzi/Serpentine3D/releases/tag/v0.13.0)

```powershell
py -3.12 -m venv .test-output\native-env
.\.test-output\native-env\Scripts\python.exe -m pip install -r requirements.txt "cadquery-ocp==7.9.3.1.1" "numpy>=1.26" "PyOpenGL>=3.1" "ezdxf>=1.1"
$env:NOODLES_TEST_SERPENTINE_SOURCE = Read-Host "Path to the extracted Serpentine3D source root"
$env:QT_QPA_PLATFORM = "offscreen"
.\.test-output\native-env\Scripts\python.exe -m unittest discover -s tests -p test_point_native.py -v
```

The native fixtures create isolated, in-memory CAD scenes. Remove the `-p test_point_native.py` filter to include the other integration suites. Run native geometry tests when changing a shape factory, reference, or scene operation.

### Viewport diagnostics

Use the same native environment and source path for these manual checks. Clear the offscreen setting to run them with the Windows OpenGL viewport.

```powershell
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
.\.test-output\native-env\Scripts\python.exe tools/benchmark_grids.py --mode native
.\.test-output\native-env\Scripts\python.exe tools/verify_operations_render.py --surfaces
.\.test-output\native-env\Scripts\python.exe tools/verify_vector_preview.py
```

The grid benchmark also supports `--mode data` and `--mode ui` with the standard editor environment. Diagnostics that write output create `.test-output/` as needed.

## Code and documentation

Editor code lives in `noodles/`, shared geometry and data code in `noodles/backend/`, and the Serpentine3D entry point in `noodles/serpentine_plugin/NoodleSBridge.py`. Each `__init__.py` marks its own folder as a Python package.

Use English for UI text and public documentation. For node and geometry changes, see the [node development guide](docs/adding-a-node.md), the [ParametricObject contract](docs/parametric-object-contract.md), and the relevant tests.

## Acknowledgments

- **Johnny Chan and the NodeGraphQt contributors** built the graph editor that NoodleS uses for its canvas, nodes, ports, and connections. [NodeGraphQt](https://github.com/jchanvfx/NodeGraphQt)
- **Marcus Ottosson and the Qt.py contributors** maintain the Qt binding compatibility layer. The **Qt for Python team** provides PySide6 and Shiboken. **Chad Dombrova and the types-PySide6 contributors** develop the type stubs installed by Qt.py. [Qt.py](https://github.com/mottosso/Qt.py/blob/master/LICENSE) · [Qt for Python](https://pypi.org/project/PySide6/) · [types-PySide6](https://pypi.org/project/types-PySide6/)
- **Chisomo Banzi and the Serpentine3D contributors** built the CAD application that hosts NoodleSBridge. NoodleS adapts Serpentine3D viewport code, and CAD View reuses its native tessellation and surface isocurve routines. [Serpentine3D](https://github.com/chisomobanzi/Serpentine3D) · [Third-party notices](THIRD_PARTY_NOTICES.md#serpentine3d)
- **Open Cascade SAS and the OCCT contributors** develop the geometry kernel. The **OCP contributors** provide the Python bindings, and **Bernhard Walter** is credited as the author of the `cadquery-ocp` package used in the native test setup. [OCCT](https://github.com/Open-Cascade-SAS/OCCT) · [OCP](https://github.com/CadQuery/OCP) · [cadquery-ocp](https://pypi.org/project/cadquery-ocp/7.9.3.1.1/)
- **The NumPy developers** provide the array operations used in the CAD bridge. **Mike C. Fletcher and the PyOpenGL contributors** provide the OpenGL bindings used for scene previews and annotations. [NumPy](https://numpy.org/) · [PyOpenGL](https://pypi.org/project/PyOpenGL/)
- **The Python Packaging Authority and the setuptools contributors** maintain the build tools used to package NoodleS. [setuptools](https://github.com/pypa/setuptools)
- **Leon Thomm and the Ryven contributors** built the visual scripting environment used for the first prototype. [Ryven](https://github.com/leon-thomm/Ryven)

### Design and mathematical references

- **Roger Penrose** discovered the P2 tiling. **Simon Tatham's** half-tile diagrams guided the subdivision in the Penrose P2 node. [Two algorithms for randomly generating aperiodic tilings](https://www.chiark.greenend.org.uk/~sgtatham/quasiblog/aperiodic-tilings/)
- **B. C. Carlson's** chapter on elliptic integrals in the NIST Digital Library of Mathematical Functions provided the formulas used to compute ellipse perimeters. [Chapter 19 and §19.8](https://dlmf.nist.gov/19) · [Equation 19.8.6](https://dlmf.nist.gov/19.8.E6)

