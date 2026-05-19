# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
r"""Tests for Feature 1: crypto package bootstrap and dependency wiring.

Verifies that all third-party crypto dependencies are declared in
pyproject.toml with correct version ranges, that they are importable after
``poetry install``, and that the ``oasis.crypto`` and ``test.crypto``
package markers exist.

These tests are intentionally RED before implementation:
  - T4 fails until ``oasis/crypto/__init__.py`` is created.
  - T6 fails until ``pyproject.toml`` is updated with the new deps.
  - T1/T2/T3 fail until ``poetry install`` has added the new packages.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# T1 — pynacl import works
# ---------------------------------------------------------------------------


def test_pynacl_import_works() -> None:
    r"""T1: nacl.signing is importable after poetry install."""
    import nacl.signing  # noqa: F401


# ---------------------------------------------------------------------------
# T2 — eth_account high-level EIP-712 surface importable
# ---------------------------------------------------------------------------


def test_eth_account_high_level_surface_importable() -> None:
    r"""T2: encode_typed_data, Account.sign_message, Account.recover_message co-resolvable."""
    from eth_account import Account
    from eth_account.messages import encode_typed_data  # noqa: F401

    assert hasattr(Account, "sign_message"), "Account.sign_message missing"
    assert hasattr(Account, "recover_message"), "Account.recover_message missing"


# ---------------------------------------------------------------------------
# T3 — base58 explicit import works
# ---------------------------------------------------------------------------


def test_base58_explicit_import_works() -> None:
    r"""T3: base58 module exposes b58encode and b58decode."""
    import base58

    assert hasattr(base58, "b58encode"), "base58.b58encode missing"
    assert hasattr(base58, "b58decode"), "base58.b58decode missing"


# ---------------------------------------------------------------------------
# T4 — oasis.crypto package importable
# ---------------------------------------------------------------------------


def test_crypto_package_importable() -> None:
    r"""T4: ``from oasis import crypto`` succeeds (oasis/crypto/__init__.py must exist)."""
    from oasis import crypto  # noqa: F401


# ---------------------------------------------------------------------------
# T5 — test.crypto package importable
# ---------------------------------------------------------------------------


def test_test_crypto_package_importable() -> None:
    r"""T5: ``import test.crypto`` succeeds (test/crypto/__init__.py must exist)."""
    import test.crypto  # noqa: F401


# ---------------------------------------------------------------------------
# T6 — pyproject.toml lists deps with correct ranges
# ---------------------------------------------------------------------------


def test_pyproject_lists_deps_with_correct_ranges() -> None:
    r"""T6: pyproject.toml declares correct version ranges for all crypto deps.

    Checks:
      - pynacl ^1.5.0 in main dependencies
      - eth-account >=0.10.0,<0.14.0 in main dependencies
      - base58 ^2.1.0 in main dependencies
      - didkit ^0.3.0 under extras/optional group ``crypto-full``
    """
    root = Path(__file__).parents[2]
    content = (root / "pyproject.toml").read_text()

    # pynacl ^1.5.0
    assert re.search(r'pynacl\s*=\s*["\'^].*1\.5', content, re.IGNORECASE), (
        "pynacl = \"^1.5.0\" not found in pyproject.toml"
    )

    # eth-account with >=0.10.0 lower bound
    assert re.search(r'eth-account', content, re.IGNORECASE), (
        "eth-account entry missing from pyproject.toml"
    )
    assert re.search(r'0\.10\.0', content), (
        "eth-account lower bound >=0.10.0 missing from pyproject.toml"
    )
    # eth-account with <0.14.0 upper bound
    assert re.search(r'0\.14\.0', content), (
        "eth-account upper bound <0.14.0 missing from pyproject.toml"
    )

    # base58 ^2.1.0
    assert re.search(r'base58\s*=\s*["\'^].*2\.1', content, re.IGNORECASE), (
        "base58 = \"^2.1.0\" not found in pyproject.toml"
    )

    # didkit under optional extras crypto-full
    assert re.search(r'didkit', content, re.IGNORECASE), (
        "didkit entry missing from pyproject.toml"
    )
    assert re.search(r'crypto-full', content, re.IGNORECASE), (
        "extras group \"crypto-full\" missing from pyproject.toml"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_didkit_not_required_for_base_import() -> None:
    r"""Edge: oasis.crypto must import without didkit (no Rust toolchain needed).

    If didkit is NOT installed, the import of oasis.crypto must still succeed.
    If didkit IS installed, we simply confirm it is importable and skip the
    negative-path assertion.
    """
    if importlib.util.find_spec("didkit") is None:
        # didkit absent — oasis.crypto must still work
        from oasis import crypto  # noqa: F401
    else:
        # didkit present — both paths work; positive case is fine
        import didkit  # noqa: F401
        from oasis import crypto  # noqa: F401


def test_eth_account_installed_version_in_range() -> None:
    r"""Edge: installed eth-account version is >=0.10.0 and <0.14.0."""
    try:
        from packaging.version import Version

        ver_str = importlib.metadata.version("eth-account")
        ver = Version(ver_str)
        assert ver >= Version("0.10.0"), (
            f"eth-account {ver_str} is below minimum 0.10.0"
        )
        assert ver < Version("0.14.0"), (
            f"eth-account {ver_str} meets or exceeds maximum 0.14.0"
        )
    except importlib.metadata.PackageNotFoundError:
        pytest.fail("eth-account is not installed")
    except ImportError:
        pytest.skip("packaging library not available for version comparison")


def test_base58_installed_version_in_range() -> None:
    r"""Edge: installed base58 version is >=2.1.0 and <3.0.0."""
    try:
        from packaging.version import Version

        ver_str = importlib.metadata.version("base58")
        ver = Version(ver_str)
        assert ver >= Version("2.1.0"), (
            f"base58 {ver_str} is below minimum 2.1.0"
        )
        assert ver < Version("3.0.0"), (
            f"base58 {ver_str} meets or exceeds maximum 3.0.0"
        )
    except importlib.metadata.PackageNotFoundError:
        pytest.fail("base58 is not installed")
    except ImportError:
        pytest.skip("packaging library not available for version comparison")
