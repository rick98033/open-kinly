"""Deterministic graph execution with explicit outcomes for every node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


class Dispatcher(Protocol):
    def __call__(self, capability: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


Authorizer = Callable[[str, dict[str, Any]], bool]


def deny_all(_capability: str, _arguments: dict[str, Any]) -> bool:
    """The safe default: a model-authored program carries no authority."""

    return False


def _materialize(value: dict[str, Any], results: dict[str, dict[str, Any]]) -> Any:
    if value["kind"] != "result":
        return value["value"]
    reference = value["result"]
    return results[reference["node"]][reference["field"]]


def _compare(left: Any, operator: str, right: Any) -> bool:
    return {
        "==": lambda: left == right,
        "!=": lambda: left != right,
        "<": lambda: left < right,
        "<=": lambda: left <= right,
        ">": lambda: left > right,
        ">=": lambda: left >= right,
    }[operator]()


def execute(
    plan: dict[str, Any],
    *,
    dispatch: Dispatcher,
    authorize: Authorizer = deny_all,
) -> dict[str, Any]:
    """Execute a compiled plan in dependency order.

    A real phone integration supplies both callbacks. Authorization is checked
    immediately before every dispatch; the model's inert proposal is never
    treated as authority.
    """

    if "unsupported" in plan:
        return {"status": "unsupported", "nodes": []}

    states: dict[str, str] = {}
    results: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    for node in plan["nodes"]:
        node_id = node["id"]
        capability = node["capability"]
        if any(states.get(dependency) != "completed" for dependency in node["depends_on"]):
            states[node_id] = "dependency_failed"
            outcomes.append(
                {"node": node_id, "capability": capability, "state": "dependency_failed"}
            )
            continue

        condition = node["condition"]
        if condition is not None:
            left = results[condition["left"]["node"]][condition["left"]["field"]]
            right = condition["right"]["value"]
            if not _compare(left, condition["op"], right):
                states[node_id] = "skipped"
                outcomes.append(
                    {
                        "node": node_id,
                        "capability": capability,
                        "state": "skipped",
                        "reason": "condition_false",
                    }
                )
                continue

        arguments = {
            name: _materialize(value, results)
            for name, value in node["arguments"].items()
        }
        if not authorize(capability, arguments):
            states[node_id] = "denied"
            outcomes.append(
                {
                    "node": node_id,
                    "capability": capability,
                    "state": "denied",
                    "arguments": arguments,
                }
            )
            continue

        try:
            response = dispatch(capability, arguments)
        except Exception as error:  # the boundary turns dispatch faults into outcomes
            states[node_id] = "failed"
            outcomes.append(
                {
                    "node": node_id,
                    "capability": capability,
                    "state": "failed",
                    "arguments": arguments,
                    "error_code": type(error).__name__,
                }
            )
            continue
        if response.get("ok") is not True:
            states[node_id] = "failed"
            outcomes.append(
                {
                    "node": node_id,
                    "capability": capability,
                    "state": "failed",
                    "arguments": arguments,
                    "error_code": response.get("error_code", "UNKNOWN"),
                }
            )
            continue

        payload = {name: value for name, value in response.items() if name != "ok"}
        states[node_id] = "completed"
        results[node_id] = payload
        outcomes.append(
            {
                "node": node_id,
                "capability": capability,
                "state": "completed",
                "arguments": arguments,
                "result": payload,
            }
        )

    completed = sum(state == "completed" for state in states.values())
    failures = {"failed", "denied", "dependency_failed"}
    status = (
        "completed"
        if not any(state in failures for state in states.values())
        else "failed"
        if completed == 0
        else "partial"
    )
    return {"status": status, "nodes": outcomes}


def allow_toy_capabilities(capability: str, _arguments: dict[str, Any]) -> bool:
    return capability in {
        "device_battery.get_status",
        "media_volume.set",
        "text_size.set",
        "flashlight.on",
        "brightness.decrease",
    }


@dataclass
class ToyPhone:
    """An in-memory adapter. It does not control a device."""

    battery_percent: int = 80
    charging: bool = False
    media_volume: int = 20
    text_size: int = 50
    flashlight: bool = False
    brightness: int = 128

    def dispatch(self, capability: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if capability == "device_battery.get_status":
            return {
                "ok": True,
                "battery_percent": self.battery_percent,
                "charging": self.charging,
            }
        if capability == "media_volume.set":
            before = self.media_volume
            self.media_volume = arguments["level"]
            return {"ok": True, "pre_state": before, "post_state": self.media_volume}
        if capability == "text_size.set":
            before = self.text_size
            self.text_size = arguments["level"]
            return {"ok": True, "pre_state": before, "post_state": self.text_size}
        if capability == "flashlight.on":
            before = self.flashlight
            self.flashlight = True
            return {"ok": True, "pre_state": before, "post_state": self.flashlight}
        if capability == "brightness.decrease":
            before = self.brightness
            self.brightness = max(0, before - arguments["amount"])
            return {"ok": True, "pre_state": before, "post_state": self.brightness}
        return {"ok": False, "error_code": "UNSUPPORTED_CAPABILITY"}
