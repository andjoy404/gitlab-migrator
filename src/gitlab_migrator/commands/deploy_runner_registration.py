#!/usr/bin/env python3
"""Create paused destination runners and register them on their Ubuntu hosts.

The script intentionally never writes runner authentication tokens or SSH
passwords to disk. It asks for SSH credentials once per distinct runner host,
then uses the source runner's Docker volumes as a registration template for
the destination configuration.
"""

import argparse
import base64
import datetime
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

try:
    from .bootstrap import configure_import_path
except ImportError:
    from bootstrap import configure_import_path

configure_import_path()

from gitlab_migrator.config import (
    DEST_ROOT_GROUP,
    DEST_TOKEN,
    DEST_URL,
    SOURCE_GROUP,
    validate,
)
from gitlab_migrator.gitlab_api import GitLabAPI
from gitlab_migrator.paths import output_path


CREATION_ERRORS = output_path("runner_creation_errors.log")
SSH_ERRORS = output_path("runner_ssh_errors.log")
RESULTS_FILE = output_path("runner_deployment_results.json")
SSH_CONNECT_TIMEOUT = os.getenv("RUNNER_SSH_CONNECT_TIMEOUT", "5")
REMOTE_RUNNER_BINARIES = {}
REMOTE_RUNNER_MAJOR_VERSIONS = {}


REMOTE_CONFIG_READER = r'''
import ast
import json
import sys

def value(raw):
    try:
        return ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return raw.strip().strip('"')

result = []
current = None
section = None
pending = None

for raw_line in open(sys.argv[1], encoding="utf-8"):
    line = raw_line.split("#", 1)[0].strip()

    if not line:
        continue

    if pending:
        pending += line
        if "]" not in line:
            continue
        current["docker_volumes"] = value(pending)
        pending = None
        continue

    if line == "[[runners]]":
        current = {
            "name": "",
            "executor": "shell",
            "docker_image": "alpine:latest",
            "docker_volumes": [],
        }
        result.append(current)
        section = None
        continue

    if line == "[runners.docker]":
        section = "docker"
        continue

    if not current or "=" not in line:
        continue

    key, raw_value = (part.strip() for part in line.split("=", 1))
    if key == "name":
        current["name"] = value(raw_value)
    elif key == "executor":
        current["executor"] = value(raw_value)
    elif section == "docker" and key == "image":
        current["docker_image"] = value(raw_value)
    elif section == "docker" and key == "volumes":
        if raw_value.rstrip().endswith("]"):
            current["docker_volumes"] = value(raw_value)
        else:
            pending = raw_value

print(json.dumps(result))
'''


def append_log(filename, entry):
    """Persist one failure immediately so interrupted runs keep progress."""

    record = dict(entry)
    record["recorded_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()

    with open(filename, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, sort_keys=True) + "\n")
        file.flush()
        os.fsync(file.fileno())


def load_results(results_file):
    if not results_file.exists():
        return []

    results = json.loads(results_file.read_text(encoding="utf-8"))

    if not isinstance(results, list):
        raise RuntimeError(f"{results_file} must contain a JSON list")

    return results


def checkpoint_results(results_file, results):
    """Atomically save successful deployments after every runner."""

    temporary = results_file.with_name(results_file.name + ".tmp")

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    temporary.replace(results_file)


def command_result(command):
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
    )


def ssh_base(host, user, key, port, control_path):
    command = [
        "ssh",
        "-p",
        str(port),
        "-S",
        str(control_path),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]

    if key:
        command.extend(["-i", str(key), "-o", "IdentitiesOnly=yes"])

    command.append(f"{user}@{host}")
    return command


def prompt_ssh_credentials(host, default_port, default_user="ubuntu"):
    """Ask for a port, username, and either a private key or SSH password."""

    port_input = input(f"  SSH port for {host} [{default_port}]: ").strip()

    try:
        port = int(port_input) if port_input else default_port
    except ValueError as error:
        raise RuntimeError(f"Invalid SSH port: {port_input}") from error

    if not 1 <= port <= 65535:
        raise RuntimeError(f"SSH port must be between 1 and 65535: {port}")

    user = (
        input(f"  SSH username for {host} [{default_user}]: ").strip()
        or default_user
    )
    key_input = input(
        "  Private key path (leave blank to enter SSH password): "
    ).strip()

    if not key_input:
        return user, None, port

    key = Path(key_input).expanduser()

    if not key.is_file():
        raise RuntimeError(f"SSH private key not found: {key}")

    return user, key, port


