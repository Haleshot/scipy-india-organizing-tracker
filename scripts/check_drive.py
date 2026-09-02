#!/usr/bin/env python3
"""Check the Google Drive setup and say what is missing.

Connecting a Drive folder has four steps and three of them fail with errors that
do not obviously name the step you skipped. This runs them in order and stops at
the first one that is wrong, with the fix.

    python scripts/check_drive.py

Reads GOOGLE_SERVICE_ACCOUNT_CREDENTIAL and GOOGLE_DRIVE_ROOT_FOLDER_IDS from
.env or the environment. Read-only: it lists files and reads one, and never
writes to Drive.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def fail(step: str, problem: str, fix: str) -> int:
    print(f"\n  {step}: {problem}\n")
    print(f"  {fix}\n")
    return 1


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    # 1. The key file exists and looks like a service account.
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIAL", "").strip()
    if not raw:
        return fail(
            "credential",
            "GOOGLE_SERVICE_ACCOUNT_CREDENTIAL is not set.",
            "Put the JSON Google gave you in secrets/ and point the variable at it.",
        )
    path = Path(raw).expanduser()
    if not path.is_file():
        return fail("credential", f"{path} does not exist.", "Check the path in .env.")
    try:
        key = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return fail("credential", f"{path} is not valid JSON ({error}).", "Re-download it.")
    if key.get("type") != "service_account":
        return fail(
            "credential",
            f"{path} is a {key.get('type')!r} key, not a service account.",
            "Create a service account and download its JSON key.",
        )
    email = key.get("client_email", "")
    project = key.get("project_id", "")
    print(f"  credential  {path.name}")
    print(f"  project     {project}")
    print(f"  identity    {email}")

    folders = [
        f.strip()
        for f in os.environ.get("GOOGLE_DRIVE_ROOT_FOLDER_IDS", "").split(",")
        if f.strip()
    ]
    if not folders:
        return fail(
            "folders",
            "GOOGLE_DRIVE_ROOT_FOLDER_IDS is not set.",
            "Open the folder in Drive and copy the part of the URL after /folders/.",
        )
    print(f"  folders     {', '.join(folders)}")

    # 2. The Drive API is enabled and the credential is accepted.
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    credentials = service_account.Credentials.from_service_account_file(
        str(path), scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    total = 0
    for folder in folders:
        try:
            response = (
                service.files()
                .list(
                    q=f"'{folder}' in parents and trashed = false",
                    fields="files(id, name, mimeType, modifiedTime)",
                    pageSize=100,
                )
                .execute()
            )
        except HttpError as error:
            reason = str(error)
            if "accessNotConfigured" in reason or "has not been used in project" in reason:
                return fail(
                    "Drive API",
                    "the Drive API is not enabled on this Google Cloud project.",
                    "Enable it here, wait a minute, and re-run:\n"
                    f"    https://console.developers.google.com/apis/api/drive.googleapis.com/overview?project={project}",
                )
            if error.resp.status == 404:
                return fail(
                    "folder",
                    f"folder {folder} is not visible to the service account.",
                    f"Open it in Drive, press Share, and add {email} as a Viewer.\n"
                    "  An unshared folder looks like a missing folder from out here.",
                )
            return fail("Drive API", reason.splitlines()[0], "See the message above.")

        files = response.get("files", [])
        total += len(files)
        print(f"\n  folder {folder}: {len(files)} file(s)")
        for item in files:
            kind = "Google Doc" if item["mimeType"].endswith("apps.document") else item["mimeType"]
            print(f"    {item['name']}  ({kind}, modified {item['modifiedTime'][:10]})")

    # 3. Sharing. An empty folder and an unshared folder look identical.
    if total == 0:
        return fail(
            "sharing",
            "the API works, but no files are visible.",
            f"Either the folder is empty, or it is not shared with {email}.\n"
            "  Open the folder in Drive, press Share, and add that address as a Viewer.",
        )

    # 4. A Doc actually reads, and the export is plain text.
    print()
    import asyncio

    from cocoindex.connectors import google_drive

    async def read_one() -> None:
        source = google_drive.GoogleDriveSource(
            service_account_credential_path=str(path),
            root_folder_ids=folders,
            mime_types=(
                "application/vnd.google-apps.document",
                "text/markdown",
                "text/plain",
            ),
        )
        async for name, handle in source.items():
            text = await handle.read_text()
            lines = [line for line in text.splitlines() if line.strip()]
            meetings = sum(1 for line in lines if line.lower().startswith("meeting:"))
            print(f"  read {name}: {len(text)} characters, {meetings} Meeting: line(s)")
            if not meetings:
                print("       no Meeting: lines, so the pipeline will find no meetings in it.")
                print("       See docs/meeting-notes-template.md for the format.")
            break

    asyncio.run(read_one())
    print("\n  Drive is set up. Switch MEETING_NOTES_SOURCE to google_drive in .env.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
