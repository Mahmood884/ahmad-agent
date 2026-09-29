"""Read-only CAN/Modbus acquisition and offline sensor-curve fitting tools."""
from __future__ import annotations

import ipaddress
import inspect
import json
import math
import re
import threading
import time
from typing import Callable

from ahmad.execution.mock_tool import ToolResult


def _payload(action: str, name: str) -> dict:
    prefix = f"{name}:"
    if not action.startswith(prefix):
        raise ValueError(f"Action must start with '{prefix}'")
    try:
        value = json.loads(action[len(prefix):])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Action payload must be valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("Action payload must be a JSON object")
    return value


class CanReadTool:
    """Read a bounded number of frames from a Linux SocketCAN interface."""

    name = "can_read"
    version = "1.0"
    MAX_FRAMES = 100
    MAX_TIMEOUT_SECONDS = 10.0
    MIN_INTERVAL_NS = 1_000_000_000

    def __init__(self, can_module=None) -> None:
        self._can_module = can_module
        self._rate_limit_lock = threading.Lock()
        self._last_request_ns: int | None = None

    def run(self, action: str) -> ToolResult:
        try:
            payload = _payload(action, self.name)
            interface = payload.get("interface", "socketcan")
            channel = payload.get("channel", "can0")
            if interface != "socketcan":
                raise ValueError("Only the read-only SocketCAN interface is supported")
            if not isinstance(channel, str) or not re.fullmatch(r"can[0-9]+", channel):
                raise ValueError("channel must be a Linux SocketCAN interface such as can0")
            max_frames = payload.get("max_frames", 10)
            if not isinstance(max_frames, int) or isinstance(max_frames, bool):
                raise ValueError("max_frames must be an integer")
            if not 1 <= max_frames <= self.MAX_FRAMES:
                raise ValueError(f"max_frames must be between 1 and {self.MAX_FRAMES}")
            timeout = payload.get("timeout", 2.0)
            if (
                not isinstance(timeout, (int, float))
                or isinstance(timeout, bool)
                or not math.isfinite(timeout)
                or not 0 < timeout <= self.MAX_TIMEOUT_SECONDS
            ):
                raise ValueError(
                    f"timeout must be greater than 0 and at most {self.MAX_TIMEOUT_SECONDS} seconds"
                )
            now_ns = time.monotonic_ns()
            with self._rate_limit_lock:
                if (
                    self._last_request_ns is not None
                    and now_ns - self._last_request_ns < self.MIN_INTERVAL_NS
                ):
                    wait_ms = (
                        self.MIN_INTERVAL_NS - (now_ns - self._last_request_ns) + 999_999
                    ) // 1_000_000
                    return ToolResult(
                        False, self.name,
                        f"RATE_LIMITED: wait at least {wait_ms} ms between CAN reads",
                        None,
                    )
                self._last_request_ns = now_ns
            can_module = self._can_module
            if can_module is None:
                try:
                    import can as can_module
                except ImportError:
                    return ToolResult(
                        False, self.name,
                        "ERROR: python-can is missing; install the 'industrial' optional dependencies.",
                        None,
                    )
            can_error = getattr(can_module, "CanError", OSError)
            frames = []
            deadline = time.monotonic() + float(timeout)
            with can_module.Bus(interface=interface, channel=channel) as bus:
                while len(frames) < max_frames:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    message = bus.recv(timeout=remaining)
                    if message is None:
                        break
                    frames.append(
                        {
                            "arbitration_id": int(message.arbitration_id),
                            "is_extended_id": bool(message.is_extended_id),
                            "is_remote_frame": bool(message.is_remote_frame),
                            "is_error_frame": bool(message.is_error_frame),
                            "data_hex": bytes(message.data).hex(),
                            "timestamp": float(message.timestamp),
                        }
                    )
            return ToolResult(
                True,
                self.name,
                json.dumps(
                    {"interface": interface, "channel": channel, "frames": frames},
                    indent=2,
                ),
                None,
            )
        except ValueError as exc:
            return ToolResult(False, self.name, f"ERROR: {exc}", None)
        except (OSError, can_error) as exc:
            return ToolResult(False, self.name, f"CAN_READ_FAILED: {exc}", None)


