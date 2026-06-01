"""Pytest fixtures for audio tests.

Automatically generates test audio files if they don't exist.
"""

import os
import pytest
from pathlib import Path


def generate_fixtures_if_missing():
    """Generate test audio fixtures if they don't exist."""
    fixtures_dir = Path(__file__).parent

    # Check if fixtures exist
    sine_file = fixtures_dir / "test_sine_440hz.wav"
    if not sine_file.exists():
        # Import and run the generator
        from .generate_test_audio import generate_test_fixtures
        generate_test_fixtures()


# Generate fixtures when this module is loaded
generate_fixtures_if_missing()
