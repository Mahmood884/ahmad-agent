import json

import pytest

from ahmad.tools.instrumentation import CanReadTool, CalibrateSensorTool, ModbusReadTool


def test_can_read_returns_bounded_frames_without_transmitting():
    class Message:
        arbitration_id = 0x123
        is_extended_id = False
        is_remote_frame = False
        is_error_frame = False
        data = b"\x01\x02"
        timestamp = 12.5

    class Bus:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def recv(self, timeout):
            self.calls += 1
            return Message() if self.calls == 1 else None

    buses = []

    class CanModule:
        @staticmethod
        def Bus(**kwargs):
            bus = Bus(**kwargs)
            buses.append(bus)
            return bus

    result = CanReadTool(can_module=CanModule).run(
        'can_read:{"channel":"can0","max_frames":3,"timeout":1}'
    )

    assert result.success
    data = json.loads(result.output)
    assert data["frames"][0]["arbitration_id"] == 0x123
    assert data["frames"][0]["data_hex"] == "0102"
    assert buses[0].kwargs == {"interface": "socketcan", "channel": "can0"}
    assert not hasattr(buses[0], "send")


def test_can_read_rejects_call_within_minimum_interval(monkeypatch):
    class Bus:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @staticmethod
        def recv(timeout):
            return None

    class CanModule:
        calls = 0

        @classmethod
        def Bus(cls, **kwargs):
            cls.calls += 1
            return Bus()

    timestamps = iter((1_000_000_000, 1_500_000_000))
    monkeypatch.setattr(
        "ahmad.tools.instrumentation.time.monotonic_ns", lambda: next(timestamps)
    )
    tool = CanReadTool(can_module=CanModule)
    action = 'can_read:{"channel":"can0","timeout":1}'

    first = tool.run(action)
    second = tool.run(action)

    assert first.success
    assert not second.success
    assert second.output.startswith("RATE_LIMITED:")
    assert CanModule.calls == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"channel": "vcan0"},
        {"channel": "can0", "interface": "socketcan-isotp"},
        {"channel": "can0", "max_frames": 101},
        {"channel": "can0", "timeout": 11},
    ],
)
def test_can_read_validates_interface_and_bounds_before_opening_bus(payload):
    class CanModule:
        @staticmethod
        def Bus(**kwargs):
            raise AssertionError("invalid settings must not open a bus")

    result = CanReadTool(can_module=CanModule).run(f"can_read:{json.dumps(payload)}")

    assert not result.success
    assert result.output.startswith("ERROR:")


def test_modbus_read_calls_only_holding_register_read():
    calls = []

    class Response:
        registers = [101, 202]

        @staticmethod
        def isError():
            return False

    class Client:
        def __init__(self, host, *, port, timeout):
            calls.append(("init", host, port, timeout))

        @staticmethod
        def connect():
            return True

        @staticmethod
        def read_holding_registers(*, address, count, device_id):
            calls.append(("read", address, count, device_id))
            return Response()

        @staticmethod
        def close():
            calls.append(("close",))

    result = ModbusReadTool(client_factory=Client).run(
        'modbus_read:{"host":"192.168.1.20","unit_id":7,"address":100,"count":2}'
    )

    assert result.success
    assert json.loads(result.output)["registers"] == [101, 202]
    assert ("read", 100, 2, 7) in calls
    assert calls[-1] == ("close",)
    assert not any("write" in str(call) for call in calls)


@pytest.mark.parametrize("host", ["example.com", "8.8.8.8", "1.1.1.1"])
def test_modbus_read_rejects_hostnames_and_public_addresses(host):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("must not open a network connection")

    result = ModbusReadTool(client_factory=unexpected_client).run(
        f'modbus_read:{json.dumps({"host":host,"unit_id":1,"address":0})}'
    )

    assert not result.success
    assert "private or loopback IP" in result.output


def test_modbus_read_supports_legacy_slave_parameter():
    class Response:
        registers = [9]

        @staticmethod
        def isError():
            return False

    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def connect():
            return True

        @staticmethod
        def read_holding_registers(*, address, count, slave):
            calls.append(slave)
            return Response()

        @staticmethod
        def close():
            pass

    result = ModbusReadTool(client_factory=Client).run(
        'modbus_read:{"host":"127.0.0.1","unit_id":3,"address":0}'
    )

    assert result.success
    assert calls == [3]


def test_calibrate_sensor_fits_linear_curve_with_scipy():
    result = CalibrateSensorTool().run(
        'calibrate_sensor:{"x":[0,1,2,3],"y":[2,5,8,11],"model":"linear"}'
    )

    assert result.success
    fit = json.loads(result.output)
    assert fit["coefficients_ascending_order"] == pytest.approx([2, 3], abs=1e-6)
    assert fit["rmse"] == pytest.approx(0, abs=1e-6)
    assert fit["r_squared"] == pytest.approx(1)
    assert "no sensor was read or modified" in fit["note"]


def test_calibrate_sensor_fits_quadratic_curve():
    result = CalibrateSensorTool().run(
        'calibrate_sensor:{"x":[-2,-1,0,1,2],"y":[9,2,1,6,17],"model":"quadratic"}'
    )

    assert result.success
    assert json.loads(result.output)["coefficients_ascending_order"] == pytest.approx(
        [1, 2, 3], abs=1e-6
    )


def test_calibrate_sensor_rejects_insufficient_distinct_points():
    result = CalibrateSensorTool().run(
        'calibrate_sensor:{"x":[1,1,1],"y":[1,2,3],"model":"quadratic"}'
    )

    assert not result.success
    assert "distinct x values" in result.output
