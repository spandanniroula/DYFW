"""Safe arithmetic for the notepad: '12*4', '15% of 80', 'rent/3', '2^10', 'sqrt(2)'."""

import ast
import math
import operator
import re

_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
           ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "floor": math.floor,
          "ceil": math.ceil, "min": min, "max": max, "log": math.log10, "ln": math.log}
_CONSTS = {"pi": math.pi, "e": math.e}
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.+?)\s*$")


def _prepare(expr):
    s = expr.strip()
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)          # 1,200 -> 1200
    s = s.replace("$", "").replace("×", "*").replace("÷", "/").replace("^", "**")
    s = re.sub(r"(?<=[\d)])\s*[xX]\s*(?=[\d(])", "*", s)  # 3 x 4 -> 3*4
    s = re.sub(r"(\d+(?:\.\d+)?)\s*([+-])\s*(\d+(?:\.\d+)?)\s*%\s*$",   # 100 + 15% -> 115
               r"\1*(1\2\3/100)", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\b", r"(\1/100)*", s)        # 15% of 80
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%(?=\s*($|[-+*/)]))", r"(\1/100)", s)  # 15% at end/before op
    return s


def _eval(node, names):
    if isinstance(node, ast.Expression):
        return _eval(node.body, names)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval(node.left, names), _eval(node.right, names)
        if isinstance(node.op, ast.Pow) and (abs(right) > 1000 or abs(left) > 1e100):
            raise ValueError("number too large")
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, names))
    if isinstance(node, ast.Name):
        key = node.id.lower()
        if key in names:
            return names[key]
        if key in _CONSTS:
            return _CONSTS[key]
        raise ValueError(f"unknown name {node.id}")
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id.lower() in _FUNCS and not node.keywords):
        return _FUNCS[node.func.id.lower()](*(_eval(a, names) for a in node.args))
    raise ValueError("unsupported expression")


def evaluate(expr, names=None):
    """Return a number, or None if expr isn't valid math."""
    s = _prepare(expr)
    if not s or len(s) > 300:
        return None
    try:
        value = _eval(ast.parse(s, mode="eval"), names or {})
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def fmt(value):
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    if isinstance(value, int):
        return str(value)
    return f"{value:.10g}"


def scan_names(lines):
    """Collect 'name = expr' definitions and the last '... = result' as 'ans'."""
    names = {}
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = _ASSIGN_RE.match(stripped)
        if m and not stripped.endswith("="):
            value = evaluate(m.group(2), names)
            if value is not None:
                names[m.group(1).lower()] = value
                continue
        if "=" in stripped:
            left, _, right = stripped.rpartition("=")
            value = evaluate(right, names) if right.strip() else None
            if value is not None and evaluate(left, names) is not None:
                names["ans"] = value
    return names
