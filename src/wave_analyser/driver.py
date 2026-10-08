"""Driver for the II-VI / Finisar WaveAnalyzer(TM) 1500S optical spectrum analyser.

Reference: WaveAnalyzer 1500S User Manual, Part Number 1233834, Rev. G00,
Section 4.2 (WaveAnalyzer 1500S Web API).

The instrument exposes a RESTful HTTP API directly on the unit (no SCPI/VISA
layer), so this driver talks HTTP via `requests` rather than pyvisa/pyserial.

    http://<ip>/wanl/scan/<center>/<span>[/<tag>]   -- configure a scan
    http://<ip>/wanl/data/<format>[?triggerin=on]    -- fetch dBm-scale data
    http://<ip>/wanl/lineardata/bin[?triggerin=on]   -- fetch linear (mW) data
    http://<ip>/wanl/info                            -- device info
    http://<ip>/wanl/scan/info                       -- current scan config
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

import numpy as np
import requests

#: Input port / step-size tags accepted by the scan endpoint.
VALID_TAGS = {
    "Normal",
    "HighSens",
    "Normal20MHz",
    "HighSens20MHz",
}

#: Centre frequency of the instrument's full operating range, in MHz.
FULL_SCAN_CENTER_MHZ = 193_700_000


@dataclass
class ScanData:
    """Parsed measurement trace. Power values are in dBm, frequency in MHz."""

    scan_id: int
    freq_mhz: np.ndarray
    power_dbm: np.ndarray
    power_x_dbm: np.ndarray
    power_y_dbm: np.ndarray
    trigger_flag: np.ndarray | None = None


class WaveAnalyzer1500S:
    """Control a WaveAnalyzer 1500S over its onboard HTTP/REST API.

    Args:
        ip: IP address or mDNS hostname of the unit (e.g. "169.254.3.8" or
            "WA000001.local").
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, ip: str, timeout: float = 5.0) -> None:
        self.ip = ip
        self.timeout = timeout
        self._session: requests.Session | None = None

    def open(self) -> None:
        """Open the underlying HTTP session."""
        self._session = requests.Session()

    def close(self) -> None:
        """Close the underlying HTTP session, if one is open."""
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> "WaveAnalyzer1500S":
        self.open()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            raise RuntimeError("Connection not open — call open() or use 'with'.")
        return self._session

    def _get(self, path: str, **kwargs) -> requests.Response:
        url = f"http://{self.ip}{path}"
        resp = self.session.get(url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp

    def get_info(self) -> dict:
        """Retrieve factory info: model, serial number, firmware version, vendor."""
        return self._get("/wanl/info").json()

    def get_scan_info(self) -> dict:
        """Retrieve the configuration of the most recent scan."""
        return self._get("/wanl/scan/info").json()

    def set_scan(self, center_mhz: float, span_mhz: float, tag: str = "Normal") -> dict:
        """Configure the scan range.

        Args:
            center_mhz: Scan centre frequency in MHz.
            span_mhz: Scan span in MHz. Pass -1 for a full scan across the
                instrument's operating range.
            tag: Input port / step-size tag. One of VALID_TAGS.

        Returns:
            JSON response with a result code ("rc"): 0 = success.
        """
        if tag not in VALID_TAGS:
            raise ValueError(f"tag must be one of {VALID_TAGS}, got {tag!r}")
        path = f"/wanl/scan/{int(center_mhz)}/{int(span_mhz)}/{tag}"
        return self._get(path).json()

    def scan_full(self, port: str = "Normal", coarse: bool = True) -> dict:
        """Configure a full-range scan, matching the GUI's "Full" / "Full
        (Coarse)" modes (Section 4.2.1 table).

        Args:
            port: "Normal" or "HighSens" optical input.
            coarse: True for Full (Coarse) — 100 MHz step, faster.
                    False for Full — 20 MHz step, higher resolution.
        """
        if port not in ("Normal", "HighSens"):
            raise ValueError(f"port must be 'Normal' or 'HighSens', got {port!r}")
        tag = port if coarse else f"{port}20MHz"
        return self.set_scan(center_mhz=FULL_SCAN_CENTER_MHZ, span_mhz=-1, tag=tag)

    def wait_for_scan(self, timeout: float = 5.0, poll_interval: float = 0.1) -> int:
        """Block until a fresh scan completes after the most recent set_scan().

        The instrument scans continuously in the background at the rate set
        by its configured span (see Section 5.3 of the manual); set_scan()
        only configures the range and returns immediately, so a get_data()
        called straight after it can race an empty or stale trace. This
        polls scan/info's `scanid` counter until it advances.

        Returns:
            The new scan id once a fresh scan has completed.

        Raises:
            TimeoutError: if no new scan completes within `timeout` seconds.
        """
        baseline = self.get_scan_info()["scanid"]
        start = time.monotonic()
        while True:
            scanid = self.get_scan_info()["scanid"]
            if scanid >= 0 and scanid != baseline:
                return scanid
            if time.monotonic() - start > timeout:
                raise TimeoutError(
                    f"no new scan completed within {timeout}s (scanid stuck at {scanid})"
                )
            time.sleep(poll_interval)

    def get_data(self, triggerin: bool = False) -> ScanData:
        """Fetch the most recent measurement trace (dBm scale) as a ScanData.

        Args:
            triggerin: If True, also request the Trigger In flag column.
        """
        params = {"triggerin": "on"} if triggerin else None
        payload = self._get("/wanl/data/json", params=params).json()
        arr = np.array(payload["data"], dtype=np.int64)

        trigger_flag = arr[:, 4] if triggerin else None
        return ScanData(
            scan_id=payload["id"],
            freq_mhz=arr[:, 0].astype(float),
            power_dbm=arr[:, 1] / 1000.0,
            power_x_dbm=arr[:, 2] / 1000.0,
            power_y_dbm=arr[:, 3] / 1000.0,
            trigger_flag=trigger_flag,
        )

    def get_fresh_data(self, triggerin: bool = False, timeout: float = 5.0,
                       poll_interval: float = 0.1) -> ScanData:
        """Fetch a trace acquired entirely after the caller's last change.

        The instrument scans continuously, so when the laser, RF or scan
        settings change, a scan is usually already in progress. The first
        wait_for_scan() returns when that in-flight scan completes, but it
        began before the change and so may hold a mix of old and new
        conditions. The second wait_for_scan() returns only once a scan that
        started after the change has completed, which is what get_data()
        then reads.

        Args:
            triggerin: Passed through to get_data().
            timeout: Per-wait timeout passed to each wait_for_scan() call.
            poll_interval: Passed through to wait_for_scan().

        Returns:
            The same ScanData object get_data() returns.

        Raises:
            TimeoutError: if either wait does not see a new scan in time.
        """
        self.wait_for_scan(timeout=timeout, poll_interval=poll_interval)
        self.wait_for_scan(timeout=timeout, poll_interval=poll_interval)
        return self.get_data(triggerin=triggerin)

    def get_averaged_data(self, n_avg: int, timeout: float = 5.0,
                          poll_interval: float = 0.1) -> ScanData:
        """Average `n_avg` fresh scans point by point into a single trace.

        The instrument's Web API has no averaging setting (that lives in the
        GUI and the PC-side Analysis Server), so this averages in software.
        A first wait_for_scan() discards the scan in flight, as in
        get_fresh_data(); each trace is then read after its own
        wait_for_scan(), so no sweep is counted twice.

        Powers are averaged in linear units and converted back to dBm:
        averaging dBm values directly gives a geometric mean, which reads
        low on noise.

        Args:
            n_avg: Number of scans to average (>= 1).
            timeout: Per-wait timeout passed to each wait_for_scan() call.
            poll_interval: Passed through to wait_for_scan().

        Returns:
            A ScanData whose scan_id is that of the last scan used.

        Raises:
            ValueError: if n_avg < 1, or the frequency grid changes between
                scans (e.g. set_scan() was called mid-average).
            RuntimeError: if the same scan id is read twice.
            TimeoutError: if any wait does not see a new scan in time.
        """
        if n_avg < 1:
            raise ValueError(f"n_avg must be >= 1, got {n_avg}")

        self.wait_for_scan(timeout=timeout, poll_interval=poll_interval)
        scans: list[ScanData] = []
        for _ in range(n_avg):
            self.wait_for_scan(timeout=timeout, poll_interval=poll_interval)
            scan = self.get_data()
            if scans:
                if scan.scan_id == scans[-1].scan_id:
                    raise RuntimeError(f"scan {scan.scan_id} read twice")
                if not np.array_equal(scan.freq_mhz, scans[0].freq_mhz):
                    raise ValueError("frequency grid changed between scans")
            scans.append(scan)

        def linear_mean_dbm(field: str) -> np.ndarray:
            mw = np.stack([10 ** (getattr(s, field) / 10) for s in scans])
            return 10 * np.log10(mw.mean(axis=0))

        return ScanData(
            scan_id=scans[-1].scan_id,
            freq_mhz=scans[0].freq_mhz,
            power_dbm=linear_mean_dbm("power_dbm"),
            power_x_dbm=linear_mean_dbm("power_x_dbm"),
            power_y_dbm=linear_mean_dbm("power_y_dbm"),
        )

    def get_linear_data(self, triggerin: bool = False) -> ScanData:
        """Fetch the most recent measurement trace on a linear (mW) scale.

        Requires firmware >= 1.02. Binary response: 1000-byte JSON header
        (zero-padded) followed by 20-byte records of five little-endian
        int32 values: freq_mhz, power_mw, power_x_mw, power_y_mw, flag.

        Note: the manual does not state a fixed-point scale factor for the
        linear power fields (unlike the dBm endpoint's documented milli-dBm
        units). Raw integers are returned as-is in `power_dbm` etc. field
        names below for shape-compatibility; treat values as raw counts
        until verified against a real unit, and rescale as needed.
        """
        params = {"triggerin": "on"} if triggerin else None
        raw = self._get("/wanl/lineardata/bin", params=params).content
        body = raw[1000:]
        n_records = len(body) // 20
        records = np.array(
            struct.unpack(f"<{n_records * 5}i", body[: n_records * 20])
        ).reshape(n_records, 5)

        trigger_flag = records[:, 4] if triggerin else None
        return ScanData(
            scan_id=-1,
            freq_mhz=records[:, 0].astype(float),
            power_dbm=records[:, 1].astype(float),
            power_x_dbm=records[:, 2].astype(float),
            power_y_dbm=records[:, 3].astype(float),
            trigger_flag=trigger_flag,
        )
