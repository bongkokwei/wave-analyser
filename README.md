# wave-analyser

Python driver for the II-VI / Finisar **WaveAnalyzer™ 1500S** optical spectrum
analyser.

The instrument exposes a RESTful HTTP API directly on the unit — there is no
SCPI/VISA layer — so this driver talks HTTP via `requests` rather than
`pyvisa`/`pyserial`.

Reference: WaveAnalyzer 1500S User Manual, Part Number 1233834, Rev. G00,
Section 4.2 (WaveAnalyzer 1500S Web API).

## Install

```bash
pip install git+https://github.com/bongkokwei/wave-analyser.git
```

Development install (editable, with test and plotting extras):

```bash
git clone https://github.com/bongkokwei/wave-analyser.git
cd wave-analyser
pip install -e ".[dev]" --break-system-packages
```

## Usage

```python
from wave_analyser import WaveAnalyzer1500S, plot_scan

with WaveAnalyzer1500S("169.254.3.8") as wa:      # or "WA000001.local"
    print(wa.get_info())

    wa.set_scan(center_mhz=193_700_000, span_mhz=1_000_000, tag="Normal")
    wa.wait_for_scan()                            # avoid racing a stale trace

    scan = wa.get_data()

print(scan.freq_mhz[scan.power_dbm.argmax()] / 1e6, "THz peak")
plot_scan(scan)
```

`set_scan()` only configures the sweep range and returns immediately — the unit
scans continuously in the background — so call `wait_for_scan()` before
`get_data()` or you may read an empty or stale trace.

### Full-range scans

`scan_full()` mirrors the GUI's *Full* / *Full (Coarse)* modes:

```python
wa.scan_full(port="Normal", coarse=True)    # 100 MHz step, faster
wa.scan_full(port="HighSens", coarse=False) # 20 MHz step, higher resolution
```

### API

| Method | Purpose |
|---|---|
| `get_info()` | Model, serial number, firmware version, vendor |
| `get_scan_info()` | Configuration of the most recent scan |
| `set_scan(center_mhz, span_mhz, tag)` | Configure the sweep range |
| `scan_full(port, coarse)` | Full-range scan across the operating range |
| `wait_for_scan(timeout, poll_interval)` | Block until a fresh scan completes |
| `get_data(triggerin)` | Fetch the trace on a dBm scale as a `ScanData` |
| `get_linear_data(triggerin)` | Fetch the trace on a linear scale (firmware ≥ 1.02) |

`ScanData` fields: `scan_id`, `freq_mhz`, `power_dbm`, `power_x_dbm`,
`power_y_dbm`, `trigger_flag` — all traces are numpy arrays.

Valid `tag` values: `Normal`, `HighSens`, `Normal20MHz`, `HighSens20MHz`.

> **Linear data caveat**: the manual does not state a fixed-point scale factor
> for the linear power fields (unlike the dBm endpoint's documented milli-dBm
> units). `get_linear_data()` returns raw integer counts; rescale as needed once
> verified against a real unit.

## Command line

A smoke test entry point is installed as `wave-analyser`:

```bash
wave-analyser 169.254.3.8 --center 193700000 --span 1000000 --plot
wave-analyser 169.254.3.8 --full coarse --save-fig trace.png
```

## Tests

Unit tests mock the HTTP layer and need no hardware:

```bash
pytest
```

Hardware tests are tagged `hw` and skipped by default:

```bash
WAVEANALYSER_IP=169.254.3.8 pytest --hw
```

## Layout

```
src/wave_analyser/
├── __init__.py     # public API
├── driver.py       # WaveAnalyzer1500S, ScanData
├── plotting.py     # plot_scan()
└── cli.py          # wave-analyser entry point
```
