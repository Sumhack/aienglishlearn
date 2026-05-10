import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PERSONA = "school_mentor"


@dataclass(frozen=True)
class CurriculumPack:
    persona: str
    prompts: dict[str, Any]
    questions: dict[str, Any]
    scoring: dict[str, Any]
    source_path: Path


def _curriculum_dir() -> Path:
    return Path(__file__).resolve().parent / "personas"


def _load_json(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        raise FileNotFoundError(f"Missing curriculum file: {file_path}")
    with file_path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def _select_persona(data: dict[str, Any], persona: str) -> tuple[str, dict[str, Any]]:
    personas = data.get("personas", {})
    if persona in personas:
        return persona, personas[persona]
    default_persona = data.get("default_persona", DEFAULT_PERSONA)
    return default_persona, personas.get(default_persona, {})


def load_curriculum(persona: str) -> CurriculumPack:
    selected_dir = _curriculum_dir()
    if not selected_dir.exists():
        raise FileNotFoundError(f"Missing curriculum folder: {selected_dir}")

    prompts_data = _load_json(selected_dir / "prompts_v2.json")
    questions_data = _load_json(selected_dir / "questions.json")
    scoring_data = _load_json(selected_dir / "scoring.json")

    selected_persona, prompts = _select_persona(prompts_data, persona)
    _, questions = _select_persona(questions_data, selected_persona)
    _, scoring = _select_persona(scoring_data, selected_persona)

    return CurriculumPack(
        persona=selected_persona,
        prompts=prompts,
        questions=questions,
        scoring=scoring,
        source_path=selected_dir,
    )
