import json
from typing import Iterable


def _coerce(value):
    if hasattr(value, "to_eng_string"):
        return float(value)
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce(v) for v in value]
    return value


def build_session_eval_prompt(persona: str, turns: Iterable[dict]) -> str:
    payload = {
        "persona": persona,
        "turns": [
            {
                "turn_index": _coerce(t.get("turn_index")),
                "agent_reply": t.get("agent_reply", ""),
                "user_transcript": t.get("user_transcript", ""),
                "fast_metrics": _coerce(t.get("fast_metrics_json", {})),
            }
            for t in turns
            if int(t.get("turn_index", 1)) > 0
        ],
    }

    schema = {
        "scores": {
            "overall": "0-100",
            "fluency": "0-100",
            "grammar": "0-100",
            "vocabulary": "0-100",
            "clarity": "0-100",
        },
        "strengths": ["..."],
        "improvements": ["..."],
        "practice_tasks": ["..."],
        "corrections": [
            {"original": "...", "suggested": "..."}
        ],
        "notes": "short summary"
    }

    return (
        "You are an English communication evaluator. "
        "Score the learner based on the conversation turns. "
        "Use transcript-only signals. "
        "Return ONLY valid JSON that matches this schema exactly.\n\n"
        f"Schema: {json.dumps(schema)}\n\n"
        f"Input: {json.dumps(_coerce(payload))}"
    )
