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
"""Bootstrap tests for crypto package dependencies and imports."""

import subprocess
import sys

import pytest
import tomlkit


def test_t1_pynacl_import():
    """pynacl import works in clean venv."""
    result = subprocess.run(
        [sys.executable, "-c", "import nacl.signing"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_t2_eth_account_eip712_surface():
    """eth_account high-level EIP-712 surface is importable."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from eth_account.messages import encode_typed_data; "
                "from eth_account import Account; "
                "assert hasattr(Account, 'sign_message') and hasattr(Account, 'recover_message')"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_t3_base58_import():
    """base58 explicit import works."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import base58; assert hasattr(base58, 'b58encode') and hasattr(base58, 'b58decode')",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_t4_crypto_package_importable():
    """oasis.crypto package is importable without ImportError."""
    from oasis import crypto

    assert crypto is not None


def test_t5_test_crypto_importable():
    """test.crypto package is importable without ImportError."""
    import test.crypto

    assert test.crypto is not None


def test_t6_pyproject_deps():
    """pyproject.toml lists deps with correct ranges."""
    with open("pyproject.toml") as f:
        doc = tomlkit.parse(f.read())

    deps = doc["tool"]["poetry"]["dependencies"]
    assert "pynacl" in deps
    assert str(deps["pynacl"]) == "^1.5.0"
    assert "eth-account" in deps
    assert str(deps["eth-account"]) == ">=0.10.0,<0.14.0"
    assert "base58" in deps
    assert str(deps["base58"]) == "^2.1.0"

    optional = deps.get("didkit")
    assert optional is not None
    assert str(optional["version"]) == "^0.3.0"
    assert optional.get("optional") is True

    extras = doc["tool"]["poetry"].get("extras", {})
    assert "crypto-full" in extras
    assert "didkit" in extras["crypto-full"]


def test_eth_account_version_range():
    """Installed eth-account version is in the expected range."""
    import eth_account

    version = eth_account.__version__
    parts = version.split(".")
    major = int(parts[0])
    minor = int(parts[1])
    assert major == 0
    assert 10 <= minor < 14, f"eth-account {version} not in >=0.10.0,<0.14.0"


def test_base58_version_range():
    """Installed base58 version is in the expected range."""
    import base58

    version = base58.__version__
    parts = version.split(".")
    major = int(parts[0])
    minor = int(parts[1])
    assert major == 2
    assert minor >= 1, f"base58 {version} not in >=2.1.0,<3.0.0"
