"""A small, dependency-free JSON-Schema validator (the subset the fixture
manifest uses: object/string/array/boolean/number/integer/null types (incl.
``type`` unions), ``required``, ``enum``, ``const``, ``pattern``,
``properties``, ``additionalProperties``, ``items``, and ``if``/``then``/
``else``).

Keeping this tiny and stdlib-only lets the harness validate fixtures with zero
runtime dependencies while ``fixtures/schema/fixture.schema.json`` stays the
single, language-neutral source of truth for the contract.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["SchemaError", "validate"]


class SchemaError(ValueError):
    """Raised when an instance violates the schema."""


_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "string": str,
    "array": list,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
    "null": type(None),
}


def _matches_type(instance: Any, type_name: str) -> bool:
    """Return True if ``instance`` satisfies the single JSON-Schema primitive
    ``type_name``."""
    py = _TYPES[type_name]
    # bool is a subclass of int — keep "boolean" and "number/integer" disjoint.
    if type_name in ("number", "integer") and isinstance(instance, bool):
        return False
    if type_name != "boolean" and isinstance(instance, bool) and py in (int, (int, float)):
        return False
    return isinstance(instance, py)


def validate(instance: Any, schema: dict, path: str = "$") -> None:
    """Validate ``instance`` against ``schema``; raise :class:`SchemaError` on the
    first violation. Returns ``None`` on success."""
    expected = schema.get("type")
    if expected is not None:
        type_names = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(instance, name) for name in type_names):
            got = "null" if instance is None else type(instance).__name__
            raise SchemaError(f"{path}: expected {expected}, got {got}")

    if "const" in schema and instance != schema["const"]:
        raise SchemaError(f"{path}: expected constant {schema['const']!r}, got {instance!r}")

    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"{path}: {instance!r} is not one of {schema['enum']}")

    if "pattern" in schema and isinstance(instance, str):
        if re.search(schema["pattern"], instance) is None:
            raise SchemaError(f"{path}: {instance!r} does not match pattern {schema['pattern']!r}")

    # Structural keywords apply by the instance's runtime type, not by whether
    # the schema happens to declare "type" — this lets partial subschemas (e.g.
    # an "if" condition that only names a "properties" check) drill in too.
    if isinstance(instance, dict):
        props: dict = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                raise SchemaError(f"{path}: missing required property '{req}'")
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    raise SchemaError(f"{path}: additional property '{key}' is not allowed")
        for key, value in instance.items():
            if key in props:
                validate(value, props[key], f"{path}.{key}")

    elif isinstance(instance, list):
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, element in enumerate(instance):
                validate(element, item_schema, f"{path}[{i}]")

    if "if" in schema:
        try:
            validate(instance, schema["if"], path)
        except SchemaError:
            if "else" in schema:
                validate(instance, schema["else"], path)
        else:
            if "then" in schema:
                validate(instance, schema["then"], path)