class ModbusReadTool:
    """Read holding registers from an explicitly addressed private IPv4/IPv6 device."""

    name = "modbus_read"
    version = "1.0"
    MAX_REGISTERS = 125
    CONNECT_TIMEOUT_SECONDS = 3.0

    def __init__(self, client_factory: Callable | None = None) -> None:
        self._client_factory = client_factory

    def run(self, action: str) -> ToolResult:
        client = None
        modbus_exception = OSError
        try:
            payload = _payload(action, self.name)
            host = payload.get("host")
            if not isinstance(host, str):
                raise ValueError("host must be a private or loopback IP address")
            try:
                address_ip = ipaddress.ip_address(host)
            except ValueError as exc:
                raise ValueError("host must be a private or loopback IP address, not a hostname") from exc
            if not (address_ip.is_private or address_ip.is_loopback):
                raise ValueError("host must be a private or loopback IP address")
            port = payload.get("port", 502)
            if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
                raise ValueError("port must be an integer between 1 and 65535")
            unit_id = payload.get("unit_id")
            if not isinstance(unit_id, int) or isinstance(unit_id, bool) or not 1 <= unit_id <= 247:
                raise ValueError("unit_id must be an integer between 1 and 247")
            address = payload.get("address")
            if not isinstance(address, int) or isinstance(address, bool) or not 0 <= address <= 65535:
                raise ValueError("address must be an integer between 0 and 65535")
            count = payload.get("count", 1)
            if not isinstance(count, int) or isinstance(count, bool):
                raise ValueError("count must be an integer")
            if not 1 <= count <= self.MAX_REGISTERS:
                raise ValueError(f"count must be between 1 and {self.MAX_REGISTERS}")
            if address + count > 65536:
                raise ValueError("address and count exceed the Modbus register address range")

            factory = self._client_factory
            if factory is None:
                try:
                    from pymodbus.client import ModbusTcpClient
                    from pymodbus.exceptions import ModbusException
                except ImportError:
                    return ToolResult(
                        False, self.name,
                        "ERROR: pymodbus is missing; install the 'industrial' optional dependencies.",
                        None,
                    )
                factory = ModbusTcpClient
                modbus_exception = ModbusException
                modbus_exception = ModbusException
            client = factory(host, port=port, timeout=self.CONNECT_TIMEOUT_SECONDS)
            if not client.connect():
                return ToolResult(
                    False, self.name, f"MODBUS_READ_FAILED: could not connect to {host}:{port}", None
                )
            method = client.read_holding_registers
            parameters = inspect.signature(method).parameters
            if "device_id" in parameters:
                unit_argument = {"device_id": unit_id}
            elif "slave" in parameters:
                unit_argument = {"slave": unit_id}
            elif "unit" in parameters:
                unit_argument = {"unit": unit_id}
            else:
                raise RuntimeError("Unsupported pymodbus API: no unit identifier parameter found")
            response = method(address=address, count=count, **unit_argument)
            if response.isError():
                return ToolResult(
                    False, self.name,
                    f"MODBUS_READ_FAILED: device returned {response}",
                    None,
                )
            registers = [int(register) for register in response.registers]
            return ToolResult(
                True,
                self.name,
                json.dumps(
                    {
                        "host": host,
                        "port": port,
                        "unit_id": unit_id,
                        "address": address,
                        "registers": registers,
                    },
                    indent=2,
                ),
                None,
            )
        except ValueError as exc:
            return ToolResult(False, self.name, f"ERROR: {exc}", None)
        except (OSError, modbus_exception) as exc:
            return ToolResult(False, self.name, f"MODBUS_READ_FAILED: {exc}", None)
        finally:
            if client is not None:
                client.close()


class CalibrateSensorTool:
    """Fit an offline calibration curve; never writes to a physical sensor."""

    name = "calibrate_sensor"
    version = "1.0"
    MAX_POINTS = 100

    def run(self, action: str) -> ToolResult:
        try:
            payload = _payload(action, self.name)
            x_values = payload.get("x")
            y_values = payload.get("y")
            model = payload.get("model", "linear")
            degree_by_model = {"linear": 1, "quadratic": 2}
            if not isinstance(model, str) or model not in degree_by_model:
                raise ValueError("model must be 'linear' or 'quadratic'")
            if not isinstance(x_values, list) or not isinstance(y_values, list):
                raise ValueError("x and y must be numeric arrays")
            if len(x_values) != len(y_values) or not 2 <= len(x_values) <= self.MAX_POINTS:
                raise ValueError(f"x and y must have the same length from 2 to {self.MAX_POINTS}")
            degree = degree_by_model[model]
            if len(x_values) < degree + 1:
                raise ValueError(f"{model} calibration requires at least {degree + 1} points")
            numeric_values = []
            for value in (*x_values, *y_values):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("x and y values must be finite numbers")
                try:
                    numeric_value = float(value)
                except OverflowError as exc:
                    raise ValueError("x and y values must be finite numbers") from exc
                if not math.isfinite(numeric_value):
                    raise ValueError("x and y values must be finite numbers")
                numeric_values.append(numeric_value)
            if len(set(x_values)) < degree + 1:
                raise ValueError(f"{model} calibration requires at least {degree + 1} distinct x values")
            try:
                import numpy as np
                from scipy.optimize import curve_fit
            except ImportError:
                return ToolResult(
                    False, self.name,
                    "ERROR: scipy is missing; install the 'industrial' optional dependencies.",
                    None,
                )

            x_data = np.asarray(numeric_values[:len(x_values)], dtype=float)
            y_data = np.asarray(numeric_values[len(x_values):], dtype=float)

            def polynomial(x, *coefficients):
                return sum(coefficient * np.power(x, index) for index, coefficient in enumerate(coefficients))

            coefficients, _ = curve_fit(
                polynomial,
                x_data,
                y_data,
                p0=np.zeros(degree + 1),
                maxfev=10_000,
            )
            predicted = polynomial(x_data, *coefficients)
            residuals = y_data - predicted
            rmse = float(np.sqrt(np.mean(np.square(residuals))))
            total_variation = float(np.sum(np.square(y_data - np.mean(y_data))))
            r_squared = (
                None
                if total_variation == 0
                else float(1.0 - np.sum(np.square(residuals)) / total_variation)
            )
            fit = {
                "model": model,
                "coefficients_ascending_order": [float(value) for value in coefficients],
                "rmse": rmse,
                "r_squared": r_squared,
                "points_used": len(x_values),
                "note": "Computed from supplied points only; no sensor was read or modified.",
            }
            fit_values = fit["coefficients_ascending_order"] + [rmse]
            if r_squared is not None:
                fit_values.append(r_squared)
            if not all(math.isfinite(value) for value in fit_values):
                raise ValueError("fit produced non-finite coefficients")
            return ToolResult(True, self.name, json.dumps(fit, indent=2), None)
        except ValueError as exc:
            return ToolResult(False, self.name, f"ERROR: {exc}", None)
        except RuntimeError as exc:
            return ToolResult(False, self.name, f"FIT_FAILED: {exc}", None)