def open_ssh_master(
    host,
    user,
    key,
    port,
    control_path,
    *,
    interactive,
    hard_timeout=None,
):
    """Authenticate and keep one reusable SSH connection open."""

    command = [
        "ssh",
        "-M",
        "-S",
        str(control_path),
        "-p",
        str(port),
        "-o",
        "ControlPersist=yes",
        "-o",
        f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]

    if not interactive:
        command.extend(["-o", "BatchMode=yes"])

    if key:
        command.extend(["-i", str(key), "-o", "IdentitiesOnly=yes"])
    elif interactive:
        command.extend([
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "PubkeyAuthentication=no",
        ])

    command.extend(["-N", "-f", f"{user}@{host}"])

    if interactive:
        print(
            f"  Authenticating as {user}@{host} on port {port}...",
            flush=True,
        )

    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=not interactive,
            timeout=hard_timeout if not interactive else None,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"SSH connection timed out for {user}@{host} on port {port} "
            f"after {hard_timeout:g} seconds"
        ) from error

    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        message = (
            f"SSH authentication failed for {user}@{host} on port {port}"
        )

        if detail:
            message += f": {detail}"

        raise RuntimeError(message)


def private_keys(keys_dir):
    """Return likely SSH private-key files without assuming a file extension."""

    if not keys_dir.is_dir():
        return []

    keys = []

    for path in sorted(keys_dir.iterdir()):
        if not path.is_file() or path.suffix == ".pub":
            continue

        try:
            with path.open(
                "r",
                encoding="utf-8",
                errors="ignore",
            ) as file:
                first_line = file.readline()
        except OSError:
            continue

        if "PRIVATE KEY" in first_line:
            keys.append(path)

    return keys


def try_default_ssh(host, keys_dir, port, control_path):
    """Try standard users, SSH agent/default identities, and local keys."""

    print(
        f"  Trying default SSH settings on port {port}...",
        flush=True,
    )
    candidates = [None, *private_keys(keys_dir)]
    last_error = None
    timeout = int(SSH_CONNECT_TIMEOUT)
    deadline = time.monotonic() + timeout

    for user in ("ubuntu", "ec2-user"):
        for key in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"Default SSH discovery timed out for {host} on port "
                    f"{port} after {timeout} seconds"
                )
            try:
                open_ssh_master(
                    host,
                    user,
                    key,
                    port,
                    control_path,
                    interactive=False,
                    hard_timeout=remaining,
                )
                method = "ssh_default" if key is None else "private_key"
                key_label = f" with {key}" if key else ""
                print(
                    f"  Connected automatically as {user}@{host}{key_label}",
                    flush=True,
                )
                return user, key, port, control_path, method
            except RuntimeError as error:
                last_error = error

                if any(
                    text in str(error).lower()
                    for text in (
                        "connection timed out",
                        "connection refused",
                        "no route to host",
                    )
                ):
                    raise last_error

    raise last_error or RuntimeError("No default SSH credentials available")


def close_ssh_master(host, user, port, control_path):
    subprocess.run(
        [
            "ssh",
            "-S",
            str(control_path),
            "-p",
            str(port),
            "-O",
            "exit",
            f"{user}@{host}",
        ],
        text=True,
        capture_output=True,
    )


