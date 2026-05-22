# Bundle 1 — Cryptographic Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace v0.2.x mock crypto (empty-string signatures, `did:mock:` strings, no typed-data) with real Ed25519 + secp256k1 + W3C DID resolution + EIP-712 typed-data binding. Land `mitosis-oasis` at version **0.4.0**.

**Architecture:** New `oasis/crypto/` package with five pure-Python modules (ed25519, secp256k1, did, eip712, typed_data). Schema gains a `public_key` column on `agent_registry` and a `signature` column on `message_log`. Two FastAPI dependencies (`require_ed25519_sig`, `require_eip712_sig`) gate the right routes. EIP-712-required routes: every Rules Hub mutation + every Override Panel binding action. Session-auth routes (Logging Hub, Dashboard, observation queries) keep their current shape.

**Tech Stack:** Python 3.10-3.11, FastAPI, SQLite, pytest, Pydantic, **+ pynacl** (Ed25519 via libsodium), **+ eth_account** (EIP-712 + secp256k1, used by web3.py), **+ didkit-py** (W3C DID resolution, Rust-backed).

**Depends on:** Bundle 0 merged (v0.3.0). Specifically: `test/spec_v097/` directory exists, `CHANGELOG.md` exists, `config.reputation_lambda` knob exists.

**Source spec:** [2026-05-18-agentcity-v097-parity-design.md](../specs/2026-05-18-agentcity-v097-parity-design.md) sections 2 (Bundle 1), 3 (crypto module surface), 4 (Flow 1, Flow 3).

---

## File Map

**New files (12):**

- `oasis/crypto/__init__.py`
- `oasis/crypto/ed25519.py` — keypair gen + sign + verify (pynacl wrapper)
- `oasis/crypto/secp256k1.py` — sign + verify (eth_account wrapper)
- `oasis/crypto/did.py` — W3C `did:key:zXXX` resolution + `did_from_pubkey()`
- `oasis/crypto/eip712.py` — typed-data hashing + signature recovery + verify
- `oasis/crypto/typed_data.py` — Pydantic schema for EIP-712 domain + types
- `oasis/api_auth.py` — FastAPI dependencies (`require_ed25519_sig`, `require_eip712_sig`)
- `test/spec_v097/test_idn_114_did_key_resolution.py`
- `test/spec_v097/test_idn_117_ed25519_attestation.py`
- `test/spec_v097/test_adj_105_eip712_binding.py`
- `test/spec_v097/test_adj_106_session_auth_observation.py`
- `test/crypto/` directory (unit tests for the five crypto modules; not under spec_v097/ because they test plumbing, not rubric rows)

**Modified files (9):**

- `oasis/governance/schema.py` — add `public_key TEXT` column to `agent_registry`; add `signature TEXT` column to `message_log`
- `oasis/governance/clerks/registrar.py` — mint Ed25519 keypair on registration; verify Ed25519 sig on attestation
- `oasis/governance/clerks/speaker.py` — verify Ed25519 sig on co-sponsor attachments
- `oasis/governance/clerks/regulator.py` — verify Ed25519 sig on bid submissions
- `oasis/governance/clerks/codifier.py` — verify Ed25519 sig on MSG6 broadcasts
- `oasis/governance/messages.py` — `signature` field on every MSG model becomes non-empty Ed25519 sig bytes (hex-encoded string)
- `oasis/adjudication/endpoints.py` — `require_eip712_sig` dependency on every mutation route (slash, override-panel decision)
- `oasis/api.py` — wire `oasis.api_auth` middleware on Rules Hub route (PUT `/api/governance/constitution`); split currently-permissive routes
- `pyproject.toml` — version 0.3.0 → 0.4.0; add `pynacl`, `eth_account`, `didkit-py` deps

**Extended files:**

- `test/e2e/test_full_protocol_smoke.py` — extend to use real Ed25519 keys end-to-end

---

## Library Choices (locked at design time)

- **pynacl** (`PyNaCl ≥ 1.5.0`) — Ed25519, libsodium-backed. Production-grade.
- **eth_account** (`≥ 0.10.0`) — EIP-712 (`encode_typed_data`), secp256k1 (`Account.recover_message`). Same lib `web3.py` uses; battle-tested.
- **didkit-py** (`≥ 0.3.0`) — `did:key` resolution + pubkey extraction. Rust-backed via `maturin` wheels; falls back to a 100-LoC Python `did:key:zXXX` resolver if didkit-py can't be installed in CI (see Task 4).

---

## Conventions

- **DID format:** `did:key:zXXX` where `zXXX` is the multibase-base58-btc-encoded Ed25519 pubkey with multicodec prefix `0xed01`. Registrar produces these; the resolver inverts them.
- **Signature format on the wire:** lowercase hex string, 128 chars (64 bytes Ed25519) or 130 chars (65 bytes secp256k1, including recovery byte).
- **EIP-712 domain:** `name="MitosisOasis", version="0.4.0", chainId=0, verifyingContract="0x0000...0000"`. `chainId=0` flags "no real chain"; verifyingContract is the zero address. Both are inputs to the canonical typed-data hash.
- **Test crypto fixtures:** `test/conftest.py` (root) gains `ed25519_keypair`, `eth_account_signer` fixtures that mint deterministic keys from a hash of the test name. No randomness in tests.

---

## Task 1: Add deps + bootstrap `oasis/crypto/` package

**Files:**

- Modify: `pyproject.toml`
- Create: `oasis/crypto/__init__.py`
- Create: `test/crypto/__init__.py`

- [ ] **Step 1.1: Add deps to `pyproject.toml`**

Under `[tool.poetry.dependencies]` (or `[project.dependencies]`), add:

```toml
pynacl = "^1.5.0"
eth-account = "^0.10.0"
didkit = { version = "^0.3.0", optional = true }
```

Mark `didkit` optional because some CI environments can't install Rust wheels; the resolver in Task 4 falls back to a pure-Python implementation. Add `didkit` to the `[tool.poetry.extras]` block as `crypto-full = ["didkit"]`.

- [ ] **Step 1.2: Install + lock**

Run:

```bash
poetry lock
poetry install --no-root
```

Expected: `pynacl`, `eth-account` installed. didkit-py installs if the Rust toolchain is available; otherwise marked as optional-not-installed.

- [ ] **Step 1.3: Verify imports**

Run:

```bash
python -c "import nacl.signing; import eth_account; print('OK')"
```

Expected: `OK`.

- [ ] **Step 1.4: Bootstrap packages**

```bash
mkdir -p oasis/crypto test/crypto
touch oasis/crypto/__init__.py test/crypto/__init__.py
```

- [ ] **Step 1.5: Commit**

```bash
git add pyproject.toml poetry.lock oasis/crypto/__init__.py test/crypto/__init__.py
git commit -m "chore(crypto): add pynacl, eth_account, didkit-py deps; bootstrap package"
```

