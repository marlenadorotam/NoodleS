"""A bounded numeric expression language interpreted without Python execution."""
import ast
from functools import lru_cache
import math
import operator
import re

from .arithmetic import finite_number


VARIABLES = ('x', 'y', 'z')
CONSTANTS = {'pi': math.pi, 'e': math.e}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: math.pow}
FUNCTIONS = {
    'abs': (abs, 1), 'sqrt': (math.sqrt, 1), 'exp': (math.exp, 1), 'log': (math.log, 1),
    'sin': (math.sin, 1), 'cos': (math.cos, 1), 'tan': (math.tan, 1),
    'atan2': (math.atan2, 2), 'min': (min, 2), 'max': (max, 2),
    'floor': (math.floor, 1), 'ceil': (math.ceil, 1),
}
SUPERSCRIPT = str.maketrans('0123456789+-', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻')


def formula_text(value):
    if not isinstance(value, str) or len(value) > 256 or any(ord(ch) < 32 for ch in value):
        raise ValueError('Expression must be one line, up to 256 characters.')
    return value.strip()


def pretty_expression(formula):
    return re.sub(r'(?:\^|\*\*)\s*(?:\(([+-]?\d+)\)|([+-]?\d+)(?![\w.]|\s*(?:\^|\*\*)))',
                  lambda m: (m[1] or m[2]).translate(SUPERSCRIPT), formula)


@lru_cache(maxsize=128)
def compile_expression(formula):
    try:
        root = ast.parse(formula.replace('^', '**'), mode='eval')
    except SyntaxError as exc:
        raise ValueError('Enter a valid expression, for example x^2 - y^2.') from exc
    if sum(1 for _ in ast.walk(root)) > 100:
        raise ValueError('Expression is too complex.')
    used = set()

    def compile_node(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            number = finite_number(node.value)
            return lambda _: number
        if isinstance(node, ast.Name):
            if node.id in VARIABLES:
                used.add(node.id)
                return operator.itemgetter(node.id)
            if node.id in CONSTANTS:
                number = CONSTANTS[node.id]
                return lambda _: number
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = compile_node(node.operand)
            sign = -1 if isinstance(node.op, ast.USub) else 1
            return lambda values: sign*operand(values)
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            fn = BINARY[type(node.op)]
            left, right = compile_node(node.left), compile_node(node.right)
            return lambda values: finite_number(fn(left(values), right(values)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS:
            fn, arity = FUNCTIONS[node.func.id]
            if len(node.args) != arity or node.keywords:
                raise ValueError(f'{node.func.id} needs {arity} argument(s).')
            args = tuple(compile_node(arg) for arg in node.args)
            return lambda values: finite_number(fn(*(arg(values) for arg in args)))
        raise ValueError('Use x, y, z, numeric constants, arithmetic or supported math functions.')

    evaluate = compile_node(root.body)

    def run(values):
        try:
            return finite_number(evaluate(values))
        except (ArithmeticError, ValueError) as exc:
            raise ValueError('Expression cannot be evaluated for these values: '+str(exc)) from exc

    return tuple(name for name in VARIABLES if name in used), run