def read_source_runner_config(
    host,
    user,
    key,
    port,
    control_path,
    config_path,
    description,
    tag_list,
):
    """Read non-secret executor settings from the existing Runner config."""

    script = base64.b64encode(REMOTE_CONFIG_READER.encode()).decode()
    command = (
        f"echo {shlex.quote(script)} | base64 -d | "
        f"sudo -n python3 - {shlex.quote(config_path)}"
    )
    result = command_result(
        ssh_base(host, user, key, port, control_path) + [command]
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Cannot read config.toml")

    configurations = json.loads(result.stdout)

    if not configurations:
        raise RuntimeError("No runner entries found in config.toml")

    matching = [
        config
        for config in configurations
        if config["name"] == description
    ]

    if len(matching) == 1:
        return matching[0]

    if len(configurations) == 1:
        return configurations[0]

    tags = ", ".join(tag_list or []) or "none"
    print(
        f'  Cannot automatically match source runner "{description}" '
        f"(tags: {tags}).",
        flush=True,
    )
    print("  Select its config.toml entry:", flush=True)

    for index, configuration in enumerate(configurations, start=1):
        details = configuration["executor"]

        if configuration["executor"] == "docker":
            details += f", image: {configuration['docker_image']}"

        print(
            f"    {index}. {configuration['name']} ({details})",
            flush=True,
        )

    while True:
        selection = input(
            "  Selection (number, exact name, or 's' to skip): "
        ).strip()

        if selection.lower() == "s":
            raise RuntimeError("Runner configuration selection skipped")

        named_matches = [
            config
            for config in configurations
            if config["name"] == selection
        ]

        if len(named_matches) == 1:
            selected = named_matches[0]
            print(f"  Selected: {selected['name']}", flush=True)
            return selected

        try:
            selected_index = int(selection) - 1
        except ValueError:
            selected_index = -1

        if 0 <= selected_index < len(configurations):
            selected = configurations[selected_index]
            print(f"  Selected: {selected['name']}", flush=True)
            return selected

        print(
            "  Enter a listed number, exact configuration name, or 's' to skip.",
            flush=True,
        )


def toml_string(value):
    return json.dumps(value)


def docker_template(configuration):
    """Create a minimal template preserving the Docker image and volumes."""

    lines = ["[[runners]]", "[runners.docker]"]
    lines.append(f"image = {toml_string(configuration['docker_image'])}")
    lines.append(
        "volumes = ["
        + ", ".join(toml_string(volume) for volume in configuration["docker_volumes"])
        + "]"
    )
    return "\n".join(lines) + "\n"


def copy_template(host, user, key, port, control_path, template_path):
    remote_path = f"/tmp/gitlab-runner-template-{template_path.name}"
    command = [
        "scp",
        "-P",
        str(port),
        "-o",
        f"ControlPath={control_path}",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]

    if key:
        command.extend(["-i", str(key), "-o", "IdentitiesOnly=yes"])

    command.extend([str(template_path), f"{user}@{host}:{remote_path}"])
    result = command_result(command)

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unable to copy runner template")

    return remote_path


def find_remote_runner_binary(host, user, key, port, control_path):
    """Find GitLab Runner without relying on sudo's restricted secure_path."""

    cache_key = host, user, port
    if cache_key in REMOTE_RUNNER_BINARIES:
        return REMOTE_RUNNER_BINARIES[cache_key]

    command = (
        'runner_path=$(command -v gitlab-runner 2>/dev/null || true); '
        'if [ -n "$runner_path" ] && [ -x "$runner_path" ]; then '
        'printf "%s\\n" "$runner_path"; exit 0; fi; '
        "for runner_path in "
        "/usr/bin/gitlab-runner "
        "/usr/local/bin/gitlab-runner "
        "/opt/gitlab-runner/gitlab-runner "
        "/opt/gitlab-runner/bin/gitlab-runner; do "
        'if [ -x "$runner_path" ]; then printf "%s\\n" "$runner_path"; '
        "exit 0; fi; done; exit 127"
    )
    result = command_result(
        ssh_base(host, user, key, port, control_path) + [command]
    )
    runner_binary = result.stdout.strip()

    if result.returncode != 0 or not runner_binary:
        raise RuntimeError(
            "gitlab-runner executable is not installed on the host or is "
            "not executable. Checked PATH, /usr/bin, /usr/local/bin, and "
            "/opt/gitlab-runner."
        )

    REMOTE_RUNNER_BINARIES[cache_key] = runner_binary
    print(f"  Using remote GitLab Runner: {runner_binary}", flush=True)
    return runner_binary


def remote_runner_major_version(
    host,
    user,
    key,
    port,
    control_path,
    runner_binary,
):
    cache_key = host, user, port
    if cache_key in REMOTE_RUNNER_MAJOR_VERSIONS:
        return REMOTE_RUNNER_MAJOR_VERSIONS[cache_key]

    command = f"{shlex.quote(runner_binary)} --version"
    result = command_result(
        ssh_base(host, user, key, port, control_path) + [command]
    )
    output = "\n".join((result.stdout or "", result.stderr or ""))
    match = re.search(
        r"(?:Version:\s*|version=)(\d+)(?:\.\d+)*",
        output,
        flags=re.IGNORECASE,
    )
    if result.returncode != 0 or not match:
        raise RuntimeError(
            "Cannot determine the remote GitLab Runner version."
        )

    major = int(match.group(1))
    REMOTE_RUNNER_MAJOR_VERSIONS[cache_key] = major
    return major


def register_runner(
    host,
    user,
    key,
    port,
    control_path,
    runner_token,
    description,
    configuration,
):
    """Register a second runner entry without altering the old registration."""

    runner_binary = find_remote_runner_binary(
        host,
        user,
        key,
        port,
        control_path,
    )
    runner_major = remote_runner_major_version(
        host,
        user,
        key,
        port,
        control_path,
        runner_binary,
    )
    token_option = "--token"
    if runner_major < 16:
        token_option = "--registration-token"
        print(
            f"  GitLab Runner {runner_major}.x detected; using the "
            "legacy-compatible authentication-token flag.",
            flush=True,
        )
    command = [
        "sudo",
        "-n",
        runner_binary,
        "register",
        "--non-interactive",
        "--url",
        DEST_URL,
        token_option,
        runner_token,
        "--name",
        description,
        "--executor",
        configuration["executor"],
    ]
    temporary_template = None

    try:
        if configuration["executor"] == "docker":
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".toml",
                delete=False,
                encoding="utf-8",
            ) as file:
                file.write(docker_template(configuration))
                temporary_template = Path(file.name)

            remote_template = copy_template(
                host,
                user,
                key,
                port,
                control_path,
                temporary_template,
            )
            command.extend(["--template-config", remote_template])
            command.extend(["--docker-image", configuration["docker_image"]])

        remote_command = " ".join(shlex.quote(argument) for argument in command)
        result = command_result(
            ssh_base(host, user, key, port, control_path) + [remote_command]
        )

        if result.returncode != 0:
            message = result.stderr.strip() or "gitlab-runner register failed"
            raise RuntimeError(
                message.replace(runner_token, "***")
            )

    finally:
        if temporary_template:
            temporary_template.unlink(missing_ok=True)


