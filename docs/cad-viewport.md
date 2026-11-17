# CAD Viewport

**CAD View** appears before **S3D Properties** and reflects the current Serpentine3D session. Right-click it to toggle **High Smooth**. The toolbar and Serpentine3D commands share the same state. Older graphs can still open the **CadViewport** node, whose button follows the toolbar.

| Command | Effect |
| --- | --- |
| `cadview` or `cv` | Adaptively samples standalone curves and keeps native surface display meshes. |
| `cadnative` or `cvn` | Restores native display. |
| `cadquality` or `cadq` | Adds finer face tessellation and isocurve sampling. High Smooth uses this mode with default values. |

The `cadquality` defaults are 6° and 12° for curve and face angular deflection, 0.35 and 0.45 for their linear deflection scales and 64 isocurve samples. The limits are 180° for angles and 512 isocurve samples. Clearing **High Smooth** returns to adaptive curves with native surface meshes.

## Display accuracy

CAD View changes display caches for standard BREP shapes. It keeps exact geometry, scene IDs, object attributes and scene revision. Text, dimensions and hatches use native drawing. One worker prepares private OCC copies and Serpentine3D swaps the display meshes on its Qt thread. Native picking stays active. High Smooth computes face normals from the OCC surface at UV samples and can approximate at singularities.

Standalone curves and curve-only compounds target about half a physical pixel. Orthographic views use viewport scale. Perspective uses the visible part of the bounds, camera depth and field of view. The worker uses the highest requirement among visible model views. Sampling levels and hysteresis reduce repeated updates, and results are discarded if the shape or the requested level changed. Technical views and sheets do not drive adaptive sampling. Surface edges, isocurves and silhouettes use native settings in CAD View and fixed tolerances in High Smooth.

## Measured performance

In isolated Serpentine3D 0.12.4 at 150% DPI, the maximum measured errors for a circle and a NURBS curve were 0.40/0.41 px in orthographic view and 0.17/0.16 px in perspective. Display updates after zoom took 58–75 ms. In a 1,000-circle test, the viewport prepared variants for 192 curves and the longest Qt event gap stayed below 50 ms.

For separate toruses with radii of 20 mm and 6 mm on Intel Graphics, High Smooth took the following times from activation through the display update:

| Toruses | Activation | Triangles | Native / High Smooth FPS |
| ---: | ---: | ---: | ---: |
| 25 | 1.43 s | 186,000 | 29.1 / 28.5 |
| 100 | 6.35 s | 744,000 | 23.6 / 23.5 |
| 225 | 16.73 s | 1,674,000 | 17.4 / 17.5 |

At 225 separate objects, buffers occupied about 22 MB natively and 51 MB in High Smooth. The longest Qt gap was 94 ms. With the same toruses in one compound, High Smooth took 11.03 s and the longest Qt gap was 6.79 s. Default CAD View took about 1–2 ms to enable in those ready-to-render scenes because the toruses reused their native meshes.
