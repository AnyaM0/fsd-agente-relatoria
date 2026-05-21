from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve Azure Speech and Storage environment variables using the Azure CLI."
    )
    parser.add_argument("--resource-group", required=True, help="Azure resource group name.")
    parser.add_argument("--speech-account", required=True, help="Azure Speech resource name.")
    parser.add_argument("--storage-account", required=True, help="Azure Storage account name.")
    parser.add_argument("--container", required=True, help="Azure Blob container name.")
    parser.add_argument("--subscription", default=None, help="Optional Azure subscription id or name.")
    parser.add_argument(
        "--output",
        default=".env.azure.local",
        help="Output path for the generated env file. Ignored by --check.",
    )
    parser.add_argument(
        "--include-secrets",
        action="store_true",
        help="Also include AZURE_SPEECH_API_KEY in the generated env file.",
    )
    parser.add_argument(
        "--include-storage-key",
        action="store_true",
        help="[Deprecated] Include AZURE_STORAGE_ACCOUNT_KEY. Use managed identity instead.",
    )
    parser.add_argument(
        "--create-container",
        action="store_true",
        help="Create the blob container if it does not exist.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only validate Azure resources and print the env content instead of writing a file.",
    )
    return parser


def _run_az_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["az", *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Azure CLI not found. Install `az` and ensure it is in PATH.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip()
        raise RuntimeError(f"Azure CLI command failed: az {' '.join(args)}\n{stderr}") from exc

    return result.stdout.strip()


def _require_az_login(subscription: str | None) -> dict:
    if subscription:
        _run_az_command(["account", "set", "--subscription", subscription])

    output = _run_az_command(["account", "show", "-o", "json"])
    data = json.loads(output)
    if not data.get("id"):
        raise RuntimeError("Azure CLI is not authenticated. Run `az login` first.")
    return data


def _speech_env(resource_group: str, speech_account: str, include_secrets: bool) -> dict[str, str]:
    speech_raw = _run_az_command(
        [
            "cognitiveservices",
            "account",
            "show",
            "--name",
            speech_account,
            "--resource-group",
            resource_group,
            "-o",
            "json",
        ]
    )
    speech = json.loads(speech_raw)

    env = {
        "AZURE_SPEECH_REGION": speech["location"],
        "AZURE_SPEECH_ENDPOINT": speech["properties"]["endpoint"],
    }

    if include_secrets:
        keys_raw = _run_az_command(
            [
                "cognitiveservices",
                "account",
                "keys",
                "list",
                "--name",
                speech_account,
                "--resource-group",
                resource_group,
                "-o",
                "json",
            ]
        )
        keys = json.loads(keys_raw)
        env["AZURE_SPEECH_API_KEY"] = keys["key1"]

    return env


def _ensure_container(storage_account: str, container: str, create_container: bool) -> None:
    exists_raw = _run_az_command(
        [
            "storage",
            "container",
            "exists",
            "--name",
            container,
            "--account-name",
            storage_account,
            "--auth-mode",
            "login",
            "-o",
            "json",
        ]
    )
    exists = json.loads(exists_raw)["exists"]

    if exists:
        return

    if not create_container:
        raise RuntimeError(
            f"Blob container `{container}` does not exist. Pass --create-container to create it."
        )

    _run_az_command(
        [
            "storage",
            "container",
            "create",
            "--name",
            container,
            "--account-name",
            storage_account,
            "--auth-mode",
            "login",
            "-o",
            "json",
        ]
    )


def _storage_env(
    storage_account: str,
    container: str,
    create_container: bool,
    include_storage_key: bool,
) -> dict[str, str]:
    storage_raw = _run_az_command(
        [
            "storage",
            "account",
            "show",
            "--name",
            storage_account,
            "-o",
            "json",
        ]
    )
    storage = json.loads(storage_raw)
    _ensure_container(storage_account, container, create_container)

    env = {
        "AZURE_STORAGE_ACCOUNT_URL": storage["primaryEndpoints"]["blob"].rstrip("/"),
        "AZURE_STORAGE_CONTAINER_NAME": container,
    }

    if include_storage_key:
        keys_raw = _run_az_command(
            [
                "storage",
                "account",
                "keys",
                "list",
                "--resource-group",
                storage["resourceGroup"],
                "--account-name",
                storage_account,
                "-o",
                "json",
            ]
        )
        keys = json.loads(keys_raw)
        env["AZURE_STORAGE_ACCOUNT_KEY"] = keys[0]["value"]

    return env


def _render_env(env_map: dict[str, str]) -> str:
    lines = [f"{key}={value}" for key, value in env_map.items()]
    return "\n".join(lines) + "\n"


def _write_env_file(output_path: str, env_text: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(env_text, encoding="utf-8")
    return path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        account = _require_az_login(args.subscription)
        env_map = {
            **_speech_env(args.resource_group, args.speech_account, args.include_secrets),
            **_storage_env(
                args.storage_account,
                args.container,
                args.create_container,
                args.include_storage_key,
            ),
        }
        env_text = _render_env(env_map)

        print(f"Azure subscription: {account['name']} ({account['id']})", file=sys.stderr)

        if args.check:
            sys.stdout.write(env_text)
            return 0

        output_path = _write_env_file(args.output, env_text)
        print(f"Wrote Azure environment to {output_path}", file=sys.stderr)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
