# SPDX-License-Identifier: Apache-2.0
"""Pytest configuration for ``scripts/`` tests.

Makes the project root importable so tests can ``from scripts.judge import ...``.

Example::

    # No-op for the user; pytest picks this up automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