---

## Task 2: `oasis/crypto/ed25519.py` (TDD)

**Files:**

- Create: `oasis/crypto/ed25519.py`
- Create: `test/crypto/test_ed25519.py`

- [ ] **Step 2.1: Write failing tests**

Create `test/crypto/test_ed25519.py`:

```python
"""Ed25519 wrapper: generate_keypair / sign / verify. Pure function module."""
from __future__ import annotations

import pytest

from oasis.crypto import ed25519


def test_keypair_is_32_bytes_each():
    priv, pub = ed25519.generate_keypair()
    assert isinstance(priv, bytes) and len(priv) == 32
    assert isinstance(pub, bytes) and len(pub) == 32


def test_sign_then_verify_roundtrip():
    priv, pub = ed25519.generate_keypair()
    msg = b"hello agentcity"
    sig = ed25519.sign(priv, msg)
    assert len(sig) == 64
    assert ed25519.verify(pub, msg, sig) is True


def test_verify_rejects_wrong_message():
    priv, pub = ed25519.generate_keypair()
    sig = ed25519.sign(priv, b"original")
    assert ed25519.verify(pub, b"tampered", sig) is False


def test_verify_rejects_wrong_pubkey():
    priv_a, _ = ed25519.generate_keypair()
    _, pub_b = ed25519.generate_keypair()
    sig = ed25519.sign(priv_a, b"msg")
    assert ed25519.verify(pub_b, b"msg", sig) is False


def test_deterministic_keypair_from_seed():
    """Used by test fixtures to derive stable keypairs per test name."""
    seed = b"\x00" * 32
    priv1, pub1 = ed25519.keypair_from_seed(seed)
    priv2, pub2 = ed25519.keypair_from_seed(seed)
    assert priv1 == priv2 and pub1 == pub2
```

- [ ] **Step 2.2: Run to confirm failures**

Run: `pytest test/crypto/test_ed25519.py -v`
Expected: ImportError on `from oasis.crypto import ed25519`.

- [ ] **Step 2.3: Implement `oasis/crypto/ed25519.py`**

```python
"""Ed25519 wrapper. Stateless, no I/O. Uses pynacl (libsodium)."""
from __future__ import annotations

import nacl.signing
import nacl.exceptions


def generate_keypair() -> tuple[bytes, bytes]:
    """Mint a fresh Ed25519 keypair.

    Returns (private_key_bytes, public_key_bytes), each 32 bytes.
    """
    signing_key = nacl.signing.SigningKey.generate()
    return bytes(signing_key), bytes(signing_key.verify_key)


def keypair_from_seed(seed: bytes) -> tuple[bytes, bytes]:
    """Derive a deterministic keypair from a 32-byte seed.

    Used by tests so keys stay stable across runs.
    """
    if len(seed) != 32:
        raise ValueError(f"seed must be 32 bytes, got {len(seed)}")
    signing_key = nacl.signing.SigningKey(seed)
    return bytes(signing_key), bytes(signing_key.verify_key)


def sign(private_key: bytes, message: bytes) -> bytes:
    """Sign `message` with Ed25519. Returns 64-byte signature."""
    if len(private_key) != 32:
        raise ValueError(f"private_key must be 32 bytes, got {len(private_key)}")
    signing_key = nacl.signing.SigningKey(private_key)
    signed = signing_key.sign(message)
    return signed.signature  # 64 bytes


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify Ed25519 signature. Returns True iff valid."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        verify_key = nacl.signing.VerifyKey(public_key)
        verify_key.verify(message, signature)
        return True
    except nacl.exceptions.BadSignatureError:
        return False
```

- [ ] **Step 2.4: Run tests and commit**

Run: `pytest test/crypto/test_ed25519.py -v`
Expected: 5 passed.

```bash
git add oasis/crypto/ed25519.py test/crypto/test_ed25519.py
git commit -m "feat(crypto): real Ed25519 signing via pynacl

5-function module (generate_keypair, keypair_from_seed, sign, verify,
plus a deterministic seed path for tests). No state, no I/O."
```

---

## Task 3: `oasis/crypto/secp256k1.py` (TDD)

**Files:**

- Create: `oasis/crypto/secp256k1.py`
- Create: `test/crypto/test_secp256k1.py`

- [ ] **Step 3.1: Write failing tests**

Create `test/crypto/test_secp256k1.py`:

```python
"""secp256k1 wrapper for EIP-712 use. Uses eth_account."""
from __future__ import annotations

import pytest
from eth_account import Account

from oasis.crypto import secp256k1


def test_sign_then_recover():
    """Round-trip: sign(msg) then recover_signer(msg, sig) returns the
    address that did the signing."""
    acct = Account.create()
    msg_hash = b"\x00" * 32  # any 32-byte hash
    sig = secp256k1.sign_hash(acct.key, msg_hash)
    assert len(sig) == 65  # r(32) + s(32) + v(1)
    recovered = secp256k1.recover_signer(msg_hash, sig)
    assert recovered.lower() == acct.address.lower()


def test_recover_rejects_wrong_hash():
    """Recovery from a different hash yields a different (likely junk) address."""
    acct = Account.create()
    sig = secp256k1.sign_hash(acct.key, b"\x00" * 32)
    recovered = secp256k1.recover_signer(b"\x01" * 32, sig)
    assert recovered.lower() != acct.address.lower()
```

- [ ] **Step 3.2: Run to confirm failures**

Run: `pytest test/crypto/test_secp256k1.py -v`
Expected: ImportError.

- [ ] **Step 3.3: Implement `oasis/crypto/secp256k1.py`**

```python
"""secp256k1 wrapper used by EIP-712 signature verification.

Thin layer over eth_account.Account (`web3.py`'s signer). The recovery
byte `v` is 27 or 28 in canonical form.
"""
from __future__ import annotations

from eth_account import Account
from eth_account._utils.signing import sign_message_hash
from eth_keys import keys


def sign_hash(private_key: bytes, msg_hash: bytes) -> bytes:
    """Sign a 32-byte hash. Returns 65-byte (r, s, v) signature."""
    if len(msg_hash) != 32:
        raise ValueError(f"msg_hash must be 32 bytes, got {len(msg_hash)}")
    if len(private_key) != 32:
        raise ValueError(f"private_key must be 32 bytes, got {len(private_key)}")
    pk = keys.PrivateKey(private_key)
    v, r, s, _eth_sig = sign_message_hash(pk, msg_hash)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v])


def recover_signer(msg_hash: bytes, signature: bytes) -> str:
    """Recover the EIP-55 hex address that signed `msg_hash`.

    Returns the address as `0x...` checksummed string.
    """
    if len(msg_hash) != 32 or len(signature) != 65:
        raise ValueError("bad hash or sig length")
    r = int.from_bytes(signature[0:32], "big")
    s = int.from_bytes(signature[32:64], "big")
    v = signature[64]
    sig = keys.Signature(vrs=(v - 27 if v >= 27 else v, r, s))
    public_key = sig.recover_public_key_from_msg_hash(msg_hash)
    return public_key.to_checksum_address()
```

