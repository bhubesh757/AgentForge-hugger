"""Restricted, AST-whitelisted evaluator for workflow condition expressions.

Never uses ``eval``/``exec``. Supported grammar:
  * literals (str/int/float/bool/None), list and tuple literals
  * the name ``state`` (and only that name), subscripts ``x[...]`` with literal-ish keys
  * method call ``<expr>.get(key[, default])`` (no other attributes / calls)
  * comparisons (== != < <= > >= in, not in, is, is not), ``and``/``or``, ``not``
Anything else raises :class:`UnsafeExpressionError`.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

MAX_EXPRESSION_LENGTH = 1000
MAX_DEPTH = 32


class UnsafeExpressionError(ValueError):
    """Expression uses syntax outside the whitelist."""


class ConditionEvaluationError(ValueError):
    """Expression was valid but failed at runtime (e.g. missing key)."""


_CMP_OPS: dict[type[ast.cmpop], Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_CONST_TYPES = (str, int, float, bool, type(None))


def _check(node: ast.AST, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise UnsafeExpressionError("expression nested too deeply")
    if isinstance(node, ast.Expression):
        _check(node.body, depth + 1)
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, _CONST_TYPES):
            raise UnsafeExpressionError(f"constant type {type(node.value).__name__} not allowed")
    elif isinstance(node, ast.Name):
        if node.id != "state" or not isinstance(node.ctx, ast.Load):
            raise UnsafeExpressionError(f"name '{node.id}' not allowed (only 'state')")
    elif isinstance(node, (ast.List, ast.Tuple)):
        for elt in node.elts:
            _check(elt, depth + 1)
    elif isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Slice):
            raise UnsafeExpressionError("slices not allowed")
        _check(node.value, depth + 1)
        _check(node.slice, depth + 1)
    elif isinstance(node, ast.Call):
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get"):
            raise UnsafeExpressionError("only '.get()' calls are allowed")
        if node.keywords or not 1 <= len(node.args) <= 2:
            raise UnsafeExpressionError(".get() takes 1 or 2 positional arguments")
        _check(func.value, depth + 1)
        for arg in node.args:
            _check(arg, depth + 1)
    elif isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _CMP_OPS:
                raise UnsafeExpressionError(f"operator {type(op).__name__} not allowed")
        _check(node.left, depth + 1)
        for c in node.comparators:
            _check(c, depth + 1)
    elif isinstance(node, ast.BoolOp):
        for v in node.values:
            _check(v, depth + 1)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not):
            if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
                _check(node.operand, depth + 1)
                return
            raise UnsafeExpressionError("only 'not' unary operator allowed")
        _check(node.operand, depth + 1)
    else:
        raise UnsafeExpressionError(f"syntax '{type(node).__name__}' not allowed")


@lru_cache(maxsize=512)
def compile_expression(expression: str) -> ast.Expression:
    """Parse + whitelist-check. Raises UnsafeExpressionError. Cached."""
    if not isinstance(expression, str) or not expression.strip():
        raise UnsafeExpressionError("expression must be a non-empty string")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise UnsafeExpressionError("expression too long")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"invalid syntax: {exc.msg}") from exc
    _check(tree)
    return tree


def _eval(node: ast.AST, state: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return state
    if isinstance(node, ast.List):
        return [_eval(e, state) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(e, state) for e in node.elts)
    if isinstance(node, ast.Subscript):
        container = _eval(node.value, state)
        key = _eval(node.slice, state)
        if not isinstance(container, (Mapping, Sequence)) or isinstance(container, (bytes,)):
            raise ConditionEvaluationError(f"cannot subscript {type(container).__name__}")
        try:
            return container[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ConditionEvaluationError(f"lookup failed: {exc!r}") from exc
    if isinstance(node, ast.Call):
        target = _eval(node.func.value, state)  # type: ignore[attr-defined]
        args = [_eval(a, state) for a in node.args]
        if not isinstance(target, Mapping):
            # Calling .get() on non-mapping (e.g. a string last_output) yields default.
            return args[1] if len(args) > 1 else None
        try:
            return target.get(*args)
        except TypeError as exc:
            raise ConditionEvaluationError(str(exc)) from exc
    if isinstance(node, ast.Compare):
        left = _eval(node.left, state)
        for op, comp in zip(node.ops, node.comparators, strict=True):
            right = _eval(comp, state)
            try:
                ok = _CMP_OPS[type(op)](left, right)
            except TypeError as exc:
                raise ConditionEvaluationError(str(exc)) from exc
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in node.values:
                result = _eval(v, state)
                if not result:
                    return result
            return result
        result = False
        for v in node.values:
            result = _eval(v, state)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        val = _eval(node.operand, state)
        return (not val) if isinstance(node.op, ast.Not) else -val
    raise UnsafeExpressionError(f"syntax '{type(node).__name__}' not allowed")  # pragma: no cover


def evaluate_condition(expression: str, state: dict) -> bool:
    """Evaluate ``expression`` against ``state``; returns a bool. Raises on unsafe syntax."""
    tree = compile_expression(expression)
    return bool(_eval(tree.body, state))
