# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Canonical AgentCity v0.97 spec constants used by production code.

These were previously defined in ``test/spec_v097/conftest.py``, which
made production modules import from ``test/`` — a path not shipped in
the Docker image and therefore a guaranteed runtime crash in production.
This module is the single source of truth; the test conftest re-exports
from here for backward compatibility with existing test imports.
"""

from __future__ import annotations

# Bid-scoring weights (spec exec §1.2).
SPEC_BID_WEIGHT_Q = 0.6  # quality weight
SPEC_BID_WEIGHT_P = 0.4  # price weight
