"""Pytest configuration and fixtures for all tests.

Automatically generates test audio fixtures on session start.
"""

import os
import sys
import pytest
from pathlib import Path


def pytest_configure(config):
    """Generate test fixtures before running tests."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    sine_file = fixtures_dir / "test_sine_440hz.wav"
    audio_dir = fixtures_dir / "audio"
    pii_audio_file = audio_dir / "conversation_with_name.wav"

    # Add fixtures to path for import
    sys.path.insert(0, str(fixtures_dir))
    try:
        from generate_test_audio import generate_test_fixtures, generate_all_fixtures

        # Generate basic test fixtures if missing
        if not sine_file.exists():
            print("\nGenerating basic test audio fixtures...")
            generate_test_fixtures()

        # Generate PII scenario fixtures if missing
        if not pii_audio_file.exists():
            print("\nGenerating PII audio fixtures...")
            generate_all_fixtures()
    except Exception as e:
        print(f"Warning: Could not generate test fixtures: {e}")
    finally:
        sys.path.pop(0)
