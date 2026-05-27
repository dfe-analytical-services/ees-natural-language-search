import os
import json
from pathlib import Path


def load_local_settings():
    if os.getenv("WEBSITE_INSTANCE_ID"):
        return

    try:
        base_dir = Path(__file__).resolve().parent.parent

        settings_path = base_dir / "local.settings.json"

        with open(settings_path) as f:
            data = json.load(f)

        for key, value in data.get("Values", {}).items():
            os.environ.setdefault(key, value)

    except FileNotFoundError:
        pass