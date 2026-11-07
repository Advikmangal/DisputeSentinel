"""Local entry point; Render production startup seeds the merchant automatically."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.seed_merchant import main, seed  # re-export seed for existing callers/tests

if __name__ == "__main__":
    raise SystemExit(main())
