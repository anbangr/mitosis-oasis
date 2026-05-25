"""Calldata decoder: strips the 4-byte selector and ABI-decodes arguments.

TODO: eth_abi is not currently in oasis deps; add it when the first concrete
adapter (Task 12+) needs decoded args.  Until then, decode_args() returns []
unconditionally so callers can rely on its signature without a hard dep.

When eth_abi is added to pyproject.toml, remove the try/except stub block and
the module-level _ETH_ABI_AVAILABLE guard.
"""

from __future__ import annotations

import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

try:
    import eth_abi  # type: ignore[import]
    _ETH_ABI_AVAILABLE = True
except ImportError:
    _ETH_ABI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_types(function_signature: str) -> list[str]:
    """Parse ``"name(uint256,address)"`` → ``["uint256", "address"]``."""
    match = re.search(r"\((.*)\)", function_signature)
    if not match:
        return []
    inner = match.group(1).strip()
    if not inner:
        return []
    return [t.strip() for t in inner.split(",")]


def _to_str(value: Any) -> str:
    """Normalise a decoded ABI value to a string suitable for comparison."""
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        # Addresses come back as checksummed strings from eth_abi.
        if re.match(r"^0x[0-9a-fA-F]{40}$", value):
            return value.lower()
        return value
    # Tuples, lists, etc. — best effort stringification.
    return str(value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decode_args(raw_calldata: str, function_signature: str) -> list[str]:
    """Decode ABI-encoded arguments from *raw_calldata*.

    Args:
        raw_calldata: Hex string like ``"0x6a0eb579000…"`` (4-byte selector
            followed by ABI-encoded arguments).
        function_signature: Canonical Solidity signature like
            ``"setQuorum(uint256)"`` or ``"transfer(address,uint256)"``.

    Returns:
        A list of decoded argument strings, or ``[]`` if decoding is not
        possible (missing dep, malformed input, selector mismatch, etc.).
    """
    if not _ETH_ABI_AVAILABLE:
        # TODO: install eth-abi (e.g. ``poetry add eth-abi``) to enable
        # calldata decoding.  See test/conformance/adapter/_calldata.py.
        return []

    if not raw_calldata or len(raw_calldata) < 10:
        # Too short to contain a 4-byte selector ("0x" + 8 hex chars = 10).
        return []

    # Strip "0x" prefix and the 4-byte selector (8 hex chars).
    rest_hex = raw_calldata.lstrip("0x")[8:]
    if not rest_hex:
        # No argument bytes after the selector.
        return []

    types = _extract_types(function_signature)
    if not types:
        return []

    try:
        decoded = eth_abi.decode(types, bytes.fromhex(rest_hex))
        return [_to_str(v) for v in decoded]
    except Exception as exc:  # noqa: BLE001
        print(
            f"[_calldata] decode_args failed for sig={function_signature!r}: {exc}",
            file=sys.stderr,
        )
        return []
