from pathlib import Path
import subprocess
import sys


def test_application_imports_in_a_fresh_interpreter():
    """Catch import-time failures before Uvicorn tries to start the app."""
    backend_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
