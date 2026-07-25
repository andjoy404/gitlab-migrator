import shutil
import subprocess
import time
import re

import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .config import (
    SOURCE_TOKEN,
    DEST_TOKEN,
)

WORKSPACE = Path(os.getenv("GITLAB_MIGRATOR_WORKSPACE_DIR", "workspace"))
WORKSPACE.mkdir(exist_ok=True)


# ==========================================================
# Helpers
# ==========================================================

def redact_credentials(value):
    """Hide URL user-info (for example, OAuth tokens) in terminal output."""

    return re.sub(
        r"(https?://)[^/@\s]+@",
        r"\1***@",
        str(value),
    )


def print_command_output(result):
    """Print subprocess output without exposing credentials embedded in URLs."""

    for output in (result.stdout, result.stderr):
        if output:
            print(redact_credentials(output), end="")


def authenticated_url(url, token):

    parsed = urlparse(url)

    return urlunparse(
        (
            parsed.scheme,
            f"oauth2:{token}@{parsed.netloc}",
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


# ----------------------------------------------------------

def run(
    cmd,
    cwd=None,
    retries=3,
):

    for attempt in range(1, retries + 1):

        result = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
        )

        print_command_output(result)

        if result.returncode == 0:
            return

        if attempt < retries:

            print(
                f"Retry {attempt}/{retries}..."
            )

            time.sleep(3)

            continue

        command_output = "\n".join(
            output.strip()
            for output in (result.stdout, result.stderr)
            if output and output.strip()
        )

        raise RuntimeError(
            f"Git command failed ({result.returncode})"
            + (
                "\n"
                + redact_credentials(command_output)
                if command_output
                else ""
            )
        )


# ----------------------------------------------------------

def repo_name(repo_url):

    return Path(repo_url).name


# ----------------------------------------------------------

def local_repo(repo_url):

    return WORKSPACE / repo_name(repo_url)

# ----------------------------------------------------------

def disable_mirror_push(repo):

    try:
        run(
            [
                "git",
                "config",
                "--unset",
                "remote.origin.mirror",
            ],
            cwd=repo,
        )
    except Exception:
        pass

# ==========================================================
# Clone / Update
# ==========================================================

def clone_or_update(source_repo):

    repo = local_repo(source_repo)

    source_repo = authenticated_url(
        source_repo,
        SOURCE_TOKEN,
    )

    #
    # Existing mirror
    #

    if repo.exists():

        print(
            f"Updating {repo.name}"
        )

        run(
            [
                "git",
                "remote",
                "set-url",
                "origin",
                source_repo,
            ],
            cwd=repo,
        )

        #
        # Some repositories have no HEAD.
        #

        try:

            run(
                [
                    "git",
                    "fetch",
                    "--prune",
                    "origin",
                ],
                cwd=repo,
            )

        except Exception as e:

            if "HEAD" in str(e):

                print(
                    "Repository has no HEAD, skipping fetch."
                )

            else:

                raise

        return repo

    #
    # New mirror
    #

    print(
        f"Cloning {repo.name}"
    )

    run(
        [
            "git",
            "clone",
            "--mirror",
            source_repo,
            str(repo),
        ]
    )

    disable_mirror_push(repo)

    return repo

# ==========================================================
# Cleanup old destination refs
# ==========================================================

def cleanup_hidden_refs(repo):

    try:

        refs = subprocess.check_output(
            [
                "git",
                "for-each-ref",
                "--format=%(refname)",
                "refs/remotes/destination",
            ],
            cwd=repo,
            text=True,
        ).splitlines()

        if refs:

            print("Cleaning old destination refs...")

        for ref in refs:

            run(
                [
                    "git",
                    "update-ref",
                    "-d",
                    ref,
                ],
                cwd=repo,
            )

    except Exception:

        #
        # No destination refs
        #

        pass

# ==========================================================
# Push
# ==========================================================

def push(
    repo,
    source_repo,
    destination_repo,
):

    source_repo = authenticated_url(
        source_repo,
        SOURCE_TOKEN,
    )

    destination_repo = authenticated_url(
        destination_repo,
        DEST_TOKEN,
    )

    #
    # Point origin to destination
    #

    run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            destination_repo,
        ],
        cwd=repo,
    )

    try:

        print(
            "Pushing mirror..."
        )

        run(
            [
                "git",
                "push",
                "--prune",
                "origin",
                "+refs/heads/*:refs/heads/*",
                "+refs/tags/*:refs/tags/*",
            ],
            cwd=repo,
        )

    finally:

        #
        # Restore source
        #

        run(
            [
                "git",
                "remote",
                "set-url",
                "origin",
                source_repo,
            ],
            cwd=repo,
        )


# ==========================================================
# Git LFS
# ==========================================================

def push_lfs(
    repo,
    destination_repo,
):

    try:

        subprocess.run(
            [
                "git",
                "lfs",
                "version",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

    except Exception:

        return

    destination_repo = authenticated_url(
        destination_repo,
        DEST_TOKEN,
    )

    #
    # Point origin to destination
    #

    run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            destination_repo,
        ],
        cwd=repo,
    )

    try:

        print(
            "Pushing Git LFS..."
        )

        try:

            run(
                [
                    "git",
                    "lfs",
                    "fetch",
                    "--all",
                ],
                cwd=repo,
            )

            run(
                [
                    "git",
                    "lfs",
                    "push",
                    "--all",
                    "origin",
                ],
                cwd=repo,
            )

        except Exception:

            print(
                "Repository does not use Git LFS."
            )

    finally:

        pass


# ==========================================================
# Public API
# ==========================================================

def mirror(
    source_repo,
    destination_repo,
):

    repo = clone_or_update(
        source_repo,
    )

    push(
        repo,
        source_repo,
        destination_repo,
    )

    push_lfs(
        repo,
        destination_repo,
    )

    #
    # Restore source URL after LFS
    #

    run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            authenticated_url(
                source_repo,
                SOURCE_TOKEN,
            ),
        ],
        cwd=repo,
    )

    print(
        f"âœ“ {repo.name} synchronized"
    )


# ==========================================================
# Workspace
# ==========================================================

def clean_workspace():

    if WORKSPACE.exists():

        shutil.rmtree(
            WORKSPACE,
        )

    WORKSPACE.mkdir(
        exist_ok=True,
    )