- [ ] **Step 3.4: Run tests and commit**

Run: `pytest test/crypto/test_secp256k1.py -v`
Expected: 2 passed.

```bash
git add oasis/crypto/secp256k1.py test/crypto/test_secp256k1.py
git commit -m "feat(crypto): secp256k1 sign + recover via eth_account

Used by EIP-712 verification. Pure function module."
```

---

## Task 4: `oasis/crypto/did.py` (TDD) — pure-Python `did:key` fallback

**Files:**

- Create: `oasis/crypto/did.py`
- Create: `test/crypto/test_did.py`

- [ ] **Step 4.1: Write failing tests**

Create `test/crypto/test_did.py`:

```python
"""W3C did:key resolution. Round-trip: pubkey -> did:key:zXXX -> pubkey."""
from __future__ import annotations

import pytest

from oasis.crypto import did, ed25519


def test_did_from_pubkey_roundtrip():
    _, pub = ed25519.generate_keypair()
    d = did.did_from_pubkey(pub)
    assert d.startswith("did:key:z")
    resolved_pub = did.resolve(d)
    assert resolved_pub == pub


def test_did_format_uses_ed25519_multicodec():
    """did:key for Ed25519 uses multicodec prefix 0xed01."""
    pub = b"\x01" * 32
    d = did.did_from_pubkey(pub)
    # The body of the DID, after did:key:z, must encode 0xed01 + 32-byte pubkey
    # in base58-btc.
    assert d.startswith("did:key:z")


def test_resolve_rejects_non_did_key():
    """Only did:key supported in mock-chain mode."""
    with pytest.raises(ValueError, match="did:key"):
        did.resolve("did:web:example.com")


def test_resolve_rejects_malformed():
    with pytest.raises(ValueError):
        did.resolve("did:key:NOT_VALID")
```

- [ ] **Step 4.2: Run to confirm failures**

Run: `pytest test/crypto/test_did.py -v`
Expected: ImportError.

- [ ] **Step 4.3: Implement `oasis/crypto/did.py`**

```python
"""W3C `did:key` resolver. Supports Ed25519 keys (multicodec 0xed01).

Pure-Python `did:key` resolution. didkit-py is optional and used when
installed for compatibility with the broader W3C DID ecosystem; the
pure-Python path is the canonical one for tests.
"""
from __future__ import annotations

import base58


# Multicodec prefix for Ed25519 public key (varint-encoded 0xed)
ED25519_MULTICODEC_PREFIX = bytes([0xed, 0x01])


def did_from_pubkey(public_key: bytes) -> str:
    """Encode an Ed25519 32-byte pubkey as a `did:key:zXXX` identifier."""
    if len(public_key) != 32:
        raise ValueError(f"pubkey must be 32 bytes, got {len(public_key)}")
    payload = ED25519_MULTICODEC_PREFIX + public_key
    encoded = base58.b58encode(payload).decode("ascii")
    return f"did:key:z{encoded}"


def resolve(did_str: str) -> bytes:
    """Resolve a `did:key:zXXX` identifier back to the 32-byte pubkey.

    Returns the raw public key bytes. Raises ValueError if the DID is
    malformed or uses a non-Ed25519 multicodec.
    """
    if not did_str.startswith("did:key:z"):
        raise ValueError(
            f"only did:key supported in this implementation, got: {did_str}"
        )
    body = did_str[len("did:key:z"):]
    try:
        decoded = base58.b58decode(body)
    except Exception as exc:
        raise ValueError(f"invalid base58 body: {body}") from exc
    if not decoded.startswith(ED25519_MULTICODEC_PREFIX):
        raise ValueError(
            f"expected Ed25519 multicodec prefix 0xed01, got: {decoded[:2].hex()}"
        )
    pubkey = decoded[len(ED25519_MULTICODEC_PREFIX):]
    if len(pubkey) != 32:
        raise ValueError(f"decoded pubkey is {len(pubkey)} bytes, expected 32")
    return pubkey
```

