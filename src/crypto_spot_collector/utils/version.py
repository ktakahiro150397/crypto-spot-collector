"""Version information from git repository."""
from pathlib import Path

from git import Repo
from loguru import logger


def get_version_from_git() -> str:
    """
    Get version string from git repository status.
    
    Returns:
        str: Version string in format "{branch_name} ({short_commit_hash})"
        
    Example:
        "main (a1b2c3d)"
        "feature/new-feature (e4f5g6h)"
    """
    try:
        # Get repository root directory (go up from this file to repo root)
        # version.py -> utils -> crypto_spot_collector -> src -> repo_root
        repo_path = Path(__file__).parent.parent.parent.parent
        repo = Repo(repo_path)
        
        # Get current branch name
        branch_name = repo.active_branch.name
        
        # Get short commit hash (first 7 characters)
        commit_hash = repo.head.commit.hexsha[:7]
        
        version = f"{branch_name} ({commit_hash})"
        logger.debug(f"Git version: {version}")
        
        return version
    except Exception as e:
        logger.warning(f"Failed to get git version: {e}")
        # Fallback to a default version if git is not available
        return "unknown (no-git)"
