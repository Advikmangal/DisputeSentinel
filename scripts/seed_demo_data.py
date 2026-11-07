"""Run locally against the replacement Render database using environment settings."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.seed_demo_data import main

if __name__ == "__main__":
    raise SystemExit(main())
