"""Locations of the optional external Python regression corpora."""
import os
from pathlib import Path

SAMPLE_ROOT = Path(os.environ.get("ORION_PYTHON_SAMPLES", "C:/workspace/OrionParser/parser_sample/python"))
GITHUB_REPOS = (SAMPLE_ROOT / "github" if "ORION_PYTHON_SAMPLES" in os.environ else
                Path(__file__).parent / "fixtures" / "real_world_repos" / "files")
