# SPDX-License-Identifier: Apache-2.0
"""Smoke tests: verify that nest-plugins-reference imports correctly."""


def test_nest_plugins_reference_imports() -> None:
    """Importing nest_plugins_reference should succeed and expose a version string."""
    import nest_plugins_reference

    assert nest_plugins_reference.__version__ == "0.1.1"
