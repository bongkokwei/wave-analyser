"""Command-line hardware smoke test for the WaveAnalyzer 1500S.

    wave-analyser <ip> [--center MHZ] [--span MHZ] [--tag TAG] [--plot]
    wave-analyser <ip> --full coarse [--plot]
"""

from __future__ import annotations

import argparse

from .driver import FULL_SCAN_CENTER_MHZ, VALID_TAGS, WaveAnalyzer1500S
from .plotting import plot_scan


def run_demo(ip: str, center_mhz: float, span_mhz: float, tag: str,
             plot: bool = False, save_path: str | None = None,
             full: str | None = None) -> None:
    """Connect to a real WaveAnalyzer 1500S, configure a scan, and fetch data."""
    with WaveAnalyzer1500S(ip) as wa:
        info = wa.get_info()
        print("Device info:", info)

        if full is not None:
            port = "HighSens" if "highsens" in tag.lower() else "Normal"
            rc = wa.scan_full(port=port, coarse=(full == "coarse"))
        else:
            rc = wa.set_scan(center_mhz=center_mhz, span_mhz=span_mhz, tag=tag)
        print("set_scan response:", rc)
        assert rc.get("rc") == 0, f"scan configuration failed: {rc}"

        scanid = wa.wait_for_scan()
        print(f"Fresh scan ready (scanid={scanid})")

        scan_info = wa.get_scan_info()
        print("Scan info:", scan_info)

        scan = wa.get_data()
        assert scan.freq_mhz.size > 0, "no data points returned"
        assert scan.freq_mhz.size == scan.power_dbm.size

        print(f"Scan id: {scan.scan_id}")
        print(f"Points: {scan.freq_mhz.size}")
        print(f"Freq range: {scan.freq_mhz.min() / 1e6:.4f}-"
              f"{scan.freq_mhz.max() / 1e6:.4f} THz")
        print(f"Peak power: {scan.power_dbm.max():.3f} dBm "
              f"at {scan.freq_mhz[scan.power_dbm.argmax()] / 1e6:.4f} THz")

    print("Hardware smoke test passed.")

    if plot:
        plot_scan(scan, ip=ip, save_path=save_path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ip", help="IP address or mDNS hostname, e.g. 169.254.3.8")
    parser.add_argument("--center", type=float, default=FULL_SCAN_CENTER_MHZ,
                        help="Scan centre frequency in MHz (default: 193.7 THz)")
    parser.add_argument("--span", type=float, default=1_000_000,
                        help="Scan span in MHz, -1 for full scan (default: 1 THz)")
    parser.add_argument("--tag", default="Normal", choices=sorted(VALID_TAGS))
    parser.add_argument("--full", choices=("coarse", "fine"), default=None,
                        help="Full-range scan, matching the GUI's Full/Full (Coarse) "
                             "modes (overrides --center/--span; port taken from --tag)")
    parser.add_argument("--plot", action="store_true",
                        help="Show a matplotlib plot of the trace")
    parser.add_argument("--save-fig", default=None,
                        help="Path to save the plot (implies --plot)")
    args = parser.parse_args(argv)

    run_demo(args.ip, args.center, args.span, args.tag,
             plot=args.plot or bool(args.save_fig),
             save_path=args.save_fig, full=args.full)


if __name__ == "__main__":
    main()
