"""Human-readable port names; compact canvas labels and graph keys stay unchanged."""
from .backend.geometry import GEOMETRY_SPECS
from .backend.solids import SOLID_SPECS
from .backend.grids import GRID_SPECS
from .backend.previews import PREVIEW_SPECS
from .backend.operations import NATIVE_SCENE_SPECS, OPERATION_SPECS
from .backend.moves import MOVE_SPECS
from .backend.math_nodes import MATH_SPECS
from .backend.data_helpers import WORLD_PLANES


def compact_port_name(operation, name, is_input):
    if operation == 'vector' and not is_input:
        return {'Vector': 'V', 'Length': 'L'}.get(name, name)
    return name


def full_port_name(operation, name, is_input):
    if operation in GEOMETRY_SPECS:
        if is_input:
            return next((d.label for d in GEOMETRY_SPECS[operation]['inputs'] if d.port == name), name)
        if operation == 'curves':
            labels = {'C': 'Curves'}
        elif operation == 'mesh':
            labels = {'M': 'Referenced Meshes'}
        elif operation == 'mesh_edges':
            labels = {'E1': 'Boundary Edges', 'E2': 'Interior Edges', 'E3': 'Non-Manifold Edges'}
        elif operation in ('brep_to_mesh', 'mesh_join', 'weld_mesh'):
            labels = {'M': {'brep_to_mesh': 'Triangulated Meshes', 'mesh_join': 'Joined Meshes',
                            'weld_mesh': 'Welded Meshes'}[operation]}
        elif operation == 'face_neighbours':
            labels = {'N': 'Adjacent Face Indices', 'B': 'Boundary Edge Count per Face',
                      'X': 'Non-Manifold Edge Count per Face'}
        elif operation == 'deconstruct_mesh':
            labels = {'V': 'Vertices', 'F': 'Faces (Zero-Based Vertex Indices)',
                      'C': 'Vertex Colors (Unavailable in Serpentine Meshes)', 'N': 'Vertex Normals'}
        elif operation == 'deconstruct_face':
            labels = {port: f'Vertex Index {port}' for port in 'ABCD'}
        elif operation == 'face_boundaries':
            labels = {'B': 'Mesh Face Boundaries'}
        elif operation == 'curve_length':
            labels = {'L': 'Curve Arc Length'}
        elif operation == 'cap_holes':
            labels = {'B': 'Capped Breps', 'K': 'Native Geometry Kind'}
        elif operation == 'project':
            labels = {'G': 'Projected Geometry'}
        elif operation in ('boolean_split', 'boolean_split_parametric'):
            labels = {'G': 'Solid Pieces', 'Count': 'Piece Count'}
        elif operation == 'section':
            labels = {'C': 'Section Curves', 'R': 'Section Regions'}
        elif operation == 'contour':
            labels = {'C': 'Contour Curves', 'R': 'Filled Regions'}
        elif operation == 'scale_non_uniform':
            labels = {'G': 'Scaled Geometry'}
        elif operation == 'surface_isocurves':
            labels = {'U': 'Curves Along U (Fixed V)', 'V': 'Curves Along V (Fixed U)',
                      'Count': 'Trimmed Curve Count'}
        elif operation == 'gradient':
            labels = {'C': 'Gradient Colors', 'D': 'Applied Domains'}
        elif operation == 'text_tag':
            labels = {'T': 'Formatted Labels', 'Count': 'Label Count'}
        elif operation == 'dimension':
            labels = {'L': 'Measured 3D Length', 'Count': 'Dimension Count'}
        elif operation == 'curve_curve':
            labels = {'P': 'Intersection Points', 'tA': 'Parameters on Curve A',
                      'tB': 'Parameters on Curve B', 'C': 'Overlapping Curves'}
        elif operation == 'region_boolean':
            labels = {'R': 'Filled Regions', 'C': 'Region Outlines'}
        elif operation == 'area':
            labels = {'A': 'Area', 'C': 'Area Centroid'}
        elif operation == 'volume':
            labels = {'V': 'Volume', 'C': 'Volume Centroid'}
        elif operation == 'triangle_face':
            labels = {'F': 'Triangle Faces'}
        elif operation == 'face_normals':
            labels = {'C': 'Face Centers', 'N': 'Unit Face Normals'}
        elif operation == 'delaunay_mesh':
            labels = {'M': 'Mesh', 'U': 'Normalized U (Periodic U)', 'V': 'Normalized V (Periodic U)'}
        elif operation == 'construct_mesh':
            labels = {'M': 'Mesh'}
        elif operation == 'deconstruct_point':
            labels = {'X': 'X Coordinate', 'Y': 'Y Coordinate', 'Z': 'Z Coordinate'}
        elif operation == 'random':
            labels = {'R': 'Random Numbers'}
        elif operation == 'plane_surface':
            labels = {'P': 'Plane Surface'}
        elif operation == 'rotate':
            labels = {'G': 'Rotated Geometry', 'A': 'Applied Angle (Degrees)', 'Count': 'Geometry Count'}
        elif operation == 'scale':
            labels = {'G': 'Scaled Geometry', 'F': 'Applied Factor', 'Count': 'Geometry Count'}
        elif operation == 'mirror':
            labels = {'G': 'Mirrored Geometry', 'Count': 'Geometry Count'}
        elif operation == 'orient':
            labels = {'G': 'Oriented Geometry', 'X': 'Plane-to-Plane Transforms', 'Count': 'Copy Count'}
        elif operation == 'duplicate_data':
            labels = {'D': 'Duplicated Data'}
        elif operation == 'dispatch':
            labels = {'A': 'True Items', 'B': 'False Items'}
        elif operation == 'weave':
            labels = {'W': 'Woven Data'}
        elif operation == 'shift_list':
            labels = {'L': 'Shifted List'}
        elif operation == 'cross_reference':
            labels = {'A': 'Paired Items from A', 'B': 'Paired Items from B'}
        elif operation in WORLD_PLANES:
            labels = {'P': f"Plane {WORLD_PLANES[operation]}"}
        elif operation in MOVE_SPECS:
            labels = {'G':'Moved Geometry','X':'Translation Transform' if operation=='move_gh' else 'World Translation X',
                      'Y':'World Translation Y','Z':'World Translation Z','Count':'Geometry Count'}
        elif operation in ('fillet', 'fillet_parametric'):
            labels = {'G': 'Filleted Curve', 'R': 'Fillet Radius', 'Flat': 'Flattened Curves', 'Count': 'Curve Count'}
        elif operation == 'map_surface':
            labels = {'C': 'Mapped Curves', 'Count': 'Curve Count'}
        elif operation == 'bounding_box':
            labels = {'B': 'Oriented Bounding Box', 'G': 'Box Geometry'}
        elif operation == 'brep_join':
            labels = {'B': 'Joined Breps', 'C': 'Closed'}
        elif operation == 'isotrim':
            labels = {'S': 'Trimmed Surface'}
        elif operation == 'uv_panels':
            labels = {'S': 'Trimmed UV Panels', 'Count': 'Panel Count'}
        elif operation == 'surface_box':
            labels = {'B': 'Target Boxes', 'Count': 'Box Count', 'Skipped': 'Skipped Cells'}
        elif operation in ('surface_morph', 'box_morph'):
            labels = {'G': 'Morphed Geometry'}
        elif operation == 'delaunay':
            labels = {'C': 'Triangle Contours', 'Count': 'Triangle Count'}
        elif operation == 'voronoi':
            labels = {'C': 'Cell Contours', 'Count': 'Contour Count'}
        elif operation == 'hexagon_tiling':
            labels = {'C': 'All Cell Contours', 'H': 'Complete Hexagons', 'P': 'Complete Cell Centers',
                      'Count': 'Contour Count'}
        elif operation == 'penrose_p2':
            labels = {'C': 'Tile Contours', 'K': 'Kite Contours', 'D': 'Dart Contours',
                      'A': 'Matching Arcs', 'Count': 'Tile Contour Count'}
        elif operation == 'deconstruct_brep':
            labels = {'F': 'Faces', 'E': 'Edges', 'V': 'Vertices'}
        elif operation == 'braced_grid_1d':
            labels = {'A': 'Primary Lines', 'B': 'Brace Lines', 'N': 'Structure Nodes'}
        elif operation in ('populate_2d', 'populate_geometry'):
            labels = {'P': 'Population Points'}
        elif operation in ('array', 'array_polar', 'objects_on_points'):
            labels = {'G': 'Placed Geometry', 'Count': 'Copy Count', 'Flat': 'Flattened Copies',
                      'Name': 'Collection Name'}
        elif operation == 'array_along_curve':
            labels = {'G': 'Arrayed Geometry', 'X': 'Placement Transforms'}
        elif operation == 'simplify':
            labels = {'T': 'Simplified Tree', 'B': 'Branch Count', 'N': 'Item Count'}
        elif operation == 'flip_matrix':
            labels = {'T': 'Transposed Tree', 'B': 'Branch Count', 'N': 'Item Count'}
        elif operation == 'tree_viewer':
            labels = {'V': 'Preview Text', 'P': 'Paths', 'B': 'Branch Count', 'N': 'Item Count'}
        elif operation == 'sort_list':
            labels = {'K': 'Sorted Keys', 'A': 'Reordered Values'}
        elif operation == 'tree_branch':
            labels = {'B': 'Selected Branches'}
        elif operation == 'replace_paths':
            labels = {'T': 'Tree With New Paths'}
        elif operation == 'text':
            labels = {'T': 'Text'}
        elif operation == 'value_list':
            labels = {'V': 'Selected Value'}
        elif operation == 'read_csv':
            labels = {'R': 'Table Rows', 'H': 'Column Headers', 'N': 'Row Count'}
        elif operation in ('bool', 'merge', 'list_item', 'list_length'):
            labels = {'B':'Boolean'} if operation == 'bool' else {
                'D':'Merged Data', 'I':'Selected Items', 'L':'Branch Lengths', 'T':'Total Items', 'B':'Branch Count'}
        elif operation == 'curve_domain':
            labels = {'D': 'Native Parameter Domain', 'L': 'Parameter Span'}
        elif operation in ('surface_domain', 'deconstruct_domain2'):
            labels = {'U': 'U Parameter Domain', 'V': 'V Parameter Domain', 'D': 'UV Domain²'}
        elif operation == 'divide_domain2':
            labels = {'S': 'Segments (Domain²)'}
        elif operation == 'reparameterize_surface':
            labels = {'S': 'Surface with UV View'}
        elif operation == 'surface_evaluate':
            labels = {'P': 'Sample Points', 'N': 'Oriented Unit Normals', 'U': 'U Derivatives',
                      'V': 'V Derivatives', 'F': 'Tangent Planes', 'u': 'Sampled U Parameters',
                      'v': 'Sampled V Parameters', 'Count': 'Sample Count', 'Skipped': 'Skipped Sample Count'}
        elif operation == 'surface_closest_point':
            labels = {'P': 'Closest Surface Points', 'U': 'U Parameters', 'V': 'V Parameters', 'D': 'Distances'}
        elif operation in ('divide_curve', 'divide_by_length', 'evaluate_curve'):
            labels = {'P': 'Division Points', 'T': 'Unit Tangents', 't': 'Native Parameters', 'Count': 'Sample Count'}
            if operation == 'evaluate_curve':
                labels['P'] = 'Sample Points'
        elif operation == 'shatter':
            labels = {'C': 'Curve Fragments', 'D': 'Source Parameter Subdomains'}
        elif operation == 'flip_curve':
            labels = {'C': 'Oriented Curves', 'F': 'Was Flipped'}
        elif operation == 'move_seam':
            labels = {'C': 'Curves With Moved Seams', 'P': 'Seam Points'}
        elif operation == 'deconstruct_plane':
            labels = {'O': 'Origin', 'X': 'Local X Axis', 'Y': 'Local Y Axis', 'Z': 'Local Z Axis'}
        elif operation == 'plane_fit':
            labels = {'P': 'Best-Fit Plane', 'D': 'Maximum Deviation', 'R': 'Root Mean Square Deviation'}
        elif operation == 'curve_closest_point':
            labels = {'P': 'Closest Points', 't': 'Curve Parameters (Normalized or Native)', 'D': 'Distances'}
        elif operation == 'sort_along_curve':
            labels = {'P': 'Sorted Original Points', 'I': 'Original Point Indices', 't': 'Native Curve Parameters'}
        elif operation == 'sort_points':
            labels = {'P': 'Sorted Points', 'I': 'Original Point Indices'}
        elif operation == 'cull_duplicate_points':
            labels = {'P': 'Kept Points', 'I': 'Original Point Indices'}
        elif operation == 'closest_points':
            labels = {'P': 'Closest Candidate Points', 'I': 'Candidate Indices', 'D': 'Distances'}
        elif operation == 'curve_curvature':
            labels = {'P': 'Points on Curve', 'K': 'Curvature Vectors'}
        elif operation == 'point_in_curve':
            labels = {'R': 'Relationship', 'I': 'Inside'}
        elif operation in ('frame', 'perp_frames'):
            labels = {'F': 'Perpendicular Planes', 'P': 'Sample Points', 'T': 'Unit Tangents',
                      't': 'Native Parameters', 'Count': 'Frame Count'}
        elif operation == 'pull_point':
            labels = {'P': 'Closest Points', 'D': 'Distances'}
        elif operation == 'loft_options':
            labels = {'O': 'Loft Options'}
        elif operation == 'construct_plane':
            labels = {'P': 'Constructed Planes'}
        elif operation == 'point_cylindrical':
            labels = {'P': 'Cylindrical Points'}
        elif operation in PREVIEW_SPECS:
            labels = {
                'plane_preview': {'P': 'Plane', 'S': 'Visible', 'Count': 'Plane Count'},
                'surface_uv_preview': {'Count': 'Visible Surface Count'},
                'vector_preview': {'V': 'Vector', 'L': 'Vector Length', 'Count': 'Arrow Count'},
            }[operation]
        elif operation in GRID_SPECS:
            labels = {'G':'Grid','C':'Cells (Closed Boundaries)','P':'Cell Centres' if operation in ('grid_triangle','grid_hexagon') else 'Points',
                'V':'Vertices','E':'Unique Edges','R':'Radial Lines','A':'Circular Arcs','NC':'Cell Count',
                'NP':'Point Count (Vertices + Centres)','Count':'Grid Count'}
        elif operation in SOLID_SPECS:
            labels = {'G': 'Geometry', 'O': 'Base Center', 'P': 'Plane', 'N': 'Axis Direction', 'V': 'Volume',
                'S': 'Geometry Type (Solid / Shell)', 'X': 'Width', 'Y': 'Depth', 'Z': 'Height', 'H': 'Height',
                'R': 'Radius', 'D': 'Diameter', 'C': 'Center', 'Top': 'Top Center', 'Tip': 'Cone Tip',
                'Count': 'Geometry Count', 'Out': 'Outer Radius', 'In': 'Inner Radius', 'r': 'Minor Radius'}
            if operation in ('sphere', 'torus'):
                labels['O'] = 'Center'
            if operation == 'ellipsoid':
                labels.update(O='Center', X='Radius X', Y='Radius Y', Z='Radius Z')
            if operation == 'box':
                labels['O'] = 'Base Corner'
            if operation == 'pyramid':
                labels['Tip'] = 'Pyramid Apex'
            if operation == 'torus':
                labels['R'] = 'Major Radius'
            if operation == 'truncated_cone':
                labels.update(R='Base Radius', r='Top Radius')
            if operation == 'paraboloid':
                labels.update(O='Vertex', Top='Rim Center')
        elif operation in OPERATION_SPECS or operation in NATIVE_SCENE_SPECS:
            labels = {'G': 'Geometry', 'K': 'Native Geometry Kind', 'SC': 'Section Count', 'Count': 'Geometry Count',
                      'N': 'Surface Normal', 'EC': 'Native Edge Count', 'U': 'Points per Row', 'V': 'Row Count',
                      'Flat': 'Flattened Geometry', 'D': 'Signed Offset Distance'}
        else:
            labels = {'C': 'Curve', 'O': 'Center', 'R': 'Radius', 'N': 'Normal', 'P': 'Plane', 'L': 'Length',
                'Count': 'Curve Count', 'A': 'Start Point', 'M': 'Through Point', 'B': 'End Point',
                'S': 'Sweep Angle (Degrees)', 'D': 'Degree', 'Cl': 'Closed', 'Per': 'Periodic', 'Closed': 'Closed',
                'V': 'Control Points', 'CP': 'Native Control Points', 'X': 'Width', 'Y': 'Height'}
            if operation == 'line':
                labels['D'] = 'Direction'
            if operation == 'rectangle':
                labels['V'] = 'Corners'
            if operation == 'polyline':
                labels['V'] = 'Vertices'
            if operation == 'ellipse':
                labels.update(A='Radius X', B='Radius Y')
            if operation == 'interpcurve':
                labels['V'] = 'Interpolation Points (Generate Only)'
        return labels.get(name, name)
    if operation in MATH_SPECS:
        if is_input:
            label = next((d.label for d in MATH_SPECS[operation]['inputs'] if d.port == name), name)
            if name in ('X', 'Y', 'Z') and operation == 'vector':
                return name+' Coordinate'
            if operation == 'expression':
                return 'Variable '+name.lower()
            return {'A': 'First Value', 'B': 'Second Value'}.get(label, label)
        labels = {'R': 'Result', 'Y': 'Result', 'S': 'Series', 'I': 'Bounds', 'V': 'Vector', 'U': 'Unit Vector',
                  'L': 'Length', 'Flat': 'Flattened Result', 'Count': 'Item Count'}
        if operation == 'remap_numbers':
            labels.update(R='Remapped Values', C='Clipped Values', **{'Flat R': 'Flattened Remapped Values', 'Flat C': 'Flattened Clipped Values'})
        if operation == 'deconstruct_domain':
            labels.update(S='Domain Start', E='Domain End')
        if operation == 'equality':
            labels.update({'=': 'Equal', '≠': 'Not Equal'})
        if operation == 'larger_than':
            labels.update({'>': 'Greater Than', '≥': 'Greater Than or Equal'})
        if operation == 'sum':
            labels['S'] = 'Branch Sum'
        elif operation == 'average':
            labels['A'] = 'Branch Average'
        elif operation == 'maximum':
            labels['M'] = 'Branch Maximum'
        return labels.get(name, name)
    if operation == 'point':
        return {'P': 'Points', 'X': 'X Coordinate', 'Y': 'Y Coordinate', 'Z': 'Z Coordinate'}.get(name, name)
    if operation == 'domain':
        return {'A': 'Start', 'B': 'End', 'D': 'Domain', 'L': 'Length'}.get(name, name)
    if operation == 'range':
        return {'D': 'Domain', 'N': 'Steps', 'R': 'Range', 'Flat': 'Flattened Range', 'Count': 'Item Count'}.get(name, name)
    if operation in ('addition', 'multiplication'):
        return {'A': 'First Value (Number, Vector or Point)', 'B': 'Second Value (Number, Vector or Point)', 'R': 'Result'}.get(name, name)
    return name
