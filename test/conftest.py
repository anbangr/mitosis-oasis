# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
import hashlib
import os
import re
import sys
from pathlib import Path

import pytest

# Add the project root directory to sys.path
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
sys.path.insert(0, root_path)


def _selects_only_conformance(markexpr):
    tokens = set(re.findall(r"\b\w+\b", markexpr))
    if "conformance" not in tokens or "or" in tokens:
        return False

    for match in re.finditer(r"\bconformance\b", markexpr):
        prefix = markexpr[: match.start()].rstrip()
        if not prefix.endswith("not"):
            return True
    return False


def pytest_ignore_collect(collection_path, config):
    markexpr = getattr(config.option, "markexpr", "") or ""
    if not _selects_only_conformance(markexpr):
        return False

    path = Path(str(collection_path)).resolve()
    conformance_root = Path(root_path).resolve() / "test" / "conformance"
    if path == conformance_root or conformance_root in path.parents:
        return False
    if path == conformance_root.parent or conformance_root.parent in path.parents:
        return True
    return False


@pytest.fixture
def ed25519_keypair(request):
    r"""Deterministic Ed25519 keypair seeded from the test node name.

    Returns ``(private_key, public_key)`` — both 32-byte ``bytes``.
    Calling the fixture from two tests with the same name produces
    identical key material.
    """
    from oasis.crypto import ed25519

    seed = hashlib.sha256(request.node.name.encode()).digest()
    return ed25519.keypair_from_seed(seed)


@pytest.fixture
def eth_account_signer(request):
    r"""Deterministic Ethereum account seeded from ``b'eth-' + test_name``.

    Returns an :class:`eth_account.Account` instance.  The address is
    identical across runs when the same test name is used.
    """
    from eth_account import Account

    seed = hashlib.sha256(b"eth-" + request.node.name.encode()).digest()
    return Account.from_key(seed)
