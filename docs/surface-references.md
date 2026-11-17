# Surface references

In **Planar Surface**, **Edge Surface**, or **Loft**, choose **Reference** and click **Set reference** after selecting compatible whole objects in Serpentine3D. **G** returns one geometry value per selected object in selection order. The **Objects** controls apply Graft or Flatten to that collection.

| Node | Reference geometry | Additional results |
| --- | --- | --- |
| Planar Surface | One planar face or several coplanar faces in the same object | N oriented normal from the first face and EC edge count |
| Edge Surface | A surface with one face | EC edge count |
| Loft | A surface, multi-face shell, or solid | K native kind. SC stays empty because there is no captured list of sections |

In Reference mode the node reads the native result and follows CAD edits. The construction inputs apply in Generate mode. Referenced surfaces retain their trims, holes, placement, and orientation. For a later UV operation on a multi-face object, choose the face explicitly in that node. [Surface UV](surface-uv.md)

A persistent marker in the scene resolves the source after renaming and reopening. Missing objects and duplicate markers produce errors. Deleting the Reference node leaves the source in Serpentine3D.

The worker serializes exact BREP using compressed BinTools snapshots. The limits are 64 selected objects per node, 600,000 characters of encoded archives per response, and 8 MiB of uncompressed BinTools data per shape. [Reference editing](reference-editing.md)
