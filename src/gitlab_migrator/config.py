from dotenv import load_dotenv
import os

load_dotenv(os.getenv("GITLAB_MIGRATOR_ENV_FILE") or None)

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

    missing = [
        key
        for key in required
        if not os.getenv(key)
    ]

    if missing:
        raise RuntimeError(
            "Missing .env variables:\n"
            + "\n".join(missing)
        )
