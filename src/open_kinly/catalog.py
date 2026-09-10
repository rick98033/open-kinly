"""Load the small, declarative assistant-facing capability catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping, TypeAlias

import yaml


ValueType: TypeAlias = Literal["string", "integer", "boolean"]
Scalar: TypeAlias = str | int | bool
_VALUE_TYPES = frozenset({"string", "integer", "boolean"})


@dataclass(frozen=True)
class ArgumentSpec:
    name: str
    value_type: ValueType
    required: bool
    description: str = ""
    minimum: int | None = None
    maximum: int | None = None
    enum: tuple[Scalar, ...] | None = None


@dataclass(frozen=True)
class ResultSpec:
    name: str
    value_type: ValueType
    description: str = ""


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    description: str
    arguments: tuple[ArgumentSpec, ...]
    results: tuple[ResultSpec, ...]
    runtime_defaults: Mapping[str, Scalar]

    def argument(self, name: str) -> ArgumentSpec | None:
        return next((item for item in self.arguments if item.name == name), None)

    def result(self, name: str) -> ResultSpec | None:
        return next((item for item in self.results if item.name == name), None)


@dataclass(frozen=True)
class Catalog:
    capabilities: tuple[CapabilitySpec, ...]

    def capability(self, name: str) -> CapabilitySpec | None:
        return next((item for item in self.capabilities if item.name == name), None)


def _mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    return value


def _value_type(value: Any, location: str) -> ValueType:
    if value not in _VALUE_TYPES:
        raise ValueError(f"{location} must be one of {sorted(_VALUE_TYPES)}")
    return value


def load_catalog(path: str | Path) -> Catalog:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    root = _mapping(document, "catalog")
    raw_capabilities = root.get("capabilities")
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise ValueError("catalog.capabilities must be a non-empty list")

    capabilities: list[CapabilitySpec] = []
    observed_names: set[str] = set()
    for index, raw in enumerate(raw_capabilities, start=1):
        item = _mapping(raw, f"capabilities[{index}]")
        name = item.get("name")
        description = item.get("description")
        if not isinstance(name, str) or not name:
            raise ValueError(f"capabilities[{index}].name must be non-empty text")
        if name in observed_names:
            raise ValueError(f"duplicate capability {name!r}")
        observed_names.add(name)
        if not isinstance(description, str) or not description:
            raise ValueError(f"capabilities[{index}].description must be non-empty text")

        arguments: list[ArgumentSpec] = []
        for argument_name, raw_argument in _mapping(
            item.get("arguments", {}), f"{name}.arguments"
        ).items():
            argument = _mapping(raw_argument, f"{name}.arguments.{argument_name}")
            enum = argument.get("enum")
            if enum is not None and not isinstance(enum, list):
                raise ValueError(f"{name}.arguments.{argument_name}.enum must be a list")
            arguments.append(
                ArgumentSpec(
                    name=argument_name,
                    value_type=_value_type(
                        argument.get("type"), f"{name}.arguments.{argument_name}.type"
                    ),
                    required=bool(argument.get("required", False)),
                    description=str(argument.get("description", "")),
                    minimum=argument.get("minimum"),
                    maximum=argument.get("maximum"),
                    enum=tuple(enum) if enum is not None else None,
                )
            )

        results: list[ResultSpec] = []
        for result_name, raw_result in _mapping(
            item.get("results", {}), f"{name}.results"
        ).items():
            result = _mapping(raw_result, f"{name}.results.{result_name}")
            results.append(
                ResultSpec(
                    name=result_name,
                    value_type=_value_type(
                        result.get("type"), f"{name}.results.{result_name}.type"
                    ),
                    description=str(result.get("description", "")),
                )
            )

        defaults = MappingProxyType(
            dict(_mapping(item.get("runtime_defaults", {}), f"{name}.runtime_defaults"))
        )
        overlap = defaults.keys() & {argument.name for argument in arguments}
        if overlap:
            raise ValueError(f"{name} duplicates model and runtime arguments: {sorted(overlap)}")
        capabilities.append(
            CapabilitySpec(
                name=name,
                description=description,
                arguments=tuple(arguments),
                results=tuple(results),
                runtime_defaults=defaults,
            )
        )
    return Catalog(tuple(capabilities))