def destination_scope(api, runner):
    source_root = SOURCE_GROUP.strip("/")
    source_path = runner["source_scope_path"].strip("/")

    if source_path != source_root and not source_path.startswith(source_root + "/"):
        raise RuntimeError("Runner scope is outside SOURCE_GROUP")

    relative = source_path.removeprefix(source_root).strip("/")
    destination_path = "/".join(
        part for part in (DEST_ROOT_GROUP.strip("/"), relative) if part
    )

    if runner["runner_type"] == "group_type":
        destination = api.find_group(destination_path)
    else:
        destination = api.find_project(destination_path)

    if destination is None:
        raise RuntimeError(f"Destination scope not found: {destination_path}")

    return destination


def create_destination_runner(api, runner):
    destination = destination_scope(api, runner)
    scope_key = "group_id" if runner["runner_type"] == "group_type" else "project_id"
    kwargs = {scope_key: destination["id"]}
    description = (
        runner.get("description")
        or f"runner {runner['source_runner_id']}"
    )

    created = api.create_user_runner(
        runner_type=runner["runner_type"],
        description=description,
        tag_list=runner.get("tag_list"),
        run_untagged=runner.get("run_untagged", False),
        locked=runner.get("locked", False),
        access_level=runner.get("access_level") or "not_protected",
        maximum_timeout=runner.get("maximum_timeout"),
        paused=True,
        **kwargs,
    )

    # Keep it paused even if an older GitLab version ignores paused on create.
    api.pause_runner(created["id"])
    return created


