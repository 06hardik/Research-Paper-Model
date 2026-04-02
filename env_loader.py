"""Lightweight .env loader for local development.

This keeps the service self-contained without requiring python-dotenv.
Existing environment variables always win over values from the file.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(env_path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ if present."""
    path = env_path or Path(__file__).with_name(".env")
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        os.environ[key] = value


load_env_file()