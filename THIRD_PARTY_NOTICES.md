# Third-party notices

NoodleS uses the MIT License for its own source files. The following projects provide the editor libraries, CAD runtime, and earlier tooling.

## Serpentine3D

NoodleSBridge integrates with Serpentine3D. Its viewport acceleration adapts Serpentine3D code for point-marker rendering, shape classification, and free-point extraction (`viewport_acceleration.py`). CAD View reuses Serpentine3D's native tessellation and surface isocurve routines (`cad_viewport.py`). The upstream notice is reproduced below. [Serpentine3D](https://github.com/chisomobanzi/Serpentine3D) · [Serpentine3D 0.12.4 license](https://github.com/chisomobanzi/Serpentine3D/blob/v0.12.4/LICENSE)

```text
MIT License

Copyright (c) 2026 Chisomo Banzi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Separately installed dependencies

| Project | Role | Upstream license |
| --- | --- | --- |
| [NodeGraphQt](https://github.com/jchanvfx/NodeGraphQt) | Graph editor and controls | MIT |
| [Qt.py](https://github.com/mottosso/Qt.py) | Qt binding compatibility layer | MIT |
| [Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html) | PySide6 and Shiboken | Open-source LGPLv3 or GPL terms, with commercial licensing also available. Check the terms of the exact modules distributed. |
| [types-PySide6](https://pypi.org/project/types-PySide6/) | Type stubs installed by Qt.py | MIT |
| [setuptools](https://github.com/pypa/setuptools) | Packaging and compatibility dependency for the pinned graph editor | MIT |
| [OCP](https://github.com/CadQuery/OCP) | Python bindings used by the Serpentine3D CAD runtime | Apache-2.0 |
| [Open CASCADE Technology](https://github.com/Open-Cascade-SAS/OCCT) | CAD geometry kernel used by Serpentine3D | LGPL-2.1 with the OCCT exception for the supported kernel version |
| [NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt) | Array operations in the Serpentine3D bridge | BSD-3-Clause for NumPy itself, with separate notices for bundled components |
| [PyOpenGL](https://github.com/mcfletch/pyopengl/blob/master/license.txt) | OpenGL bindings used by scene previews and annotations | BSD-style PyOpenGL license |

Editor dependencies are installed through pip. Serpentine3D and its CAD libraries have their own distribution. A future bundled installer should be reviewed against the terms of the exact dependencies it redistributes.

The [project acknowledgments](CONTRIBUTING.md#acknowledgments) credit the authors and reference materials.

