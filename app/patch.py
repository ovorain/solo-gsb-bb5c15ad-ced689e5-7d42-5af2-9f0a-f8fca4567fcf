"""RFC 6902 JSON Patch, applied atomically on a deep copy of the document.

Supported operations: ``add``, ``remove``, ``replace``, ``test``. JSON
Pointers follow RFC 6901 (``~0`` / ``~1`` escapes, ``""`` addresses the whole
document). Array ``add`` accepts a zero-based index or ``-`` (append); every
other operation requires the target to exist and rejects ``-``.

Two failure categories are kept strictly separate:

* :class:`InvalidOperationError` — the request itself is malformed (bad
  operation structure or bad pointer syntax). The service maps this to 422.
* :class:`PatchConflictError` — a well-formed operation failed against the
  current document (missing path, array index out of bounds, failed test).
  The service maps this to 409. Nothing is applied in that case: callers get
  no partial result.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from app.jsonutil import json_equal

SUPPORTED_OPS = ("add", "remove", "replace", "test")


class InvalidOperationError(ValueError):
    """An operation object or its JSON Pointer is malformed (-> 422)."""


class PatchConflictError(Exception):
    """A valid operation could not be applied to the document (-> 409)."""

    def __init__(self, index: int, path: str, reason: str) -> None:
        super().__init__(reason)
        self.index = index
        self.path = path
        self.reason = reason


def parse_pointer(pointer: Any) -> list[str]:
    """Split an RFC 6901 JSON Pointer into reference tokens.

    The empty string addresses the whole document. ``~0`` and ``~1`` unescape
    to ``~`` and ``/``; any other use of ``~`` is a syntax error.
    """
    if not isinstance(pointer, str):
        raise InvalidOperationError("'path' must be a string")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise InvalidOperationError(
            f"invalid JSON Pointer {pointer!r}: must be empty or start with '/'"
        )
    tokens = []
    for raw in pointer.split("/")[1:]:
        i = 0
        while i < len(raw):
            if raw[i] == "~":
                if i + 1 >= len(raw) or raw[i + 1] not in "01":
                    raise InvalidOperationError(
                        f"invalid JSON Pointer {pointer!r}: "
                        f"'~' must be escaped as '~0' and '/' as '~1'"
                    )
                i += 2
            else:
                i += 1
        tokens.append(raw.replace("~1", "/").replace("~0", "~"))
    return tokens


@dataclass
class Operation:
    """One validated patch operation."""

    op: str
    path: str
    tokens: list[str]
    value: Any = None  # only meaningful when has_value is True
    has_value: bool = False


def parse_operation(raw: Any, index: int) -> Operation:
    """Validate one operation's structure and pointer (not the document)."""
    where = f"operations[{index}]"
    if not isinstance(raw, dict):
        raise InvalidOperationError(f"{where} must be an object")
    op = raw.get("op")
    if not isinstance(op, str) or op not in SUPPORTED_OPS:
        raise InvalidOperationError(
            f"{where}: 'op' must be one of {', '.join(SUPPORTED_OPS)}"
        )
    if "path" not in raw:
        raise InvalidOperationError(f"{where} is missing 'path'")
    path = raw["path"]
    tokens = parse_pointer(path)
    has_value = "value" in raw
    if op == "remove":
        if has_value:
            raise InvalidOperationError(f"{where}: 'remove' must not carry a 'value'")
        return Operation(op=op, path=path, tokens=tokens)
    if not has_value:
        raise InvalidOperationError(f"{where}: '{op}' requires a 'value'")
    return Operation(op=op, path=path, tokens=tokens, value=raw["value"], has_value=True)


def _is_index_token(token: str) -> bool:
    """True for canonical RFC 6901 array indices (base 10, no leading zeros)."""
    if not token:
        return False
    if token == "0":
        return True
    return token[0] in "123456789" and all("0" <= c <= "9" for c in token)


def _array_index(
    token: str, *, length: int, allow_end: bool, index: int, path: str
) -> int:
    """Resolve an array reference token to an insertion/access position."""
    if token == "-":
        if allow_end:
            return length  # "-" appends past the last element (add only)
        raise PatchConflictError(index, path, "'-' is only allowed for the 'add' operation")
    if not _is_index_token(token):
        raise PatchConflictError(index, path, f"invalid array index {token!r}")
    position = int(token)
    limit = length if allow_end else length - 1
    if position > limit:
        raise PatchConflictError(
            index, path, f"array index {position} out of bounds (length {length})"
        )
    return position


def _resolve_parent(document: Any, tokens: list[str], index: int, path: str) -> Any:
    """Walk all but the last token; return the container of the target."""
    node = document
    for token in tokens[:-1]:
        if isinstance(node, dict):
            if token not in node:
                raise PatchConflictError(index, path, f"path does not exist: {path!r}")
            node = node[token]
        elif isinstance(node, list):
            node = node[_array_index(token, length=len(node), allow_end=False,
                                     index=index, path=path)]
        else:
            raise PatchConflictError(index, path, f"path does not exist: {path!r}")
    return node


def _apply_one(document: Any, op: Operation, index: int) -> Any:
    """Apply a single operation, returning the (possibly new) document."""
    if not op.tokens:  # empty pointer: the whole document
        if op.op in ("add", "replace"):
            return op.value
        if op.op == "remove":
            return None
        if not json_equal(document, op.value):
            raise PatchConflictError(index, op.path, "test operation failed")
        return document

    parent = _resolve_parent(document, op.tokens, index, op.path)
    last = op.tokens[-1]

    if isinstance(parent, dict):
        exists = last in parent
        if op.op == "add":
            parent[last] = op.value
        elif not exists:
            raise PatchConflictError(index, op.path, f"path does not exist: {op.path!r}")
        elif op.op == "remove":
            del parent[last]
        elif op.op == "replace":
            parent[last] = op.value
        elif not json_equal(parent[last], op.value):
            raise PatchConflictError(index, op.path, "test operation failed")
        return document

    if isinstance(parent, list):
        if op.op == "add":
            position = _array_index(last, length=len(parent), allow_end=True,
                                    index=index, path=op.path)
            parent.insert(position, op.value)
            return document
        position = _array_index(last, length=len(parent), allow_end=False,
                                index=index, path=op.path)
        if op.op == "remove":
            del parent[position]
        elif op.op == "replace":
            parent[position] = op.value
        elif not json_equal(parent[position], op.value):
            raise PatchConflictError(index, op.path, "test operation failed")
        return document

    raise PatchConflictError(index, op.path, f"path does not exist: {op.path!r}")


def apply_patch(document: Any, operations: list[Operation]) -> Any:
    """Apply validated operations in order to a deep copy of ``document``.

    Either every operation succeeds and the patched copy is returned, or one
    fails with :class:`PatchConflictError` and the caller's document is left
    untouched (no partial result).
    """
    result = copy.deepcopy(document)
    for index, op in enumerate(operations):
        result = _apply_one(result, op, index)
    return result
