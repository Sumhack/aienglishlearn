from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Attr


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app.config import get_settings  # noqa: E402


def _tables():
    settings = get_settings()
    resource = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region or "ap-south-1",
    )
    sessions = resource.Table(settings.aws_sessions_table)
    modules = resource.Table(settings.aws_modules_table)
    return sessions, modules


def _resolve_module_meta(modules_table, persona: str) -> tuple[str, str] | None:
    item = modules_table.get_item(Key={"module_key": persona}).get("Item")
    if not item:
        return None
    display_name = item.get("display_name") or item.get("module_name") or persona
    coach_type = item.get("coach_type") or ""
    return display_name, coach_type


def _candidate_session_ids(sessions_table, all_rows: bool) -> list[str]:
    ids: list[str] = []
    scan_kwargs: dict = {"ProjectionExpression": "session_id"}
    if not all_rows:
        scan_kwargs["FilterExpression"] = Attr("display_name").not_exists() | Attr("coach_type").not_exists()

    while True:
        response = sessions_table.scan(**scan_kwargs)
        ids.extend(item["session_id"] for item in response.get("Items", []) if item.get("session_id"))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    return ids


def _update_session_meta(
    sessions_table,
    modules_table,
    session_id: str,
    dry_run: bool,
) -> None:
    item = sessions_table.get_item(Key={"session_id": session_id}).get("Item")
    if not item:
        print(f"[skip] session not found: {session_id}")
        return

    persona = item.get("persona")
    if not persona:
        print(f"[skip] session missing persona: {session_id}")
        return

    module_meta = _resolve_module_meta(modules_table, persona)
    if not module_meta:
        print(f"[skip] persona not found in learning_modules: session={session_id} persona={persona}")
        return

    display_name, coach_type = module_meta
    print(
        f"[candidate] session={session_id} persona={persona} "
        f"display_name={display_name!r} coach_type={coach_type!r}"
    )

    if dry_run:
        return

    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET display_name = :d, coach_type = :c",
        ExpressionAttributeValues={
            ":d": display_name,
            ":c": coach_type,
        },
    )
    print(
        json.dumps(
            {
                "session_id": session_id,
                "status": "updated",
                "display_name": display_name,
                "coach_type": coach_type,
            },
            ensure_ascii=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill display_name and coach_type in sessions from learning_modules."
    )
    parser.add_argument(
        "session_ids",
        nargs="*",
        help="One or more session IDs to update (omit when using --all).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all sessions (or only missing fields unless --include-populated is passed).",
    )
    parser.add_argument(
        "--include-populated",
        action="store_true",
        help="With --all, include rows that already have display_name and coach_type.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview updates without writing.")
    args = parser.parse_args()

    if args.all and args.session_ids:
        raise SystemExit("Use either --all or explicit session_ids, not both.")
    if not args.all and not args.session_ids:
        raise SystemExit("Provide session_ids, or use --all.")

    sessions_table, modules_table = _tables()

    if args.all:
        session_ids = _candidate_session_ids(sessions_table, all_rows=args.include_populated)
        print(f"[info] found {len(session_ids)} candidate sessions")
    else:
        session_ids = args.session_ids

    for session_id in session_ids:
        try:
            _update_session_meta(
                sessions_table=sessions_table,
                modules_table=modules_table,
                session_id=session_id,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            print(f"[error] {session_id}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
