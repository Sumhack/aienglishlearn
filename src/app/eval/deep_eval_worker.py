import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
import boto3

from app.config import get_settings


@dataclass(frozen=True)
class DeepEvalResult:
    scores: dict[str, float]
    strengths: list[str]
    improvements: list[str]
    practice_tasks: list[str]
    corrections: list[dict[str, str]]
    notes: str


import json
from dataclasses import dataclass

import boto3

from app.config import get_settings


#     if model.startswith("google/"):
#         return model.removeprefix("google/")
#     return "gemini-1.5-flash"


def _parse_json_from_text(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError(f"Model returned non-JSON output: {text[:500]}")
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Model returned invalid JSON. Snippet: {snippet[:500]}"
            ) from exc
# def _model_name() -> str:
#     settings = get_settings()
#     model = settings.agent_llm
#     if model.startswith("google/"):
#         return model.removeprefix("google/")
#     return "gemini-1.5-flash"


# def run_deep_eval_gemini(prompt: str) -> DeepEvalResult:
#     settings = get_settings()
#     model = _model_name()
#     url = (
#         f"https://generativelanguage.googleapis.com/v1beta/models/"
#         f"{model}:generateContent?key={settings.google_api_key}"
#     )
#     body = {
#         "contents": [{"parts": [{"text": prompt}]}],
#         "generationConfig": {
#             "temperature": 0.2,
#             "maxOutputTokens": 1200,
#             "responseMimeType": "application/json",
#         },
#     }
#     req = urllib.request.Request(
#         url,
#         data=json.dumps(body).encode("utf-8"),
#         headers={"Content-Type": "application/json"},
#         method="POST",
#     )
#     try:
#         with urllib.request.urlopen(req, timeout=60) as resp:
#             payload = json.loads(resp.read().decode("utf-8"))
#     except urllib.error.HTTPError as exc:
#         detail = exc.read().decode("utf-8") if exc.fp else str(exc)
#         raise RuntimeError(f"Deep eval request failed: {detail}") from exc

#     candidates = payload.get("candidates", [])
#     if not candidates:
#         raise RuntimeError("Deep eval returned no candidates")

#     content = candidates[0].get("content", {})
#     parts = content.get("parts", [])
#     if not parts:
#         raise RuntimeError("Deep eval returned empty content")

#     raw_text = parts[0].get("text", "{}")
#     data = json.loads(raw_text)

#     scores = data.get("scores", {})
#     return DeepEvalResult(
#         scores={
#             "overall": float(scores.get("overall", 0)),
#             "fluency": float(scores.get("fluency", 0)),
#             "grammar": float(scores.get("grammar", 0)),
#             "vocabulary": float(scores.get("vocabulary", 0)),
#             "clarity": float(scores.get("clarity", 0)),
#         },
#         strengths=list(data.get("strengths", [])),
#         improvements=list(data.get("improvements", [])),
#         practice_tasks=list(data.get("practice_tasks", [])),
#         corrections=list(data.get("corrections", [])),
#         notes=str(data.get("notes", "")),
#     )



import boto3

from app.config import get_settings









def run_deep_eval_bedrock(prompt: str) -> DeepEvalResult:
    settings = get_settings()
    if not settings.bedrock_model_id:
        raise RuntimeError("BEDROCK_MODEL_ID is required when EVAL_PROVIDER=bedrock")

    client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    response = client.converse(
        modelId=settings.bedrock_model_id,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        inferenceConfig={
            "temperature": 0.2,
            "maxTokens": 1200,
        },
    )

    output = response.get("output", {})
    message = output.get("message", {})
    content = message.get("content", [])
    if not content:
        raise RuntimeError(f"Bedrock response missing content: {response}")

    output_text = content[0].get("text", "")
    if not output_text:
        raise RuntimeError(f"Bedrock response missing output text: {response}")

    data = _parse_json_from_text(output_text)
    scores = data.get("scores", {})
    return DeepEvalResult(
        scores={
            "overall": float(scores.get("overall", 0)),
            "fluency": float(scores.get("fluency", 0)),
            "grammar": float(scores.get("grammar", 0)),
            "vocabulary": float(scores.get("vocabulary", 0)),
            "clarity": float(scores.get("clarity", 0)),
        },
        strengths=list(data.get("strengths", [])),
        improvements=list(data.get("improvements", [])),
        practice_tasks=list(data.get("practice_tasks", [])),
        corrections=list(data.get("corrections", [])),
        notes=str(data.get("notes", "")),
    )

def run_deep_eval(prompt: str) -> DeepEvalResult:
    # settings = get_settings()
    return run_deep_eval_bedrock(prompt)
    # if settings.eval_provider.lower() == "bedrock":
    #     return run_deep_eval_bedrock(prompt)
    # return run_deep_eval_gemini(prompt)