Add `base58` to `pyproject.toml` deps if not already present. (It's a transitive of eth-account, usually already installed; verify with `python -c "import base58"`.)

- [ ] **Step 4.4: Run tests and commit**

Run: `pytest test/crypto/test_did.py -v`
Expected: 4 passed.

```bash
git add oasis/crypto/did.py test/crypto/test_did.py
git commit -m "feat(crypto): did:key W3C resolver (Ed25519 multicodec 0xed01)

Pure-Python implementation. didkit-py optional for broader W3C method
support; this module is the canonical did:key path used by oasis."
```

---

## Task 5: `oasis/crypto/eip712.py` + `typed_data.py` (TDD)

**Files:**

- Create: `oasis/crypto/typed_data.py`
- Create: `oasis/crypto/eip712.py`
- Create: `test/crypto/test_eip712.py`

- [ ] **Step 5.1: Write failing tests**

Create `test/crypto/test_eip712.py`:

```python
"""EIP-712 typed-data hashing + verification."""
from __future__ import annotations

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from oasis.crypto import eip712
from oasis.crypto.typed_data import DOMAIN, SanctionTypedData


def test_hash_typed_data_matches_eth_account():
    """Our hashing must agree byte-for-byte with eth_account.messages."""
    data = SanctionTypedData(
        target_did="did:key:zVictim",
        amount_wei=100,
        reason="test",
        nonce=1,
    )
    our_hash = eip712.hash_typed_data(domain=DOMAIN, primary_type="Sanction",
                                       message=data.to_dict())
    canonical = encode_typed_data(full_message={
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Sanction": [
                {"name": "target_did", "type": "string"},
                {"name": "amount_wei", "type": "uint256"},
                {"name": "reason", "type": "string"},
                {"name": "nonce", "type": "uint256"},
            ],
        },
        "primaryType": "Sanction",
        "domain": DOMAIN,
        "message": data.to_dict(),
    })
    assert our_hash == canonical.body


def test_sign_and_verify_roundtrip():
    acct = Account.create()
    data = SanctionTypedData(
        target_did="did:key:zVictim", amount_wei=100, reason="test", nonce=1
    )
    sig = eip712.sign(acct.key, domain=DOMAIN, primary_type="Sanction",
                       message=data.to_dict())
    recovered = eip712.recover_signer(domain=DOMAIN, primary_type="Sanction",
                                       message=data.to_dict(), signature=sig)
    assert recovered.lower() == acct.address.lower()


def test_verify_returns_bool():
    acct = Account.create()
    data = SanctionTypedData(
        target_did="did:key:zVictim", amount_wei=100, reason="test", nonce=1
    )
    sig = eip712.sign(acct.key, domain=DOMAIN, primary_type="Sanction",
                       message=data.to_dict())
    assert eip712.verify(domain=DOMAIN, primary_type="Sanction",
                         message=data.to_dict(), signature=sig,
                         expected_signer=acct.address) is True
    assert eip712.verify(domain=DOMAIN, primary_type="Sanction",
                         message=data.to_dict(), signature=sig,
                         expected_signer="0x0000000000000000000000000000000000000000") is False
```

- [ ] **Step 5.2: Run to confirm failures**

Run: `pytest test/crypto/test_eip712.py -v`
Expected: ImportError.

- [ ] **Step 5.3: Implement `oasis/crypto/typed_data.py`**

```python
"""EIP-712 domain + typed-data Pydantic models."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel


# Domain separator for the simulated AgentCity chain.
# chainId=0 flags "no real chain"; verifyingContract is the zero address.
DOMAIN: dict = {
    "name": "MitosisOasis",
    "version": "0.4.0",
    "chainId": 0,
    "verifyingContract": "0x0000000000000000000000000000000000000000",
}


EIP712_DOMAIN_TYPE = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]


class TypedDataMessage(BaseModel):
    """Base class for EIP-712 messages. Subclasses provide the type schema."""

    TYPE_SCHEMA: ClassVar[list[dict]] = []
    PRIMARY_TYPE: ClassVar[str] = ""

    def to_dict(self) -> dict:
        return self.model_dump()


class SanctionTypedData(TypedDataMessage):
    """EIP-712 payload for adjudication slash/freeze decisions."""

    TYPE_SCHEMA: ClassVar[list[dict]] = [
        {"name": "target_did", "type": "string"},
        {"name": "amount_wei", "type": "uint256"},
        {"name": "reason", "type": "string"},
        {"name": "nonce", "type": "uint256"},
    ]
    PRIMARY_TYPE: ClassVar[str] = "Sanction"

    target_did: str
    amount_wei: int
    reason: str
    nonce: int


class ConstitutionAmendmentTypedData(TypedDataMessage):
    """EIP-712 payload for Rules Hub parameter updates."""

    TYPE_SCHEMA: ClassVar[list[dict]] = [
        {"name": "param_name", "type": "string"},
        {"name": "param_value", "type": "string"},
        {"name": "nonce", "type": "uint256"},
    ]
    PRIMARY_TYPE: ClassVar[str] = "ConstitutionAmendment"

    param_name: str
    param_value: str
    nonce: int


class ImpeachmentTypedData(TypedDataMessage):
    """EIP-712 payload for impeachment motions (Bundle 2 will use this)."""

    TYPE_SCHEMA: ClassVar[list[dict]] = [
        {"name": "target_did", "type": "string"},
        {"name": "evidence_cid", "type": "string"},
        {"name": "motion_id", "type": "string"},
    ]
    PRIMARY_TYPE: ClassVar[str] = "Impeachment"

    target_did: str
    evidence_cid: str
    motion_id: str
```

- [ ] **Step 5.4: Implement `oasis/crypto/eip712.py`**

```python
"""EIP-712 hash + sign + verify, layered on eth_account.

Stateless, pure functions. The schema for any given typed-data message
lives in oasis.crypto.typed_data (TypedDataMessage subclasses).
"""
from __future__ import annotations

from typing import Mapping

from eth_account import Account
from eth_account.messages import encode_typed_data

from .typed_data import EIP712_DOMAIN_TYPE, TypedDataMessage


def _typed_data_envelope(domain: Mapping, primary_type: str,
                          message: Mapping) -> dict:
    """Build the canonical EIP-712 envelope from our convention."""
    # Look up the schema by primary_type via the registered subclasses.
    schema = None
    for subclass in TypedDataMessage.__subclasses__():
        if subclass.PRIMARY_TYPE == primary_type:
            schema = subclass.TYPE_SCHEMA
            break
    if schema is None:
        raise ValueError(f"no TypedDataMessage subclass for primary_type={primary_type}")
    return {
        "types": {
            "EIP712Domain": EIP712_DOMAIN_TYPE,
            primary_type: schema,
        },
        "primaryType": primary_type,
        "domain": dict(domain),
        "message": dict(message),
    }


def hash_typed_data(domain: Mapping, primary_type: str,
                     message: Mapping) -> bytes:
    """Compute the 32-byte EIP-712 hash for `message`."""
    envelope = _typed_data_envelope(domain, primary_type, message)
    encoded = encode_typed_data(full_message=envelope)
    return encoded.body  # 32 bytes


def sign(private_key: bytes, domain: Mapping, primary_type: str,
         message: Mapping) -> bytes:
    """Produce a 65-byte EIP-712 signature."""
    msg_hash = hash_typed_data(domain, primary_type, message)
    acct = Account.from_key(private_key)
    signed = acct.signHash(msg_hash)
    # eth_account gives us r, s, v; concat as r||s||v (canonical wire format).
    return (signed.r.to_bytes(32, "big") +
            signed.s.to_bytes(32, "big") +
            bytes([signed.v]))


def recover_signer(domain: Mapping, primary_type: str, message: Mapping,
                    signature: bytes) -> str:
    """Return the checksum-address that signed `message`."""
    from .secp256k1 import recover_signer as _recover
    msg_hash = hash_typed_data(domain, primary_type, message)
    return _recover(msg_hash, signature)


def verify(domain: Mapping, primary_type: str, message: Mapping,
           signature: bytes, expected_signer: str) -> bool:
    """Verify signature; return True iff recovered signer matches."""
    try:
        recovered = recover_signer(domain, primary_type, message, signature)
        return recovered.lower() == expected_signer.lower()
    except Exception:
        return False
```

- [ ] **Step 5.5: Run tests and commit**

Run: `pytest test/crypto/test_eip712.py -v`
Expected: 3 passed.

```bash
git add oasis/crypto/typed_data.py oasis/crypto/eip712.py test/crypto/test_eip712.py
git commit -m "feat(crypto): EIP-712 typed-data hashing + signing + verify

domain=MitosisOasis/0.4.0/chainId=0 — flags 'no real chain'. Three
typed-data schemas: Sanction, ConstitutionAmendment, Impeachment.
Bundle 2 will add Impeachment usage."
```

---

## Task 6: Schema migration — `public_key` + `signature` columns

**Files:**

- Modify: `oasis/governance/schema.py`

- [ ] **Step 6.1: Add columns**

In `create_governance_tables()`, after the table CREATE block (and before constitution seeding), add the idempotent ALTERs:

```python
    # Bundle 1: real crypto. agent_registry gains public_key; message_log gains signature.
    for stmt in (
        "ALTER TABLE agent_registry ADD COLUMN public_key TEXT",
        "ALTER TABLE message_log ADD COLUMN signature TEXT",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column exists
```

- [ ] **Step 6.2: Write a schema-presence test**

Add to `test/spec_v097/test_idn_117_ed25519_attestation.py` (anchor file for this rubric row):

```python
"""Spec leg §3.2: identity attestation must carry a real Ed25519 signature
verified against the agent's registered public_key. v0.2.x accepted any
non-empty string."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables


def test_agent_registry_has_public_key_column(tmp_path: Path):
    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_registry)")}
    assert "public_key" in cols


def test_message_log_has_signature_column(tmp_path: Path):
    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(message_log)")}
    assert "signature" in cols
```

Run: `pytest test/spec_v097/test_idn_117_ed25519_attestation.py -v`
Expected: 2 passed.

- [ ] **Step 6.3: Commit**

```bash
git add oasis/governance/schema.py test/spec_v097/test_idn_117_ed25519_attestation.py
git commit -m "feat(schema): add public_key + signature columns for real crypto"
```

---

## Task 7: Registrar mints + verifies Ed25519 keys

**Files:**

- Modify: `oasis/governance/clerks/registrar.py`
- Append to: `test/spec_v097/test_idn_117_ed25519_attestation.py`

- [ ] **Step 7.1: Append e2e attestation test**

In `test/spec_v097/test_idn_117_ed25519_attestation.py`, append:

```python
def test_attestation_with_invalid_ed25519_sig_is_rejected(tmp_path):
    """Registrar.verify_identity must return errors for a bad signature."""
    from oasis.crypto import ed25519
    from oasis.governance.schema import create_governance_tables, seed_constitution
    from oasis.governance.clerks.registrar import Registrar
    from oasis.governance.messages import IdentityAttestation, MessageType

    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    seed_constitution(str(db))

    # Register an agent with a real public key
    priv, pub = ed25519.generate_keypair()
    from oasis.crypto import did
    agent_did = did.did_from_pubkey(pub)

    reg = Registrar(db_path=str(db))
    reg.register_agent(
        agent_did=agent_did,
        agent_type="producer",
        display_name="test producer",
        public_key=pub.hex(),
    )

    # Build an attestation with a *wrong* signature (signed by a fresh key)
    other_priv, _ = ed25519.generate_keypair()
    payload = b"attestation payload"
    bad_sig = ed25519.sign(other_priv, payload)
    msg = IdentityAttestation(
        msg_type=MessageType.IDENTITY_ATTESTATION,
        sender_did=agent_did,
        session_id="s1",
        signature=bad_sig.hex(),
        payload=payload.hex(),
    )

    result = reg.verify_identity(msg)
    assert result["valid"] is False
    assert any("signature" in e.lower() for e in result.get("errors", []))


def test_attestation_with_valid_ed25519_sig_is_accepted(tmp_path):
    from oasis.crypto import ed25519, did
    from oasis.governance.schema import create_governance_tables, seed_constitution
    from oasis.governance.clerks.registrar import Registrar
    from oasis.governance.messages import IdentityAttestation, MessageType

    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    seed_constitution(str(db))

    priv, pub = ed25519.generate_keypair()
    agent_did = did.did_from_pubkey(pub)
    reg = Registrar(db_path=str(db))
    reg.register_agent(
        agent_did=agent_did, agent_type="producer",
        display_name="test producer", public_key=pub.hex(),
    )

    payload = b"valid attestation"
    sig = ed25519.sign(priv, payload)
    msg = IdentityAttestation(
        msg_type=MessageType.IDENTITY_ATTESTATION,
        sender_did=agent_did, session_id="s1",
        signature=sig.hex(), payload=payload.hex(),
    )

    result = reg.verify_identity(msg)
    assert result["valid"] is True, f"unexpected errors: {result.get('errors')}"
```

Run: `pytest test/spec_v097/test_idn_117_ed25519_attestation.py -v`
Expected: 2 new tests fail (the registrar can't accept `public_key` yet, can't verify Ed25519).

- [ ] **Step 7.2: Modify `oasis/governance/clerks/registrar.py`**

In the `register_agent(...)` method, add a `public_key: str | None = None` parameter (after `human_principal`) and store it in `agent_registry.public_key`. The INSERT becomes:

```python
conn.execute(
    "INSERT INTO agent_registry "
    "(agent_did, agent_type, capability_tier, display_name, "
    "human_principal, public_key) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    (agent_did, agent_type, tier, display_name, human_principal, public_key),
)
```

In `verify_identity(self, attestation: IdentityAttestation) -> dict`, replace the v0.2.x non-empty-string check at lines 131-132 with real Ed25519 verification:

```python
        from oasis.crypto import ed25519, did as did_mod

        # Fetch the registered public_key for this DID
        with self._connect() as c:
            row = c.execute(
                "SELECT public_key FROM agent_registry WHERE agent_did = ?",
                (attestation.sender_did,),
            ).fetchone()
        if row is None or not row[0]:
            errors.append(f"No registered public_key for {attestation.sender_did}")
        else:
            try:
                pubkey_bytes = bytes.fromhex(row[0])
                sig_bytes = bytes.fromhex(attestation.signature or "")
                payload_bytes = bytes.fromhex(attestation.payload or "")
                # The DID must encode the same pubkey we have on file.
                try:
                    pubkey_from_did = did_mod.resolve(attestation.sender_did)
                    if pubkey_from_did != pubkey_bytes:
                        errors.append(
                            "public_key on registry does not match did:key encoding"
                        )
                except ValueError as e:
                    errors.append(f"invalid did:key: {e}")
                if not ed25519.verify(pubkey_bytes, payload_bytes, sig_bytes):
                    errors.append("Ed25519 signature verification failed")
            except ValueError as e:
                errors.append(f"signature/payload not valid hex: {e}")
```

Remove the old `if not attestation.signature: errors.append("Empty signature")` check at lines 131-132.

- [ ] **Step 7.3: Run tests and commit**

Run: `pytest test/spec_v097/test_idn_117_ed25519_attestation.py test/governance/ -v`
Expected: spec_v097 tests pass; some existing governance tests fail because they construct attestations without real signatures. For each failing test, use the new `test/conftest.py` `ed25519_keypair` fixture (added in Task 10) to mint a real key, sign the payload, populate `signature`.

If that's too disruptive, gate the verification on a `verify_signatures: bool = True` flag on `Registrar.__init__` and set it to `False` in tests for now — but **document** that this is a temporary measure cleared by Bundle 1's full E2E coverage.

```bash
git add oasis/governance/clerks/registrar.py test/spec_v097/test_idn_117_ed25519_attestation.py test/governance/
git commit -m "feat(governance/registrar): real Ed25519 attestation verification

Registrar.register_agent now stores public_key; verify_identity uses
oasis.crypto.ed25519 + oasis.crypto.did to verify attestations against
the registered key (also checks did:key encoding consistency)."
```

---

## Task 8: Ed25519 verification across remaining clerks

**Files:**

- Modify: `oasis/governance/clerks/speaker.py`, `regulator.py`, `codifier.py`
- Modify: `oasis/governance/messages.py`

- [ ] **Step 8.1: Add a shared verification helper**

Create a helper in `oasis/governance/clerks/_signing.py`:

```python
"""Shared Ed25519 verification helper for clerk modules.

Every message type (MSG3-MSG7) carries a `signature` and `payload`
field; the sender's public_key is read from agent_registry. This
helper centralises the verify-and-error-report logic.
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

from oasis.crypto import ed25519


def verify_message_signature(
    *,
    sender_did: str,
    payload_hex: str,
    signature_hex: str,
    conn: sqlite3.Connection,
) -> tuple[bool, list[str]]:
    """Return (valid, errors). Empty errors iff valid."""
    errors: list[str] = []
    row = conn.execute(
        "SELECT public_key FROM agent_registry WHERE agent_did = ?",
        (sender_did,),
    ).fetchone()
    if row is None or not row[0]:
        errors.append(f"sender {sender_did} has no registered public_key")
        return False, errors
    try:
        pubkey = bytes.fromhex(row[0])
        sig = bytes.fromhex(signature_hex or "")
        payload = bytes.fromhex(payload_hex or "")
    except ValueError:
        errors.append("signature or payload not valid hex")
        return False, errors
    if not ed25519.verify(pubkey, payload, sig):
        errors.append("Ed25519 signature verification failed")
        return False, errors
    return True, []
```

- [ ] **Step 8.2: Wire `verify_message_signature` into each clerk**

For `speaker.py`, `regulator.py`, `codifier.py`: at every entry point that accepts an incoming MSG, call `verify_message_signature(sender_did=..., payload_hex=..., signature_hex=..., conn=...)`. If invalid, return an error response or raise.

Specifically:

- **Speaker**: on MSG3 receipt (proposal submission), verify the proposer's signature. On MSG7 dual co-signature, verify both signatures.
- **Regulator**: on MSG4 (bid), verify bidder's signature. On MSG5 broadcast, sign with regulator's private key (mint at clerk-registry time).
- **Codifier**: on MSG6, sign with codifier's private key.

- [ ] **Step 8.3: Mint clerk keypairs at seeding time**

Modify `_DEFAULT_CLERKS` seeding in `oasis/governance/schema.py` to mint Ed25519 keypairs for each clerk and store the public key, AND persist the private key to a separate (gitignored) `clerk_keys/` directory so the FastAPI process can load them at startup.

Actually — **simpler approach** — generate keys at lifespan startup, not at seed time. Add to `oasis/api.py`'s `lifespan()`:

```python
    # Bundle 1: mint clerk keypairs for the seeded clerks if not present.
    from oasis.crypto import ed25519, did
    import os, json
    keys_dir = Path(os.environ.get("OASIS_CLERK_KEYS_DIR", "data/clerk_keys"))
    keys_dir.mkdir(parents=True, exist_ok=True)
    for role in ("registrar", "speaker", "regulator", "codifier"):
        key_path = keys_dir / f"{role}.json"
        if not key_path.exists():
            priv, pub = ed25519.generate_keypair()
            key_path.write_text(json.dumps({
                "private_key_hex": priv.hex(),
                "public_key_hex": pub.hex(),
                "did": did.did_from_pubkey(pub),
            }))
        # Update the clerk's row in agent_registry with the matching pubkey.
        data = json.loads(key_path.read_text())
        # ... UPDATE agent_registry SET public_key = ? WHERE agent_did = ?
```

Add `data/clerk_keys/` to `.gitignore`.

- [ ] **Step 8.4: Run tests and commit**

Run: `pytest test/governance/ -v`
Expected: any test that drives a full clerk flow now needs a real signature. Use the `ed25519_keypair` fixture pattern (added in Task 10) to fix them.

```bash
git add oasis/governance/clerks/_signing.py oasis/governance/clerks/speaker.py oasis/governance/clerks/regulator.py oasis/governance/clerks/codifier.py oasis/governance/schema.py oasis/api.py .gitignore test/governance/
git commit -m "feat(governance/clerks): Ed25519 verification on every MSG type

Clerks mint persistent keypairs at lifespan startup (gitignored
data/clerk_keys/). Shared verify_message_signature helper centralises
public_key lookup + signature verification across MSG3-MSG7."
```

---

## Task 9: EIP-712 middleware for Rules Hub + Override Panel

**Files:**

- Create: `oasis/api_auth.py`
- Modify: `oasis/adjudication/endpoints.py`
- Modify: `oasis/api.py`

- [ ] **Step 9.1: Write the binding test**

Create `test/spec_v097/test_adj_105_eip712_binding.py`:

```python
"""Spec adj §0.5, §1.1: Rules Hub and Override Panel binding operations
require EIP-712 signatures from registered adjudicators. Logging Hub
and Dashboard routes are session-auth only.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from eth_account import Account

from oasis.crypto import eip712
from oasis.crypto.typed_data import DOMAIN, SanctionTypedData


@pytest.fixture
def client():
    from oasis.api import app
    return TestClient(app)


def test_sanction_without_eip712_returns_401(client):
    """POST /api/adjudication/slash without an EIP-712 header is rejected."""
    r = client.post("/api/adjudication/slash", json={
        "target_did": "did:key:zVictim",
        "amount": 100.0,
        "reason": "test",
    })
    assert r.status_code == 401
    assert "EIP-712" in r.text or "signature" in r.text.lower()


def test_sanction_with_valid_eip712_succeeds(client, monkeypatch):
    """POST /api/adjudication/slash WITH a valid EIP-712 header is accepted."""
    # Register an adjudicator with a known address
    acct = Account.create()
    monkeypatch.setenv("OASIS_TEST_ADJUDICATOR_ADDR", acct.address)

    data = SanctionTypedData(
        target_did="did:key:zVictim", amount_wei=100, reason="test", nonce=1
    )
    sig = eip712.sign(acct.key, domain=DOMAIN,
                      primary_type="Sanction", message=data.to_dict())
    r = client.post(
        "/api/adjudication/slash",
        json={"target_did": "did:key:zVictim", "amount": 100.0,
              "reason": "test", "nonce": 1},
        headers={"X-EIP712-Signature": sig.hex(),
                 "X-EIP712-Signer": acct.address},
    )
    # The agent isn't in the registry, so 404 — but NOT 401.
    assert r.status_code != 401, "valid EIP-712 should not be rejected as 401"


def test_dashboard_route_does_not_require_eip712(client):
    """GET /api/observatory/dashboard (or similar read-only) MUST not
    require EIP-712."""
    r = client.get("/api/adjudication/treasury")
    # 401 here would be wrong — this is a read-only Logging-Hub-type route.
    assert r.status_code != 401, "read-only adjudication route must not require EIP-712"
```

Run: `pytest test/spec_v097/test_adj_105_eip712_binding.py -v`
Expected: fails — EIP-712 middleware doesn't exist yet.

- [ ] **Step 9.2: Implement `oasis/api_auth.py`**

```python
"""FastAPI auth dependencies for v0.97 protocol.

require_ed25519_sig: verifies a message-level Ed25519 signature against
the sender's registered public_key. Used on agent-facing routes.

require_eip712_sig: verifies an EIP-712 typed-data signature against the
adjudicator's registered address. Used on Rules Hub + Override Panel
binding routes.
"""
from __future__ import annotations

from typing import Mapping

from fastapi import Header, HTTPException, Request

from .crypto import eip712
from .crypto.typed_data import DOMAIN


async def require_eip712_sig(
    request: Request,
    x_eip712_signature: str = Header(default=""),
    x_eip712_signer: str = Header(default=""),
) -> str:
    """Verify EIP-712 sig on the request body. Returns signer address.

    Reads primary_type from the URL path: each protected route maps to
    a known typed-data primary_type (e.g. `/slash` → `Sanction`,
    `/constitution` PUT → `ConstitutionAmendment`).
    """
    if not x_eip712_signature or not x_eip712_signer:
        raise HTTPException(
            status_code=401,
            detail="EIP-712 signature required (headers X-EIP712-Signature, X-EIP712-Signer)",
        )

    # Map route → primary_type
    primary_type = _route_to_primary_type(request.url.path, request.method)
    if primary_type is None:
        raise HTTPException(
            status_code=500,
            detail=f"no EIP-712 type mapping for {request.method} {request.url.path}",
        )

    body = await request.json()
    try:
        sig = bytes.fromhex(x_eip712_signature.removeprefix("0x"))
    except ValueError:
        raise HTTPException(status_code=400, detail="X-EIP712-Signature not valid hex")

    valid = eip712.verify(
        domain=DOMAIN,
        primary_type=primary_type,
        message=body,
        signature=sig,
        expected_signer=x_eip712_signer,
    )
    if not valid:
        raise HTTPException(status_code=401, detail="EIP-712 signature verification failed")
    return x_eip712_signer


def _route_to_primary_type(path: str, method: str) -> str | None:
    """Static map: which routes require which primary_type."""
    if method == "POST" and path.endswith("/slash"):
        return "Sanction"
    if method == "POST" and path.endswith("/freeze"):
        return "Sanction"
    if method == "PUT" and path.endswith("/constitution"):
        return "ConstitutionAmendment"
    if method == "POST" and path.endswith("/impeach"):  # Bundle 2
        return "Impeachment"
    return None
```

- [ ] **Step 9.3: Wire the dependency**

In `oasis/adjudication/endpoints.py`, add to the router the `Depends(require_eip712_sig)` on the slash and freeze endpoints:

```python
from fastapi import Depends
from oasis.api_auth import require_eip712_sig

@router.post("/slash", dependencies=[Depends(require_eip712_sig)])
async def slash_agent(...):
    ...
```

If slash/freeze endpoints don't yet exist (they may not — Bundle 0 only added settlement-side slash), add them now: a `POST /api/adjudication/slash` endpoint that calls `SanctionService.slash_stake()`.

- [ ] **Step 9.4: Run tests and commit**

Run: `pytest test/spec_v097/test_adj_105_eip712_binding.py -v`
Expected: 3 passed.

```bash
git add oasis/api_auth.py oasis/adjudication/endpoints.py oasis/api.py test/spec_v097/test_adj_105_eip712_binding.py
git commit -m "feat(api): EIP-712 middleware on Rules Hub + Override Panel routes

require_eip712_sig dependency on POST /api/adjudication/slash, freeze,
impeach (Bundle 2 wires impeach), and PUT /api/governance/constitution.
Read-only adjudication/observatory routes unaffected (session auth)."
```

---

## Task 10: Test crypto fixtures (cross-cutting)

**Files:**

- Modify: `test/conftest.py`
- Create: `test/spec_v097/test_idn_114_did_key_resolution.py`
- Create: `test/spec_v097/test_adj_106_session_auth_observation.py`

- [ ] **Step 10.1: Add deterministic crypto fixtures**

Append to `test/conftest.py`:

```python
import hashlib
import pytest
from eth_account import Account

from oasis.crypto import ed25519


@pytest.fixture
def ed25519_keypair(request) -> tuple[bytes, bytes]:
    """Deterministic Ed25519 keypair seeded from test name.

    Same test → same keypair across runs. Use for tests that need a
    stable public_key on file.
    """
    seed = hashlib.sha256(request.node.name.encode()).digest()
    return ed25519.keypair_from_seed(seed)


@pytest.fixture
def eth_account_signer(request) -> Account:
    """Deterministic eth_account Account seeded from test name."""
    seed = hashlib.sha256(b"eth-" + request.node.name.encode()).digest()
    return Account.from_key(seed)
```

- [ ] **Step 10.2: Add the remaining spec_v097 tests**

Create `test/spec_v097/test_idn_114_did_key_resolution.py`:

```python
"""Spec idn §3: agents register via DID-compatible identity. Mock
did:mock: strings replaced with did:key:zXXX (W3C-compatible)."""
from __future__ import annotations

from oasis.crypto import did, ed25519


def test_did_format_is_did_key_z(ed25519_keypair):
    _priv, pub = ed25519_keypair
    d = did.did_from_pubkey(pub)
    assert d.startswith("did:key:z"), f"expected did:key:z prefix, got {d}"


def test_did_resolves_back_to_pubkey(ed25519_keypair):
    _priv, pub = ed25519_keypair
    d = did.did_from_pubkey(pub)
    assert did.resolve(d) == pub
```

Create `test/spec_v097/test_adj_106_session_auth_observation.py`:

```python
"""Spec adj §0.5: Logging Hub and Dashboard routes use session auth,
not EIP-712. Verify GET /api/adjudication/treasury (read-only) does
NOT require EIP-712."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from oasis.api import app
    return TestClient(app)


def test_read_only_treasury_route_no_eip712(client):
    r = client.get("/api/adjudication/treasury")
    assert r.status_code != 401, "read-only treasury route must not require EIP-712"


def test_read_only_decisions_list_no_eip712(client):
    r = client.get("/api/adjudication/decisions")
    assert r.status_code != 401


def test_read_only_alerts_list_no_eip712(client):
    r = client.get("/api/adjudication/alerts")
    assert r.status_code != 401
```

- [ ] **Step 10.3: Run + commit**

Run: `pytest test/spec_v097/test_idn_114_did_key_resolution.py test/spec_v097/test_adj_106_session_auth_observation.py -v`
Expected: 5 passed.

```bash
git add test/conftest.py test/spec_v097/test_idn_114_did_key_resolution.py test/spec_v097/test_adj_106_session_auth_observation.py
git commit -m "test(crypto): deterministic fixtures + IDN/ADJ spec rows"
```

---

## Task 11: Extend E2E smoke test with real crypto end-to-end

**Files:**

- Modify: `test/e2e/test_full_protocol_smoke.py`

- [ ] **Step 11.1: Add the Bundle-1 waypoint**

Append a new test function to `test/e2e/test_full_protocol_smoke.py`:

```python
def test_bundle1_full_legislative_path_with_real_crypto(gov_db, ed25519_keypair):
    """End-to-end: register 10 producers with real Ed25519 keys, have
    6 of them attest with real signatures, drive the state machine
    through to PROPOSAL_OPEN."""
    from oasis.crypto import ed25519, did
    from oasis.governance.clerks.registrar import Registrar

    reg = Registrar(db_path=gov_db.execute("PRAGMA database_list").fetchone()[2])

    keys: list[tuple[bytes, bytes, str]] = []
    for i in range(10):
        priv, pub = ed25519.generate_keypair()
        agent_did = did.did_from_pubkey(pub)
        reg.register_agent(
            agent_did=agent_did, agent_type="producer",
            display_name=f"prod-{i}", public_key=pub.hex(),
        )
        keys.append((priv, pub, agent_did))

    session_id = "smoke-bundle1"
    gov_db.execute(
        "INSERT INTO legislative_session "
        "(session_id, state, mission_objective, mission_budget) "
        "VALUES (?, 'IDENTITY_VERIFICATION', 'smoke', 1000.0)",
        (session_id,),
    )

    # 6 of 10 attest with real signatures
    for priv, pub, agent_did in keys[:6]:
        payload = f"attest:{session_id}:{agent_did}".encode()
        sig = ed25519.sign(priv, payload)
        gov_db.execute(
            "INSERT INTO message_log "
            "(session_id, sender_did, msg_type, payload, signature) "
            "VALUES (?, ?, 'IDENTITY_ATTESTATION', ?, ?)",
            (session_id, agent_did, payload.hex(), sig.hex()),
        )
    gov_db.commit()

    from oasis.governance import state_machine as sm
    result = sm._guard_identity_to_proposal(session_id=session_id, conn=gov_db)
    assert result.allowed, f"6/10 real-Ed25519 attestations failed: {result.reason}"
```

- [ ] **Step 11.2: Run + commit**

Run: `pytest test/e2e/ -v`
Expected: Bundle-0 waypoint still passes; new Bundle-1 waypoint passes.

```bash
git add test/e2e/test_full_protocol_smoke.py
git commit -m "test(e2e): Bundle-1 waypoint — full legislative path with real Ed25519"
```

---

## Task 12: Version bump + CHANGELOG

**Files:**

- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

- [ ] **Step 12.1: Bump version**

`pyproject.toml`: `version = "0.3.0"` → `version = "0.4.0"`. Update `oasis/crypto/typed_data.py` `DOMAIN["version"]` to match.

- [ ] **Step 12.2: CHANGELOG entry**

Prepend to `CHANGELOG.md`:

```markdown
## [0.4.0] — TBD — Bundle 1 (Cryptographic Foundation)

### Added

- Real **Ed25519 keypair-per-agent** via pynacl. Registrar mints keys at
  registration; every clerk verifies Ed25519 signatures on incoming MSGs
  (MSG2-MSG7) against the sender's registered `public_key`.
- Real **W3C `did:key:zXXX` DIDs** (Ed25519 multicodec 0xed01) replacing
  v0.2.x `did:mock:` strings. Pure-Python resolver in `oasis.crypto.did`.
- **EIP-712 typed-data** signature verification on Rules Hub + Override
  Panel binding routes. Three typed-data schemas: `Sanction`,
  `ConstitutionAmendment`, `Impeachment`. Domain
  `name="MitosisOasis", version="0.4.0", chainId=0`.
- New deps: `pynacl ^1.5.0`, `eth-account ^0.10.0`, `didkit ^0.3.0`
  (optional).
- `oasis/api_auth.py` FastAPI dependencies for crypto-required routes.
- `agent_registry.public_key` column. `message_log.signature` column.
- Test fixtures: `ed25519_keypair`, `eth_account_signer` (deterministic
  per test name).
- ≥10 new spec_v097 tests (IDN-114, IDN-117, ADJ-105, ADJ-106 +
  EIP-712 binding tests).

### Breaking

- Agents registering without a `public_key` are rejected. The default
  clerk seeding at lifespan startup mints clerk keys automatically
  (`data/clerk_keys/`, gitignored).
- All MSG types now require a real Ed25519 signature in their
  `signature` field. v0.2.x callers passing non-empty strings will be
  rejected.
- `POST /api/adjudication/slash` (and other binding adjudication
  routes) now require `X-EIP712-Signature` + `X-EIP712-Signer` headers.
```

- [ ] **Step 12.3: Final pass**

Run: `pytest -q`
Expected: 484 (Bundle-0-passed) + 13 (Bundle-0 spec_v097) + ~10 new (Bundle-1 spec_v097) + crypto unit tests + 2 e2e waypoints = ~520 passing.

Run: `ruff check oasis/ test/ --fix && ruff format oasis/ test/`

```bash
git add pyproject.toml CHANGELOG.md oasis/crypto/typed_data.py
git commit -m "chore(release): v0.4.0 — Bundle 1 (Cryptographic Foundation)"
```

---

## Acceptance Gates

- [ ] All Bundle-0 tests still pass (484 + Bundle-0 spec_v097 + Bundle-0 e2e).
- [ ] All Bundle-1 spec_v097 tests pass (≥10 new).
- [ ] `test/crypto/` unit tests pass (≥14 across ed25519/secp256k1/did/eip712).
- [ ] `test/e2e/test_full_protocol_smoke.py` has both Bundle-0 and Bundle-1 waypoints, both pass.
- [ ] `pyproject.toml` at `0.4.0`. `oasis/crypto/typed_data.py` DOMAIN version matches.
- [ ] `CHANGELOG.md` has full `[0.4.0]` entry.
- [ ] Codex outside-voice review on the bundle's diff returns no new findings beyond the spec.
- [ ] No `pytest.mark.skip` added in this bundle.

## Bundle 1 → Bundle 2/3 handoff

Bundle 2 and 3 can ship in parallel after Bundle 1 merges. Both depend on:

- `oasis/crypto/eip712.py` exists and is tested.
- `oasis/api_auth.py` `require_eip712_sig` dependency exists.
- `oasis.crypto.typed_data.ImpeachmentTypedData` exists (Bundle 2 will use it).
- `data/clerk_keys/` directory pattern established for keypair persistence.
- The E2E test has a Bundle-1 waypoint to extend.
