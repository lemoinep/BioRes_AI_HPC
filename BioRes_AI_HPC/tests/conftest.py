from pathlib import Path

import pytest


@pytest.fixture
def worker_path() -> Path:
    path = Path("build/cpp/Release/biores_worker.exe")

    if not path.exists():
        pytest.skip(
            "C++ worker not built. Run: cmake --build build --config Release"
        )

    return path