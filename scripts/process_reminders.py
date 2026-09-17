"""Compatibility wrapper for the backend's one-shot process-reminders command."""
import os
from pathlib import Path
import sys


if __name__ == "__main__":
    backend = Path(__file__).resolve().parents[1] / "backend"
    sys.path.insert(0, str(backend))
    os.chdir(backend)
    from app.commands.process_reminders import main

    raise SystemExit(main())
