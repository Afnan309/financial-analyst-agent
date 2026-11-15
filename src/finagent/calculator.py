"""Safe arithmetic for the agent. LLMs are bad at arithmetic, so every
calculation goes through this evaluator instead of the model's head.

Only numbers, + - * / **, parentheses and round/abs/min/max are allowed.
No names, attributes, imports or calls to anything else.
"""
from __future__ import annotations

import ast
import operator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"round": round, "abs": abs, "min": min, "max": max}


class CalcError(ValueError):
    pass


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise CalcError("exponent too large")
        if isinstance(node.op, ast.Div) and right == 0:
            raise CalcError("division by zero")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        args = [_eval(a) for a in node.args]
        if node.func.id == "round" and len(args) == 2:
            return float(round(args[0], int(args[1])))
        return float(_FUNCS[node.func.id](*args))
    raise CalcError(f"unsupported expression element: {type(node).__name__}")


def calculate(expression: str) -> float:
    import re

    # drop thousands separators ("4,210.0") but keep argument commas ("round(x, 2)")
    expr = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", expression).replace("$", "").strip()
    if len(expr) > 300:
        raise CalcError("expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"invalid expression: {expression!r}") from e
    return _eval(tree)
