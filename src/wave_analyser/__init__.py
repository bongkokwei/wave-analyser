"""Python driver for the II-VI / Finisar WaveAnalyzer(TM) 1500S OSA."""

from .driver import (
    FULL_SCAN_CENTER_MHZ,
    VALID_TAGS,
    ScanData,
    WaveAnalyzer1500S,
)
from .plotting import plot_scan

__all__ = [
    "WaveAnalyzer1500S",
    "ScanData",
    "VALID_TAGS",
    "FULL_SCAN_CENTER_MHZ",
    "plot_scan",
]

__version__ = "0.1.0"
