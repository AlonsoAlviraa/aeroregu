from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from evidence_kernel.paths import schemas_dir


class SchemaError(ValueError):
    pass


@lru_cache(maxsize=1)
def _registry() -> Registry:
    registry: Registry = Registry()
    for path in sorted(schemas_dir().glob("*.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents)
        schema_id = contents.get("$id", path.name)
        registry = registry.with_resource(schema_id, resource)
        registry = registry.with_resource(path.name, resource)
    return registry


def load_schema(name: str) -> dict[str, Any]:
    path = schemas_dir() / name
    return json.loads(path.read_text(encoding="utf-8"))


def validate_instance(name: str, instance: Any) -> None:
    schema = load_schema(name)
    validator = Draft202012Validator(schema, registry=_registry())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        rendered = "; ".join(_format_error(error) for error in errors)
        raise SchemaError(f"{name}: {rendered}")


def _format_error(error: ValidationError) -> str:
    location = "/".join(str(part) for part in error.path) or "<root>"
    return f"{location}: {error.message}"
