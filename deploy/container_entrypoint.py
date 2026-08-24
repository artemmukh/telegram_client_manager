from __future__ import annotations

import os
from pathlib import Path

from deploy.runtime_assets import provision_runtime_assets

RUNTIME_SEED_ROOT = Path("/opt/runtime-seed")
RUNTIME_DATA_ROOT = Path("/app/data")


def main() -> None:
    provision_runtime_assets(RUNTIME_SEED_ROOT, RUNTIME_DATA_ROOT)
    os.execvp("python", ["python", "-m", "bot.run"])


if __name__ == "__main__":
    main()
