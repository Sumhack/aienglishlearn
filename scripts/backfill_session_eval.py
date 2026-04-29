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
from app.eval.deep_eval_worker import run_deep_eval  # noqa: E402
from app.eval.prompts import build_session_eval_prompt  # noqa: E402
from app.services.session_service import (  # noqa: E402
    get_session_by_id,
    list_turn_items,
    update_session_summary,
)


def _has_fast_metrics(turns: list[dict]) -> bool:
    if not turns:
        return False
    for turn in turns:
        metrics = turn.get("fast_metrics_json")
        if not metrics:
            return False
    return True


def _update_eval_version(*, session_id: str, eval_version: int) -> None:
    settings = get_settings()
    resource = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region or "ap-south-1",
    )
    table = resource.Table(settings.aws_sessions_table)
    table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET eval_version = :v",
        ExpressionAttributeValues={":v": eval_version},
    )


def _list_all_candidate_session_ids(*, eval_version: int) -> list[str]:
    settings = get_settings()
    resource = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region or "ap-south-1",
    )
    table = resource.Table(settings.aws_sessions_table)
    candidate_ids: list[str] = []
    scan_kwargs: dict = {
        "FilterExpression": Attr("report_status").eq("ready")
        & (Attr("eval_version").not_exists() | Attr("eval_version").lt(eval_version)),
        "ProjectionExpression": "session_id",
    }

    while True:
        response = table.scan(**scan_kwargs)
        candidate_ids.extend(
            item["session_id"]
            for item in response.get("Items", [])
            if item.get("session_id")
        )
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    return candidate_ids


def _backfill_session(*, session_id: str, dry_run: bool, eval_version: int, allow_partial: bool) -> None:
    session = get_session_by_id(session_id)
    if not session:
        print(f"[skip] session not found: {session_id}")
        return

    turns = list_turn_items(session_id)
    if not turns:
        print(f"[skip] no turns found: {session_id}")
        return

    # if not allow_partial and not _has_fast_metrics(turns):
    #     print(f"[skip] missing fast_metrics_json on one or more turns: {session_id}")
    #     return

    prompt = build_session_eval_prompt(session.persona, turns)
    print(f"[candidate] {session_id} persona={session.persona} turns={len(turns)}")

    if dry_run:
        return

    result = run_deep_eval(prompt)
    summary = {
        "strengths": result.strengths,
        "improvements": result.improvements,
        "content_improvements": result.content_improvements,
        "practice_tasks": result.practice_tasks,
        "corrections": result.corrections,
        "notes": result.notes,
    }

    update_session_summary(
        session_id=session_id,
        scores=result.scores,
        summary=summary,
        report_status="ready",
    )
    _update_eval_version(session_id=session_id, eval_version=eval_version)
    print(
        json.dumps(
            {
                "session_id": session_id,
                "status": "updated",
                "eval_version": eval_version,
                "scores": result.scores
                # "relevance": result.scores.get("relevance"),
            },
            ensure_ascii=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill session evals using the current deep-eval schema."
    )
    parser.add_argument(
        "session_ids",
        nargs="*",
        help="One or more session IDs to backfill (omit when using --all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate candidates without writing")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Backfill all eligible sessions with report_status=ready and eval_version < target",
    )
    parser.add_argument(
        "--eval-version",
        type=int,
        default=2,
        help="Eval version to store on each updated session",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow sessions even if some turns are missing fast_metrics_json",
    )
    args = parser.parse_args()

    if args.all and args.session_ids:
        raise SystemExit("Use either --all or explicit session_ids, not both")

    if not args.all and not args.session_ids:
        raise SystemExit("Provide one or more session_ids, or use --all")

    session_ids = (
        _list_all_candidate_session_ids(eval_version=args.eval_version) if args.all else args.session_ids
    )

    if args.all:
        print(f"[info] found {len(session_ids)} candidate sessions")

    for session_id in session_ids:
        try:
            _backfill_session(
                session_id=session_id,
                dry_run=args.dry_run,
                eval_version=args.eval_version,
                allow_partial=args.allow_partial,
            )
        except Exception as exc:
            print(f"[error] {session_id}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
