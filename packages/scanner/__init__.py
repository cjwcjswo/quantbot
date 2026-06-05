"""Per-strategy watch-candidate selection (arch doc §6.11)."""

from packages.scanner.symbol_scanner import (
    SymbolScanner,
    depth_usdt_within,
    scanner_score,
)

__all__ = ["SymbolScanner", "depth_usdt_within", "scanner_score"]
