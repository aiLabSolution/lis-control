"""A small, dependency-free JSON-Schema validator (the subset the fixture
manifest uses: object/string/array/boolean types, ``required``, ``enum``,
``properties``, ``additionalProperties``, ``items``).

Keeping this tiny and stdlib-only lets the harness validate fixtures with zero
runtime dependencies while ``fixtures/schema/fixture.schema.json`` stays the
single, language-neutral source of truth for the contract.
"""

from __future__ import annotations

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
}


def validate(instance: Any, schema: dict, path: str = "$") -> None:
    """Validate ``instance`` against ``schema``; raise :class:`SchemaError` on the
    first violation. Returns ``None`` on success."""
    expected = schema.get("type")
    if expected is not None:
        py = _TYPES[expected]
        # bool is a subclass of int — keep "boolean" and "number/integer" disjoint.
        if expected in ("number", "integer") and isinstance(instance, bool):
            raise SchemaError(f"{path}: expected {expected}, got boolean")
        if expected != "boolean" and isinstance(instance, bool) and py in (int, (int, float)):
            raise SchemaError(f"{path}: expected {expected}, got boolean")
        if not isinstance(instance, py):
            raise SchemaError(f"{path}: expected {expected}, got {type(instance).__name__}")

    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"{path}: {instance!r} is not one of {schema['enum']}")

    if expected == "object":
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

    elif expected == "array":
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, element in enumerate(instance):
                validate(element, item_schema, f"{path}[{i}]")
