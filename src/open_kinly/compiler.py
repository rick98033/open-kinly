"""Validate model output and lower it into a typed, dependency-explicit graph."""

from __future__ import annotations

import json
from typing import Any, Never

from jsonschema import Draft202012Validator

from .catalog import Catalog, Scalar, ValueType
from .language import build_schema, catalog_fingerprint, fingerprint


class CompileError(ValueError):
    """The proposed program is syntactically or semantically invalid."""


_ORDERING_OPERATORS = frozenset({"<", "<=", ">", ">="})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise CompileError(f"duplicate JSON property {name!r}")
        result[name] = value
    return result


def _invalid_constant(value: str) -> Never:
    raise CompileError(f"invalid JSON constant {value!r}")


def parse_model_output(text: str) -> dict[str, Any]:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except json.JSONDecodeError as error:
        raise CompileError(f"invalid JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise CompileError("model output must be one JSON object")
    return value


def _scalar_type(value: Scalar) -> ValueType:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    return "string"


def _literal(value: Scalar) -> dict[str, Any]:
    value_type = _scalar_type(value)
    return {"kind": value_type, "value": value}


def _producer_result(
    calls: list[dict[str, Any]],
    catalog: Catalog,
    *,
    current_position: int,
    reference: dict[str, Any],
    location: str,
) -> tuple[str, ValueType]:
    producer_position = reference["call"]
    if producer_position >= current_position:
        raise CompileError(
            f"{location}: result references must point to an earlier call"
        )
    producer_call = calls[producer_position - 1]
    producer = catalog.capability(producer_call["capability"])
    assert producer is not None
    result = producer.result(reference["field"])
    if result is None:
        raise CompileError(
            f"{location}: call {producer_position} does not produce "
            f"{reference['field']!r}"
        )
    return f"c{producer_position}", result.value_type


def compile_program(document: dict[str, Any], catalog: Catalog) -> dict[str, Any]:
    schema = build_schema(catalog)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        location = ".".join(map(str, errors[0].absolute_path)) or "root"
        raise CompileError(f"{location}: {errors[0].message}")
    if "unsupported" in document:
        return {
            "profile": "open_kinly_plan_v1",
            "unsupported": {"reason": "unsupported_request"},
            "catalog_fingerprint": catalog_fingerprint(catalog),
            "schema_fingerprint": fingerprint(schema),
        }

    calls: list[dict[str, Any]] = document["calls"]
    if sum("when" in call for call in calls) > 1:
        raise CompileError("calls: at most one call may contain when")

    nodes: list[dict[str, Any]] = []
    result_nodes: list[str] = []
    for position, call in enumerate(calls, start=1):
        capability = catalog.capability(call["capability"])
        assert capability is not None
        node_id = f"c{position}"
        depends_on: set[str] = set()
        arguments: dict[str, Any] = {}

        for name, value in call["arguments"].items():
            argument = capability.argument(name)
            assert argument is not None
            if isinstance(value, dict) and set(value) == {"ref"}:
                producer_id, result_type = _producer_result(
                    calls,
                    catalog,
                    current_position=position,
                    reference=value["ref"],
                    location=f"calls[{position}].arguments.{name}",
                )
                if result_type != argument.value_type:
                    raise CompileError(
                        f"calls[{position}].arguments.{name}: {result_type} result "
                        f"cannot supply {argument.value_type} argument"
                    )
                depends_on.add(producer_id)
                arguments[name] = {
                    "kind": "result",
                    "result": {
                        "node": producer_id,
                        "field": value["ref"]["field"],
                        "value_type": result_type,
                    },
                }
            else:
                arguments[name] = _literal(value)

        for name, value in capability.runtime_defaults.items():
            arguments[name] = _literal(value)

        condition = None
        if "when" in call:
            raw_condition = call["when"]
            producer_id, result_type = _producer_result(
                calls,
                catalog,
                current_position=position,
                reference=raw_condition["left"],
                location=f"calls[{position}].when.left",
            )
            producer_position = raw_condition["left"]["call"]
            if "when" in calls[producer_position - 1]:
                raise CompileError(
                    f"calls[{position}].when.left: condition producer must be unconditional"
                )
            right_type = _scalar_type(raw_condition["right"])
            if result_type != right_type:
                raise CompileError(
                    f"calls[{position}].when.right: {right_type} literal cannot compare "
                    f"with {result_type} result"
                )
            if raw_condition["op"] in _ORDERING_OPERATORS and result_type != "integer":
                raise CompileError(
                    f"calls[{position}].when.op: ordering requires integer operands"
                )
            depends_on.add(producer_id)
            condition = {
                "left": {
                    "node": producer_id,
                    "field": raw_condition["left"]["field"],
                    "value_type": result_type,
                },
                "op": raw_condition["op"],
                "right": _literal(raw_condition["right"]),
            }

        node = {
            "id": node_id,
            "capability": capability.name,
            "arguments": arguments,
            "condition": condition,
            "depends_on": sorted(depends_on, key=lambda item: int(item[1:])),
        }
        nodes.append(node)
        if capability.results:
            result_nodes.append(node_id)

    plan = {
        "profile": "open_kinly_plan_v1",
        "catalog_fingerprint": catalog_fingerprint(catalog),
        "schema_fingerprint": fingerprint(schema),
        "nodes": nodes,
        "result_nodes": result_nodes,
    }
    plan["plan_hash"] = fingerprint(plan)
    return plan
