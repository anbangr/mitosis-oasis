"""Shared message-signature verification helper.

This module is re-exported from ``oasis.governance.clerks._signing`` so
that test imports remain stable.
"""

from __future__ import annotations

from oasis.governance.clerks._signing import verify_message_signature

__all__ = ["verify_message_signature"]
