import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PERSONA = "professional"
DEFAULT_MODE = "behavioral_interview"


@dataclass(frozen=True)
class CurriculumPack:
    persona: str
    mode: str
    prompts: dict[str, Any]
    questions: dict[str, Any]
    scoring: dict[str, Any]
    source_path: Path


def _curriculum_dir(persona: str, mode: str) -> Path:
    return Path(__file__).resolve().parent / persona / mode


def _load_json(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        raise FileNotFoundError(f"Missing curriculum file: {file_path}")
    with file_path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def load_curriculum(persona: str, mode: str) -> CurriculumPack:
    requested_dir = _curriculum_dir(persona, mode)
    if requested_dir.exists():
        selected_persona = persona
        selected_mode = mode
        selected_dir = requested_dir
    else:
        selected_persona = DEFAULT_PERSONA
        selected_mode = DEFAULT_MODE
        selected_dir = _curriculum_dir(DEFAULT_PERSONA, DEFAULT_MODE)

    prompts = _load_json(selected_dir / "prompts.json")
    questions = _load_json(selected_dir / "questions.json")
    scoring = _load_json(selected_dir / "scoring.json")

    return CurriculumPack(
        persona=selected_persona,
        mode=selected_mode,
        prompts=prompts,
        questions=questions,
        scoring=scoring,
        source_path=selected_dir,
    )
