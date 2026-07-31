"""Unit tests for the WaveAnalyzer 1500S driver.

The HTTP layer (`requests.Session`) is mocked out, so these run without an
instrument on the network.
"""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from wave_analyser import ScanData, WaveAnalyzer1500S


@pytest.fixture
def instrument():
    """A WaveAnalyzer1500S with its HTTP session mocked out."""
    with patch("wave_analyser.driver.requests.Session") as mock_session_cls:
        wa = WaveAnalyzer1500S("169.254.3.8")
        wa.open()
        wa._mock_session = mock_session_cls.return_value
        yield wa
        wa.close()


def _json_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _binary_response(content: bytes):
    resp = MagicMock()
    resp.content = content
    return resp


def test_session_property_raises_when_not_open():
    wa = WaveAnalyzer1500S("169.254.3.8")
    with pytest.raises(RuntimeError, match="not open"):
        _ = wa.session


def test_context_manager_opens_and_closes():
    with patch("wave_analyser.driver.requests.Session") as mock_session_cls:
        with WaveAnalyzer1500S("169.254.3.8") as wa:
            assert wa.session is mock_session_cls.return_value
        mock_session_cls.return_value.close.assert_called_once()


def test_get_info_hits_correct_url(instrument):
    instrument._mock_session.get.return_value = _json_response({"model": "WA1500S"})
    assert instrument.get_info() == {"model": "WA1500S"}
    instrument._mock_session.get.assert_called_once_with(
        "http://169.254.3.8/wanl/info", timeout=5.0
    )


def test_set_scan_builds_integer_path(instrument):
    instrument._mock_session.get.return_value = _json_response({"rc": 0})
    assert instrument.set_scan(193_700_000, 1_000_000, "HighSens") == {"rc": 0}
    url = instrument._mock_session.get.call_args[0][0]
    assert url == "http://169.254.3.8/wanl/scan/193700000/1000000/HighSens"


def test_set_scan_rejects_unknown_tag(instrument):
    with pytest.raises(ValueError, match="tag must be one of"):
        instrument.set_scan(193_700_000, 1_000_000, "Turbo")


@pytest.mark.parametrize(
    ("port", "coarse", "tag"),
    [
        ("Normal", True, "Normal"),
        ("Normal", False, "Normal20MHz"),
        ("HighSens", True, "HighSens"),
        ("HighSens", False, "HighSens20MHz"),
    ],
)
def test_scan_full_tag_and_span(instrument, port, coarse, tag):
    instrument._mock_session.get.return_value = _json_response({"rc": 0})
    instrument.scan_full(port=port, coarse=coarse)
    url = instrument._mock_session.get.call_args[0][0]
    assert url.endswith(f"/wanl/scan/193700000/-1/{tag}")


def test_scan_full_rejects_bad_port(instrument):
    with pytest.raises(ValueError, match="port must be"):
        instrument.scan_full(port="Ultra")


def test_wait_for_scan_returns_new_scanid(instrument):
    instrument._mock_session.get.side_effect = [
        _json_response({"scanid": 41}),  # baseline
        _json_response({"scanid": 41}),  # unchanged
        _json_response({"scanid": 42}),  # advanced
    ]
    assert instrument.wait_for_scan(poll_interval=0) == 42


def test_wait_for_scan_times_out(instrument):
    instrument._mock_session.get.return_value = _json_response({"scanid": 41})
    with pytest.raises(TimeoutError, match="no new scan completed"):
        instrument.wait_for_scan(timeout=0.05, poll_interval=0)


def test_get_data_scales_milli_dbm(instrument):
    instrument._mock_session.get.return_value = _json_response(
        {
            "id": 7,
            "data": [
                [191_000_000, -12_345, -15_000, -16_000, 0],
                [191_000_100, -10_000, -13_000, -14_000, 1],
            ],
        }
    )
    scan = instrument.get_data()

    assert isinstance(scan, ScanData)
    assert scan.scan_id == 7
    np.testing.assert_allclose(scan.freq_mhz, [191_000_000, 191_000_100])
    np.testing.assert_allclose(scan.power_dbm, [-12.345, -10.0])
    np.testing.assert_allclose(scan.power_x_dbm, [-15.0, -13.0])
    np.testing.assert_allclose(scan.power_y_dbm, [-16.0, -14.0])
    assert scan.trigger_flag is None


def test_get_data_triggerin_adds_param_and_flags(instrument):
    instrument._mock_session.get.return_value = _json_response(
        {"id": 7, "data": [[191_000_000, -12_345, -15_000, -16_000, 1]]}
    )
    scan = instrument.get_data(triggerin=True)

    assert instrument._mock_session.get.call_args.kwargs["params"] == {"triggerin": "on"}
    np.testing.assert_array_equal(scan.trigger_flag, [1])


def test_get_linear_data_parses_binary_records(instrument):
    header = b"{}".ljust(1000, b"\x00")
    records = [
        (191_000_000, 100, 60, 40, 0),
        (191_000_100, 200, 120, 80, 1),
    ]
    body = b"".join(struct.pack("<5i", *r) for r in records)
    instrument._mock_session.get.return_value = _binary_response(header + body)

    scan = instrument.get_linear_data()

    np.testing.assert_allclose(scan.freq_mhz, [191_000_000, 191_000_100])
    np.testing.assert_allclose(scan.power_dbm, [100, 200])
    np.testing.assert_allclose(scan.power_x_dbm, [60, 120])
    np.testing.assert_allclose(scan.power_y_dbm, [40, 80])
    assert scan.trigger_flag is None


def test_get_linear_data_ignores_trailing_partial_record(instrument):
    header = b"{}".ljust(1000, b"\x00")
    body = struct.pack("<5i", 191_000_000, 100, 60, 40, 0) + b"\x01\x02\x03"
    instrument._mock_session.get.return_value = _binary_response(header + body)

    scan = instrument.get_linear_data()
    assert scan.freq_mhz.size == 1


def test_http_error_propagates(instrument):
    resp = MagicMock()
    resp.raise_for_status.side_effect = RuntimeError("500 Server Error")
    instrument._mock_session.get.return_value = resp
    with pytest.raises(RuntimeError, match="500 Server Error"):
        instrument.get_info()


@pytest.mark.hw
def test_real_instrument_smoke():
    """Smoke test against a physical unit; run with `pytest --hw`."""
    import os

    ip = os.environ.get("WAVEANALYSER_IP", "169.254.3.8")
    with WaveAnalyzer1500S(ip) as wa:
        info = wa.get_info()
        assert info
        assert wa.set_scan(193_700_000, 1_000_000).get("rc") == 0
        wa.wait_for_scan()
        scan = wa.get_data()
        assert scan.freq_mhz.size == scan.power_dbm.size > 0
