import os
from pathlib import Path

from dotenv import load_dotenv


ENV_FILE = Path(
    os.getenv("GITLAB_MIGRATOR_ENV_FILE", Path.cwd() / ".env")
).expanduser()

load_dotenv(ENV_FILE)

SOURCE_URL = os.getenv("SOURCE_URL")
SOURCE_TOKEN = os.getenv("SOURCE_TOKEN")
SOURCE_GROUP = os.getenv("SOURCE_GROUP")

DEST_URL = os.getenv("DEST_URL")
DEST_TOKEN = os.getenv("DEST_TOKEN")
DEST_ROOT_GROUP = os.getenv("DEST_ROOT_GROUP")


def validate():
    required = [
        "SOURCE_URL",
        "SOURCE_TOKEN",
        "SOURCE_GROUP",
        "DEST_URL",
        "DEST_TOKEN",
        "DEST_ROOT_GROUP",
    ]

    missing = [key for key in required if not os.getenv(key)]

    if missing:
        raise RuntimeError(
            f"Missing configuration variables (loaded {ENV_FILE}):\n"
            + "\n".join(missing)
        )
