"""Pure numeric and vector Ryven operators, with the common NoodleS DataTree."""
from dataclasses import dataclass
import json
import math
from statistics import mean

from .arithmetic import VectorValue, arithmetic_tree, evaluate_arithmetic, finite_number
from .datatree import Branch, DataTree, MAX_ITEMS, MAX_BRANCHES, aligned, map_values, topology
from .domain import DomainValue
from .graph_mapper import mapped_value, normalize_config
from .expression import compile_expression, formula_text


@dataclass(frozen=True)
class MathInput:
    port: str
    label: str
    kind: str = "number"
    defaults: tuple = ()


AB = (MathInput("A", "A"), MathInput("B", "B"))
X = (MathInput("X", "Number/Numbers"),)
MATH_SPECS = {
    "expression": {"class": "ExpressionNode", "name": "Expression",
        "inputs": tuple(MathInput(v.upper(), v.upper(), defaults=(v,)) for v in ("x", "y", "z")),
        "outputs": ("R",), "defaults": {"formula": "x", "x": 0., "y": 0., "z": 0.}},
    "subtraction": {"class": "SubtractionNode", "name": "Subtraction", "inputs": (
        MathInput("A", "A", "number_or_vector"), MathInput("B", "B", "number_or_vector")),
        "outputs": ("R",), "defaults": {}},
    "division": {"class": "DivisionNode", "name": "Division", "inputs": AB, "outputs": ("R",), "defaults": {}},
    "equality": {"class": "EqualityNode", "name": "Equality", "inputs": (
        MathInput("A", "First Number", defaults=("a",)),
        MathInput("B", "Second Number", defaults=("b",))),
        "outputs": ("=", "≠"), "defaults": {"a": 0., "b": 0.}},
    "larger_than": {"class": "LargerThanNode", "name": "Larger Than", "inputs": (
        MathInput("A", "First Number", defaults=("a",)),
        MathInput("B", "Second Number", defaults=("b",))),
        "outputs": (">", "≥"), "defaults": {"a": 0., "b": 0.}},
    "minimum": {"class": "MinimumNode", "name": "Minimum", "inputs": AB, "outputs": ("R",), "defaults": {}},
    "sum": {"class": "SumNode", "name": "Sum", "inputs": (MathInput("N", "Numbers"),),
            "outputs": ("S",), "defaults": {}},
    "average": {"class": "AverageNode", "name": "Average", "inputs": (MathInput("N", "Numbers"),),
                "outputs": ("A",), "defaults": {}},
    "maximum": {"class": "MaximumNode", "name": "Maximum", "inputs": (MathInput("N", "Numbers"),),
                "outputs": ("M",), "defaults": {}},
    "sine": {"class": "SineNode", "name": "Sine", "inputs": X, "outputs": ("Y",), "defaults": {}},
    "square": {"class": "SquareNode", "name": "Square", "inputs": X, "outputs": ("Y",), "defaults": {}},
    "power": {"class": "PowerNode", "name": "Power", "inputs": (
        MathInput("A", "Base", defaults=("base",)), MathInput("B", "Exponent", defaults=("exponent",))),
        "outputs": ("R",), "defaults": {"base": 2., "exponent": 2.}},
    "series": {"class": "SeriesNode", "name": "Series", "inputs": (
        MathInput("S", "Start", defaults=("start",)), MathInput("N", "Step", defaults=("step",)),
        MathInput("C", "Count", defaults=("count",))), "outputs": ("S", "Count"),
        "defaults": {"start": 0.0, "step": 1.0, "count": 10}},
    "bounds": {"class": "BoundsNode", "name": "Bounds", "inputs": (MathInput("N", "Numbers"),),
               "outputs": ("I",), "defaults": {}},
    "deconstruct_domain": {"class": "DeconstructDomainNode", "name": "Deconstruct Domain",
        "inputs": (MathInput("I", "Domain", "domain"),), "outputs": ("S", "E"), "defaults": {}},
    "remap_numbers": {"class": "RemapNumbersNode", "name": "Remap Numbers", "inputs": (
        MathInput("V", "Values"), MathInput("S", "Source Domain", "domain", ("source_start", "source_end")),
        MathInput("T", "Target Domain", "domain", ("target_start", "target_end"))),
        "outputs": ("R", "C", "Flat R", "Flat C"),
        "defaults": {"source_start": 0.0, "source_end": 1.0, "target_start": 0.0, "target_end": 1.0}},
    "vector": {"class": "VectorNode", "name": "Vector", "inputs": (
        MathInput("X", "X", defaults=("x",)), MathInput("Y", "Y", defaults=("y",)),
        MathInput("Z", "Z", defaults=("z",))), "outputs": ("Vector", "Length"),
        "defaults": {"x": 0.0, "y": 0.0, "z": 0.0}},
    "vector_2pt": {"class": "Vector2PtNode", "name": "Vector 2Pt", "inputs": (
        MathInput("A", "Start Point", "point"), MathInput("B", "End Point", "point"),
        MathInput("U", "Unitize", "boolean", ("unitize",))),
        "outputs": ("V", "L"), "defaults": {"unitize": False}},
    "unit_vector": {"class": "UnitVectorNode", "name": "Unit Vector",
        "inputs": (MathInput("V", "Vector", "vector"),), "outputs": ("U",), "defaults": {}},
    **{operation: {"class": "Unit" + axis + "Node", "name": "Unit " + axis,
        "inputs": (MathInput("F", "Factor", defaults=("factor",)),),
        "outputs": ("V",), "defaults": {"factor": 1.0}}
       for operation, axis in (("unit_x", "X"), ("unit_y", "Y"), ("unit_z", "Z"))},
    "amplitude": {"class": "AmplitudeNode", "name": "Amplitude", "inputs": (
        MathInput("V", "Vector", "vector"), MathInput("A", "Amplitude", defaults=("amplitude",))),
        "outputs": ("V",), "defaults": {"amplitude": 1.0}},
    "reverse_vector": {"class": "ReverseVectorNode", "name": "Reverse Vector",
        "inputs": (MathInput("V", "Vector", "vector"),), "outputs": ("V",), "defaults": {}},
    "cross_product": {"class": "CrossProductNode", "name": "Cross Product", "inputs": (
        MathInput("A", "First Vector", "vector"), MathInput("B", "Second Vector", "vector")),
        "outputs": ("V", "L"), "defaults": {}},
    "graph_mapper": {"class": "GraphMapperNode", "name": "Graph Mapper", "inputs": (
        MathInput("V", "Values"), MathInput("I", "Input Domain", "domain", ("input_start", "input_end")),
        MathInput("O", "Output Domain", "domain", ("output_start", "output_end"))),
        "outputs": ("R", "Flat", "Count"),
        "defaults": {"input_start": 0.0, "input_end": 1.0, "output_start": 0.0, "output_end": 1.0},
        "widget_properties": ("graph_config",)},
}
MATH_NODE_OPERATIONS = {spec["class"]: operation for operation, spec in MATH_SPECS.items()}


