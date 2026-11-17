# Deconstruct Brep and Braced Grid 1-D Structure

Both nodes are in **Library → Operations**. To build a braced grid over a loft, connect **Loft.G → Deconstruct Brep.Brep**, then **Faces → Braced Grid 1-D Structure.Surface**. The two line outputs can feed separate **Pipe** nodes.

## Deconstruct Brep

Supply geometry with native faces. The node returns **Faces**, **Edges**, and **Vertices** in one branch per input object. Faces and edges refer to the exact source subshapes. Shared topology appears once, degenerate edges are omitted, and faces keep their orientation and trims. Outputs remain graph data.

## Braced Grid 1-D Structure

Supply one face per **Surface** item. **U Divisions** and **V Divisions** are integers between 1 and 128 and both default to 10. The node samples equal parameter steps in the native face domain. A full periodic direction needs at least two divisions, and duplicate nodes at the seam of a face are merged.

**Primary Lines** connects neighboring samples along U and V. **Brace Lines** adds a consistently oriented diagonal to each eligible cell. Both outputs contain straight members. A member that crosses a hole or leaves the trimmed face in UV is omitted. **Structure Nodes** returns points used by at least one member. Equal UV steps can produce unequal physical distances.

Inputs support Graft and Flatten. Outputs use corresponding paths per face. A node can produce up to 6,000 members and publishes all lines as one ParametricObject. The `bracedgrid1d` command uses the same algorithm on one selected face with the editor closed.
