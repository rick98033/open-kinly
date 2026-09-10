"""Generate the model-facing prompt and exact JSON Schema from the catalog."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from .catalog import ArgumentSpec, Catalog, ValueType


MIN_CALLS = 1
MAX_CALLS = 8

# This is the approved Kinly clean-room candidate instruction, unchanged.
_INSTRUCTIONS = """Translate the user's request into one JSON object matching the supplied schema.

ADMISSIBLE UTTERANCES
The output contains one or more capability calls, or the unsupported form when the request cannot be represented by the declared capabilities and language forms.
Represent the whole request. Do not emit only its representable part.
This is a single-turn request for explicit actions or declared registrations. Prior-context confirmations, recurrence, undeclared future scheduling, and routines cannot be represented.

NO-GUESS RULE
Use calls only when the current utterance explicitly identifies every action target and required argument.
If a target, referent, object, or required argument is missing or ambiguous, use the unsupported form instead of guessing.
Pronouns, generic phrases, and values alone do not identify a target.

THE AUTHORING LANGUAGE
Use a literal argument only when the user supplies that value.
Use an argument's ref form when the user asks to pass an earlier call's result to that argument; never replace the result with a literal.
For a conditional request, include an unconditional call that reads the needed result before the requested action.
Put the when condition on the requested action.
At most one requested action may have a when condition.
A when condition compares one declared result field from an earlier call with a same-type literal supplied by the user.
Use == or != for strings, integers, or Booleans. Use <, <=, >, or >= only for integers.
Use > for above and < for below. Use >= for at least and <= for at most.
The requested action runs only when the comparison is true.
The result-producing call is unconditional.
The conditional action has no declared terminal result data.
Include every requested action exactly once."""


def _closed_object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _literal_schema(argument: ArgumentSpec) -> dict[str, Any]:
    if argument.value_type == "string":
        schema: dict[str, Any] = {"type": "string", "minLength": 1}
    else:
        schema = {"type": argument.value_type}
    if argument.enum is not None:
        schema["enum"] = list(argument.enum)
    if argument.minimum is not None:
        schema["minimum"] = argument.minimum
    if argument.maximum is not None:
        schema["maximum"] = argument.maximum
    if argument.description:
        schema["description"] = argument.description
    return schema


def _reference_schema(fields: tuple[str, ...]) -> dict[str, Any]:
    return _closed_object(
        {
            "ref": _closed_object(
                {
                    "call": {"type": "integer", "minimum": 1, "maximum": MAX_CALLS},
                    "field": {"type": "string", "enum": list(fields)},
                },
                ["call", "field"],
            )
        },
        ["ref"],
    )


def _result_fields_by_type(catalog: Catalog) -> dict[ValueType, tuple[str, ...]]:
    fields: dict[ValueType, set[str]] = {
        "string": set(),
        "integer": set(),
        "boolean": set(),
    }
    for capability in catalog.capabilities:
        for result in capability.results:
            fields[result.value_type].add(result.name)
    return {kind: tuple(sorted(names)) for kind, names in fields.items()}


def _condition_schema(
    fields_by_type: dict[ValueType, tuple[str, ...]],
) -> dict[str, Any] | None:
    variants: list[dict[str, Any]] = []
    for value_type in ("string", "integer", "boolean"):
        fields = fields_by_type[value_type]
        if not fields:
            continue
        right: dict[str, Any] = {"type": value_type}
        if value_type == "string":
            right["minLength"] = 1
        operators = ["==", "!="]
        if value_type == "integer":
            operators.extend(["<", "<=", ">", ">="])
        variants.append(
            _closed_object(
                {
                    "left": _closed_object(
                        {
                            "call": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_CALLS,
                            },
                            "field": {"type": "string", "enum": list(fields)},
                        },
                        ["call", "field"],
                    ),
                    "op": {"type": "string", "enum": operators},
                    "right": right,
                },
                ["left", "op", "right"],
            )
        )
    if not variants:
        return None
    return variants[0] if len(variants) == 1 else {"oneOf": variants}


def build_schema(catalog: Catalog) -> dict[str, Any]:
    fields_by_type = _result_fields_by_type(catalog)
    condition_schema = _condition_schema(fields_by_type)
    variants: list[dict[str, Any]] = []
    for capability in catalog.capabilities:
        argument_properties: dict[str, Any] = {}
        required_arguments: list[str] = []
        for argument in capability.arguments:
            forms = [_literal_schema(argument)]
            compatible_fields = fields_by_type[argument.value_type]
            if compatible_fields:
                forms.append(_reference_schema(compatible_fields))
            argument_properties[argument.name] = (
                forms[0] if len(forms) == 1 else {"anyOf": forms}
            )
            if argument.required:
                required_arguments.append(argument.name)
        properties: dict[str, Any] = {
            "capability": {
                "type": "string",
                "const": capability.name,
                "description": capability.description,
            },
            "arguments": _closed_object(argument_properties, required_arguments),
        }
        if not capability.results and condition_schema is not None:
            properties["when"] = deepcopy(condition_schema)
        variants.append(_closed_object(properties, ["capability", "arguments"]))

    calls = _closed_object(
        {
            "calls": {
                "type": "array",
                "minItems": MIN_CALLS,
                "maxItems": MAX_CALLS,
                "items": {"oneOf": variants},
            }
        },
        ["calls"],
    )
    unsupported = _closed_object(
        {
            "unsupported": _closed_object(
                {"reason": {"type": "string", "const": "unsupported_request"}},
                ["reason"],
            )
        },
        ["unsupported"],
    )
    return {"oneOf": [calls, unsupported]}


def build_system_prompt(catalog: Catalog) -> str:
    lines = [_INSTRUCTIONS, "", "CAPABILITIES"]
    for capability in catalog.capabilities:
        lines.append(f"- {capability.name}: {capability.description}")
        if capability.arguments:
            lines.append("  arguments:")
            for argument in capability.arguments:
                constraints = [argument.value_type, "required" if argument.required else "optional"]
                if argument.enum is not None:
                    constraints.append("one of " + ", ".join(map(str, argument.enum)))
                if argument.minimum is not None:
                    constraints.append(f"minimum {argument.minimum}")
                if argument.maximum is not None:
                    constraints.append(f"maximum {argument.maximum}")
                suffix = f" — {argument.description}" if argument.description else ""
                lines.append(f"    - {argument.name} ({'; '.join(constraints)}){suffix}")
        else:
            lines.append("  arguments: none")
        if capability.results:
            lines.append("  results:")
            for result in capability.results:
                suffix = f" — {result.description}" if result.description else ""
                lines.append(f"    - {result.name} ({result.value_type}){suffix}")
        else:
            lines.append("  results: none")
    return "\n".join(lines) + "\n"


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def catalog_fingerprint(catalog: Catalog) -> str:
    document = []
    for capability in catalog.capabilities:
        document.append(
            {
                "name": capability.name,
                "description": capability.description,
                "arguments": [
                    {
                        "name": argument.name,
                        "type": argument.value_type,
                        "required": argument.required,
                        "description": argument.description,
                        "minimum": argument.minimum,
                        "maximum": argument.maximum,
                        "enum": argument.enum,
                    }
                    for argument in capability.arguments
                ],
                "results": [
                    {
                        "name": result.name,
                        "type": result.value_type,
                        "description": result.description,
                    }
                    for result in capability.results
                ],
                "runtime_defaults": dict(capability.runtime_defaults),
            }
        )
    return fingerprint(document)
