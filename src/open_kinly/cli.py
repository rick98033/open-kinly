"""Command-line entry point for model authoring, compilation, and toy execution."""

from __future__ import annotations

import argparse
from importlib.resources import as_file, files
import json
import os
from pathlib import Path
from typing import Any

from .catalog import load_catalog
from .compiler import compile_program, parse_model_output
from .language import build_schema, build_system_prompt, fingerprint
from .model import author_once
from .runtime import ToyPhone, allow_toy_capabilities, execute


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("program must be one JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile a phone-use request into a typed action graph."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--utterance", help="send one request to a structured-output model")
    source.add_argument("--program", type=Path, help="compile an already-authored JSON program")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL"))
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--execute-toy", action="store_true")
    parser.add_argument("--battery", type=int, default=80)
    parser.add_argument("--show-prompt", action="store_true")
    parser.add_argument("--show-schema", action="store_true")
    arguments = parser.parse_args()

    catalog_resource = files("open_kinly").joinpath("toy_catalog.yaml")
    if arguments.catalog is not None:
        catalog = load_catalog(arguments.catalog)
    else:
        with as_file(catalog_resource) as catalog_path:
            catalog = load_catalog(catalog_path)
    prompt = build_system_prompt(catalog)
    schema = build_schema(catalog)

    if arguments.show_prompt:
        print(prompt, end="")
        if not arguments.show_schema and arguments.utterance is None and arguments.program is None:
            return 0
    if arguments.show_schema:
        print(json.dumps(schema, indent=2, sort_keys=True))
        if arguments.utterance is None and arguments.program is None:
            return 0
    if arguments.program is None and arguments.utterance is None:
        parser.error("provide --program or --utterance")

    planning: dict[str, Any]
    if arguments.program is not None:
        program = _read_json(arguments.program)
        planning = {"model_calls": 0, "source": "replay"}
    else:
        if not arguments.base_url or not arguments.model:
            parser.error("--utterance requires --base-url and --model")
        completion = author_once(
            base_url=arguments.base_url,
            model=arguments.model,
            system_prompt=prompt,
            utterance=arguments.utterance,
            schema=schema,
            api_key=arguments.api_key,
        )
        program = parse_model_output(completion["content"])
        planning = {
            "model_calls": 1,
            "retries": 0,
            "model": arguments.model,
            "latency_ms": completion["latency_ms"],
            "usage": completion["usage"],
            "finish_reason": completion["finish_reason"],
        }

    plan = compile_program(program, catalog)
    output: dict[str, Any] = {
        "planning": planning,
        "language": {
            "prompt_sha256": fingerprint(prompt),
            "schema_sha256": fingerprint(schema),
        },
        "program": program,
        "plan": plan,
    }
    if arguments.execute_toy:
        if not 0 <= arguments.battery <= 100:
            parser.error("--battery must be from 0 through 100")
        phone = ToyPhone(battery_percent=arguments.battery)
        output["outcome"] = execute(
            plan,
            dispatch=phone.dispatch,
            authorize=allow_toy_capabilities,
        )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0
