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
"""ADJ-099 — Conflict-of-Interest recusal signature lock.

This test verifies that ``is_conflicted`` exposes the exact keyword-only
signature contract required by the v0.97 spec.  It MUST be red before the
implementation is written (TDD invariant).
"""

from __future__ import annotations

import inspect

from oasis.adjudication.coi import is_conflicted


def test_coi_helper_signature() -> None:
    """T4: is_conflicted parameter order is exactly the spec contract."""
    sig = inspect.signature(is_conflicted)
    params = list(sig.parameters.keys())
    assert params == [
        "adjudicator_did",
        "mission_id",
        "agents_in_mission",
        "gov_db_path",
    ]

    # All parameters must be keyword-only (POSITIONAL_OR_KEYWORD is not acceptable)
    for p in sig.parameters.values():
        assert p.kind == inspect.Parameter.KEYWORD_ONLY, (
            f"Parameter {p.name} must be keyword-only, got {p.kind}"
        )
