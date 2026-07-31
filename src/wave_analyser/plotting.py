"""Plotting helpers for WaveAnalyzer traces.

`matplotlib` is imported lazily so the driver itself stays usable on machines
without a plotting stack installed.
"""

from __future__ import annotations

from .driver import ScanData


def plot_scan(scan: ScanData, ip: str = "", save_path: str | None = None,
              show: bool = True) -> None:
    """Plot a trace (frequency in THz vs. absolute power in dBm).

    Args:
        scan: Trace returned by `WaveAnalyzer1500S.get_data()`.
        ip: Optional instrument address, used in the plot title.
        save_path: If given, save the figure to this path at 300 dpi.
        show: Whether to call `plt.show()` (set False for headless use).
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(scan.freq_mhz / 1e6, scan.power_dbm, lw=1.0)
    ax.set_xlabel("Frequency (THz)")
    ax.set_ylabel("Absolute power (dBm)")
    title = "WaveAnalyzer 1500S"
    if ip:
        title += f" @ {ip}"
    ax.set_title(f"{title} — scan {scan.scan_id}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"Saved plot to {save_path}")
    if show:
        plt.show()
