"""Tests for version utility."""
import re

from crypto_spot_collector.utils.version import get_version_from_git


def test_get_version_from_git() -> None:
    """Test that get_version_from_git returns expected format."""
    version = get_version_from_git()
    
    # Version should match pattern: {branch_name} ({7-char-hash})
    # e.g., "main (a1b2c3d)" or "feature/test (e4f5g6h)"
    pattern = r'^.+ \([a-f0-9]{7}\)$'
    
    assert re.match(pattern, version), \
        f"Version '{version}' does not match expected format"
    
    # Should not be the fallback version
    assert version != "unknown (no-git)", \
        "Version should not be the fallback value in a git repository"


def test_version_format() -> None:
    """Test that version contains branch name and commit hash."""
    version = get_version_from_git()
    
    # Version should contain both branch name and commit hash in parentheses
    assert "(" in version and ")" in version, \
        "Version should contain commit hash in parentheses"
    
    # Extract the hash part
    hash_part = version.split("(")[1].rstrip(")")
    
    # Hash should be 7 characters long and hexadecimal
    assert len(hash_part) == 7, \
        f"Commit hash should be 7 characters, got {len(hash_part)}"
    assert all(c in "0123456789abcdef" for c in hash_part), \
        f"Commit hash should be hexadecimal, got '{hash_part}'"