def math_property_names(operation):
    spec = MATH_SPECS[operation]
    return ("tree_modes", *spec["defaults"], *spec.get("widget_properties", ()))


def series_count(value):
    value = finite_number(value)
    if not 1 <= value <= MAX_ITEMS or int(value) != value:
        raise ValueError(f"Series Count must be an integer between 1 and {MAX_ITEMS:,}.")
    return int(value)


def unitize_flag(value):
    """Retain Vector 2Pt's explicit Boolean/0/1 convention, without truthiness."""
    if isinstance(value, bool):
        return value
    if type(value) in (int, float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in (
            "true", "false", "yes", "no", "on", "off", "1", "0"):
        return value.strip().lower() in ("true", "yes", "on", "1")
    raise ValueError("Unitize requires True/False or 0/1.")


def normalize_math_state(operation, data):
    spec = MATH_SPECS[operation]
    modes = data.get("tree_modes", {})
    if not isinstance(modes, dict) or set(modes) - {i.port for i in spec["inputs"]}:
        raise ValueError("Invalid " + spec["name"] + " input modifiers.")
    if any(mode not in ("none", "graft", "flatten") for mode in modes.values()):
        raise ValueError("Invalid input modifier.")
    state = {"tree_modes": {key: mode for key, mode in modes.items() if mode != "none"}}
    if operation == "graph_mapper":
        if "graph_config" in data and not isinstance(data["graph_config"], dict):
            raise ValueError("Graph Mapper settings must be an object.")
        state["graph_config"] = normalize_config(data.get("graph_config"))
    for key, default in spec["defaults"].items():
        value = data.get(key, default)
        if key == "formula":
            value = formula_text(value)
        elif key == "unitize":
            value = unitize_flag(value)
        elif key == "count":
            value = series_count(value)
        else:
            value = finite_number(value)
            if abs(value) > 1e9:
                raise ValueError("Default parameters must lie between -1e9 and 1e9.")
        state[key] = value
    return state


def math_input_tree(value, descriptor, mode="none"):
    if descriptor.kind in ("point", "vector"):
        tree, kind = arithmetic_tree(value, mode)
        if kind not in (None, descriptor.kind):
            raise ValueError(descriptor.label + " requires " + descriptor.kind.title() + " data.")
        return tree
    if descriptor.kind == "boolean":
        tree = topology(list(value) if isinstance(value, tuple) else value, mode)
        return DataTree(tuple(Branch(b.path, tuple(unitize_flag(item) for item in b.items), b.keys)
                              for b in tree.branches))
    if descriptor.kind == "number_or_vector":
        tree, kind = arithmetic_tree(value, mode)
        if kind not in (None, "number", "vector"):
            raise ValueError(descriptor.label + " requires Number or Vector data.")
        return tree
    if descriptor.kind == "number":
        tree, kind = arithmetic_tree(value, mode)
        if kind not in (None, "number"):
            raise ValueError(descriptor.label + " requires numeric data; Point/Vector is unsupported by this operator.")
        return tree
    if isinstance(value, tuple):
        value = list(value)
    tree = topology(value, mode)
    if any(not isinstance(item, DomainValue) for b in tree.branches for item in b.items):
        raise ValueError(descriptor.label + " requires Domain data.")
    return tree


def _nonzero_domain(value, label):
    if value.start == value.end:
        raise ValueError(label + " must have nonzero length.")
    return value


def _slot_trees(trees, inputs, state, ports, label, strict=False):
    """Retain Ryven's explicit flat-list-to-branch-slot assignment."""
    structured = [i for i, port in enumerate(ports) if
                  isinstance(inputs.get(port), DataTree) or state["tree_modes"].get(port, "none") != "none"]
    if not structured:
        return trees
    base = tuple(aligned(*(trees[i] for i in structured)))
    total = sum(len(rows) for _, rows in base)
    result = list(trees)
    for index in set(range(len(trees))) - set(structured):
        tree = trees[index]
        values = tree.values()
        if not values:
            continue
        if len(base) > 1 and total > 1 and len(values) == total:
            keys = tuple(k for b in tree.branches for k in b.keys)
            offset, branches = 0, []
            for path, rows in base:
                width = len(rows)
                branches.append(Branch(path, values[offset:offset + width], keys[offset:offset + width]))
                offset += width
            result[index] = DataTree(tuple(branches))
        elif (strict and len(values) != 1 and any(len(values) != len(rows) for _, rows in base)
              or not strict and any(len(values) > len(rows) > 1 for _, rows in base)):
            raise ValueError(label + ": ambiguous flat input length for these branch widths.")
    return result


def _series(trees):
    matches = tuple(aligned(*trees))
    split = any(len(rows) > 1 for _, rows in matches)
    plans, empty_paths, total = [], [], 0
    for path, rows in matches:
        if not rows:
            empty_paths.append(path + (0,) if split else path)
            continue
        lengths = [len((t.branches[0] if len(t.branches) == 1 else
                        next(b for b in t.branches if b.path == path)).items) for t in trees]
        if any(length not in (1, max(lengths)) for length in lengths):
            raise ValueError("Series: Start, Step and Count need equal item counts or singletons in each branch.")
        for index, ((start, step, count), keys) in enumerate(rows):
            count = series_count(count)
            total += count
            if total > MAX_ITEMS or len(plans) + len(empty_paths) >= MAX_BRANCHES:
                raise ValueError(f"Series exceeds the {MAX_ITEMS:,} output value or branch limit.")
            plans.append((path + (index,) if split else path, start, step, count, keys))
    if len(plans) + len(empty_paths) > MAX_BRANCHES:
        raise ValueError(f"Series exceeds the {MAX_BRANCHES:,} output branch limit.")
    branches_by_path = {}
    for path, start, step, count, keys in plans:
        numbers = tuple(finite_number(start + index * step) for index in range(count))
        identity = json.dumps(keys, separators=(",", ":"))
        branches_by_path[path] = Branch(path, numbers, tuple(identity + ":" + str(i) for i in range(count)))
    # Preserve the input branch order, including empty branches between lists.
    branches = []
    for path, rows in matches:
        if not rows:
            branches.append(Branch(path + (0,) if split else path, ()))
        else:
            branches.extend(branches_by_path[path + (i,) if split else path] for i in range(len(rows)))
    return {"S": DataTree(tuple(branches)), "Count": total}


def _between_points(a, b, unitize):
    vector = VectorValue(tuple(y - x for x, y in zip(a.xyz, b.xyz)))
    length = finite_number(math.hypot(*vector.xyz))
    if unitize and length > 0:
        vector = VectorValue(tuple(component / length for component in vector.xyz))
    return vector, length


def evaluate_math(operation, parameters, inputs):
    spec = MATH_SPECS[operation]
    state = normalize_math_state(operation, parameters)
    if operation == "subtraction":
        for port in ("A", "B"):
            if port not in inputs:
                raise ValueError("Connect input " + port + ".")
        return evaluate_arithmetic(operation, state, inputs)
    descriptors = spec["inputs"]
    if operation == "expression":
        names, expression = compile_expression(state["formula"])
        if not names:
            return {"R": expression({})}
        descriptors = tuple(d for d in descriptors if d.port.lower() in names)
    trees = []
    collection = any(d.port in state["tree_modes"] for d in descriptors)
    for descriptor in descriptors:
        port = descriptor.port
        if port in inputs:
            value = inputs[port]
        elif descriptor.defaults:
            value = (DomainValue(*(state[k] for k in descriptor.defaults)) if descriptor.kind == "domain"
                     else state[descriptor.defaults[0]])
        else:
            raise ValueError("Connect input " + port + ".")
        collection |= isinstance(value, (DataTree, list, tuple))
        trees.append(math_input_tree(value, descriptor, state["tree_modes"].get(port, "none")))

    def shape(tree):
        return tree if collection or tree.count == 0 else tree.values()[0]

    if operation == "expression":
        trees = _slot_trees(trees, inputs, state, tuple(name.upper() for name in names), "Expression", strict=True)
        return {"R": shape(map_values(lambda *items: expression(dict(zip(names, items))), *trees))}
    if operation == "series":
        return _series(trees)
    if operation == "sum":
        return {"S": shape(DataTree(tuple(Branch(b.path, (finite_number(math.fsum(b.items)),))
                                           for b in trees[0].branches)))}
    if operation in ("average", "maximum"):
        port, reduce_branch = ("A", mean) if operation == "average" else ("M", max)
        return {port: shape(DataTree(tuple(
            Branch(b.path, (reduce_branch(b.items),) if b.items else ()) for b in trees[0].branches)))}
    if operation == "equality":
        equal = map_values(lambda a, b: a == b, *trees)
        return {"=": shape(equal), "≠": shape(map_values(lambda match: not match, equal))}
    if operation == "larger_than":
        return {">": shape(map_values(lambda a, b: a > b, *trees)),
                "≥": shape(map_values(lambda a, b: a >= b, *trees))}
    if operation == "graph_mapper":
        for tree in trees[1:]:
            for domain in tree.values():
                _nonzero_domain(domain, "Graph Mapper domain")
        result = map_values(lambda value, source, target: mapped_value(value, source, target, state["graph_config"]), *trees)
        return {"R": shape(result), "Flat": topology(result, "flatten"), "Count": result.count}
    if operation == "minimum":
        trees = _slot_trees(trees, inputs, state, ("A", "B"), "Minimum")
    if operation == "vector":
        trees = _slot_trees(trees, inputs, state, ("X", "Y", "Z"), "Vector")
        vectors = map_values(lambda x, y, z: VectorValue((x, y, z)), *trees)
        lengths = map_values(lambda vector: finite_number(math.hypot(*vector.xyz)), vectors)
        return {"Vector": shape(vectors), "Length": shape(lengths)}
    if operation == "vector_2pt":
        trees = _slot_trees(trees, inputs, state, ("A", "B", "U"), "Vector 2Pt", strict=True)
        # Use the same matched rows for both outputs. L always describes B-A.
        pairs = map_values(_between_points, *trees)
        vectors = DataTree(tuple(Branch(b.path, tuple(pair[0] for pair in b.items), b.keys) for b in pairs.branches))
        lengths = DataTree(tuple(Branch(b.path, tuple(pair[1] for pair in b.items), b.keys) for b in pairs.branches))
        return {"V": shape(vectors), "L": shape(lengths)}
    if operation in ("unit_x", "unit_y", "unit_z"):
        axis = ("unit_x", "unit_y", "unit_z").index(operation)
        return {"V": shape(map_values(lambda factor: VectorValue(tuple(factor if i == axis else 0 for i in range(3))), *trees))}
    if operation == "unit_vector":
        def unit(vector):
            length = finite_number(math.hypot(*vector.xyz))
            if length <= 1e-15:
                raise ValueError("Unit Vector: zero/invalid vector length (must exceed 1e-15).")
            return VectorValue(tuple(component / length for component in vector.xyz))
        return {"U": shape(map_values(unit, *trees))}
    if operation == "amplitude":
        def resize(vector, amplitude):
            length = finite_number(math.hypot(*vector.xyz))
            return VectorValue((0, 0, 0) if length == 0 or amplitude == 0 else
                               tuple((component / length) * amplitude for component in vector.xyz))
        return {"V": shape(map_values(resize, *trees))}
    if operation == "reverse_vector":
        return {"V": shape(map_values(lambda vector: VectorValue(tuple(-v if v != 0 else 0 for v in vector.xyz)), *trees))}
    if operation == "power":
        def power(base, exponent):
            try:
                return finite_number(math.pow(base, exponent))
            except (ValueError, OverflowError) as exc:
                raise ValueError("Power requires a finite real result.") from exc
        return {"R": shape(map_values(power, *trees))}
    if operation == "cross_product":
        from .curves import cross
        vectors = map_values(lambda a, b: VectorValue(cross(a.xyz, b.xyz)), *trees)
        return {"V": shape(vectors), "L": shape(map_values(lambda v: finite_number(math.hypot(*v.xyz)), vectors))}
    if operation == "bounds":
        values = trees[0].values()
        if not values:
            raise ValueError("Bounds requires at least one number.")
        low, high = min(values), max(values)
        finite_number(high - low)
        # Bounds describes observed data, including a valid singleton interval.
        return {"I": DomainValue(low, high)}
    if operation == "deconstruct_domain":
        return {"S": shape(map_values(lambda domain: domain.start, *trees)),
                "E": shape(map_values(lambda domain: domain.end, *trees))}
    if operation == "remap_numbers":
        def remap(value, source, target):
            _nonzero_domain(source, "Source Domain")
            _nonzero_domain(target, "Target Domain")
            ratio = finite_number((target.end - target.start) / (source.end - source.start))
            result = finite_number(target.start + (value - source.start) * ratio)
            clipped = min(max(target.start, target.end), max(min(target.start, target.end), result))
            return result, clipped
        pairs = map_values(remap, *trees)
        raw = DataTree(tuple(Branch(b.path, tuple(pair[0] for pair in b.items), b.keys) for b in pairs.branches))
        clipped = DataTree(tuple(Branch(b.path, tuple(pair[1] for pair in b.items), b.keys) for b in pairs.branches))
        return {"R": shape(raw), "C": shape(clipped), "Flat R": topology(raw, "flatten"),
                "Flat C": topology(clipped, "flatten")}

    def numeric(*values):
        values = tuple(finite_number(value) for value in values)
        if operation == "division":
            if values[1] == 0:
                raise ValueError("Division by zero.")
            result = values[0] / values[1]
        elif operation == "minimum":
            result = min(values)
        elif operation == "sine":
            result = math.sin(values[0])
        else:  # Square is x², not a square root.
            result = values[0] * values[0]
        return finite_number(result)
    return {spec["outputs"][0]: shape(map_values(numeric, *trees))}