def resume_results(api, results_file):
    results = json.loads(results_file.read_text(encoding="utf-8"))

    for result in results:
        api.resume_runner(result["destination_runner_id"])
        print(f"Resumed runner {result['destination_runner_id']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(output_path("runners.json")))
    parser.add_argument("--keys-dir", default="data/keys")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    validate()
    try:
        ssh_timeout = int(SSH_CONNECT_TIMEOUT)
    except ValueError as error:
        raise RuntimeError(
            "RUNNER_SSH_CONNECT_TIMEOUT must be a positive integer."
        ) from error
    if ssh_timeout < 1:
        raise RuntimeError(
            "RUNNER_SSH_CONNECT_TIMEOUT must be a positive integer."
        )

    print(f"SSH connection timeout: {ssh_timeout} seconds.")
    api = GitLabAPI(DEST_URL, DEST_TOKEN)
    # macOS places its default temporary directory below a long
    # /var/folders/... path. OpenSSH appends a random suffix while opening a
    # master socket, which can exceed the Unix-domain socket path limit.
    control_directory = tempfile.TemporaryDirectory(
        prefix="grs-",
        dir="/tmp",
    )
    master_connections = {}
    manual_ssh_preferences = {}

    try:
        if args.resume:
            resume_results(api, Path(RESULTS_FILE))
            return

        runners = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        keys_dir = Path(args.keys_dir)
        results_file = Path(RESULTS_FILE)
        results = load_results(results_file)
        successful_ids = {
            str(result["source_runner_id"])
            for result in results
            if "source_runner_id" in result
        }
        deployed_this_run = 0
        skipped = 0
        creation_failure_count = 0
        ssh_failure_count = 0

        print(f"Deploying {len(runners)} runners...")

        if successful_ids:
            print(
                f"Loaded {len(successful_ids)} successful runner checkpoints; "
                "they will be skipped."
            )

        print()

        for index, runner in enumerate(runners, start=1):
            runner_id = runner["source_runner_id"]
            ip_address = runner.get("ip_address")
            description = runner.get("description") or f"runner {runner_id}"
            failure_context = {
                "source_runner_id": runner_id,
                "runner_index": index,
                "runner_description": description,
                "runner_tags": runner.get("tag_list") or [],
                "source_scope_path": runner["source_scope_path"],
            }
            print(
                f"[Runner {index}/{len(runners)}] "
                f"{runner['source_scope_path']} - {description} "
                f"({ip_address or 'no IP address'})",
                flush=True,
            )

            if str(runner_id) in successful_ids:
                existing = next(
                    result
                    for result in results
                    if str(result.get("source_runner_id")) == str(runner_id)
                )
                print(
                    "  Skipped: already deployed as destination runner "
                    f"{existing.get('destination_runner_id', 'unknown')}",
                    flush=True,
                )
                skipped += 1
                continue

            if not ip_address:
                append_log(SSH_ERRORS, {
                    **failure_context,
                    "stage": "ssh",
                    "error": "Runner export has no usable IP address",
                })
                ssh_failure_count += 1
                print("  Failed: runner has no usable IP address", flush=True)
                continue

            try:
                connection = master_connections.get(ip_address)

                if connection is None:
                    control_path = (
                        Path(control_directory.name)
                        / f"h{len(master_connections) + 1}"
                    )

                    preference = manual_ssh_preferences.get(ip_address)

                    if preference is not None:
                        user, key, ssh_port = preference
                        print(
                            f"  Reusing manual SSH settings: "
                            f"{user}@{ip_address} port {ssh_port}",
                            flush=True,
                        )
                        open_ssh_master(
                            ip_address,
                            user,
                            key,
                            ssh_port,
                            control_path,
                            interactive=True,
                        )
                        authentication = "private_key" if key else "password"
                        connection = (
                            user,
                            key,
                            ssh_port,
                            control_path,
                            authentication,
                        )
                    else:
                        try:
                            connection = try_default_ssh(
                                ip_address,
                                keys_dir,
                                args.port,
                                control_path,
                            )
                        except RuntimeError as default_error:
                            print(
                                f"  Default SSH failed: {default_error}",
                                flush=True,
                            )
                            print("  Enter SSH settings manually:", flush=True)
                            user, key, ssh_port = prompt_ssh_credentials(
                                ip_address,
                                args.port,
                            )
                            # Remember host/port/user after a failed password
                            # attempt. Passwords are never read or stored.
                            manual_ssh_preferences[ip_address] = (
                                user,
                                key,
                                ssh_port,
                            )
                            open_ssh_master(
                                ip_address,
                                user,
                                key,
                                ssh_port,
                                control_path,
                                interactive=True,
                            )
                            authentication = (
                                "private_key" if key else "password"
                            )
                            connection = (
                                user,
                                key,
                                ssh_port,
                                control_path,
                                authentication,
                            )

                    master_connections[ip_address] = connection

                user, key, ssh_port, control_path, authentication = connection
                configuration = read_source_runner_config(
                    ip_address,
                    user,
                    key,
                    ssh_port,
                    control_path,
                    "/etc/gitlab-runner/config.toml",
                    description,
                    runner.get("tag_list"),
                )

                if not runner.get("description"):
                    description = configuration["name"]
            except Exception as error:
                append_log(SSH_ERRORS, {
                    **failure_context,
                    "ip_address": ip_address,
                    "stage": "ssh_or_configuration",
                    "error": str(error),
                })
                ssh_failure_count += 1
                print(f"  SSH/configuration failed: {error}", flush=True)
                continue

            try:
                runner_to_create = dict(runner)
                runner_to_create["description"] = description
                created = create_destination_runner(api, runner_to_create)
            except Exception as error:
                append_log(CREATION_ERRORS, {
                    **failure_context,
                    "stage": "creation",
                    "error": str(error),
                })
                creation_failure_count += 1
                print(f"  Creation failed: {error}", flush=True)
                continue

            try:
                register_runner(
                    ip_address,
                    user,
                    key,
                    ssh_port,
                    control_path,
                    created["token"],
                    description,
                    configuration,
                )
                result_record = {
                    "source_runner_id": runner_id,
                    "destination_runner_id": created["id"],
                    "ip_address": ip_address,
                    "ssh_port": ssh_port,
                    "user": user,
                    "authentication": authentication,
                    "key": key.name if key else None,
                    "source_config_name": configuration["name"],
                }
                results.append(result_record)
                checkpoint_results(results_file, results)
                successful_ids.add(str(runner_id))
                deployed_this_run += 1
                print(
                    f"  Registered paused runner {created['id']} on {ip_address} "
                    "(checkpoint saved)",
                    flush=True,
                )
            except Exception as error:
                append_log(SSH_ERRORS, {
                    **failure_context,
                    "destination_runner_id": created["id"],
                    "ip_address": ip_address,
                    "stage": "registration",
                    "error": str(error),
                })
                ssh_failure_count += 1
                print(f"  Registration failed: {error}", flush=True)
                try:
                    api.delete_runner(created["id"])
                    print(
                        f"  Removed failed destination runner {created['id']}.",
                        flush=True,
                    )
                except Exception as cleanup_error:
                    append_log(CREATION_ERRORS, {
                        **failure_context,
                        "destination_runner_id": created["id"],
                        "stage": "registration_rollback",
                        "error": str(cleanup_error),
                    })
                    print(
                        f"  Warning: could not remove failed destination "
                        f"runner {created['id']}: {cleanup_error}",
                        flush=True,
                    )

        print(
            f"Deployment complete: {deployed_this_run} newly registered, "
            f"{skipped} previously successful, "
            f"{creation_failure_count + ssh_failure_count} failed."
        )
        print(f"Total successful checkpoints: {len(successful_ids)}")

        if creation_failure_count:
            print(f"Creation failures: {CREATION_ERRORS}")

        if ssh_failure_count:
            print(f"SSH/configuration failures: {SSH_ERRORS}")

    finally:
        for host, connection in master_connections.items():
            user, _, ssh_port, control_path, _ = connection
            close_ssh_master(host, user, ssh_port, control_path)

        control_directory.cleanup()
        api.close()


if __name__ == "__main__":
    main()
