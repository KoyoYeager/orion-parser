#!/usr/bin/env python
"""Run OrionParser without pip install.

Usage:
    python run.py parse example.py
    python run.py analyze --symbols src/
    python run.py langs
"""

import sys
from pathlib import Path

# Add src/ to Python path so orionparser can be imported
sys.path.insert(0, str(Path(__file__).parent / "src"))

from orionparser.cli import main

if __name__ == "__main__":
    main()
