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
"""ADJ-098 — Rotation policy signature lock.

This test verifies that ``enforce_rotation`` exposes the exact keyword-only
signature contract required by the v0.97 spec.  It MUST be red before the
implementation is written (TDD invariant).
"""

from __future__ import annotations

import inspect

from oasis.adjudication.rotation import enforce_rotation


def test_enforce_rotation_signature() -> None:
    """T6: enforce_rotation parameter order contains the spec contract."""
    sig = inspect.signature(enforce_rotation)
    params = list(sig.parameters.keys())
    assert "adjudicator_did" in params
    assert "decision_type" in params
    assert "max_consecutive" in params
    assert "db_path" in params

    # All parameters must be keyword-only
    for p in sig.parameters.values():
        assert p.kind == inspect.Parameter.KEYWORD_ONLY, (
            f"Parameter {p.name} must be keyword-only, got {p.kind}"
        )
