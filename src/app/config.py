import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from dotenv import load_dotenv

load_dotenv()


REQUIRED_ENV_BY_SCOPE = {
    "livekit": (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
    ),
    "models": (
        "GOOGLE_API_KEY",
        "DEEPGRAM_API_KEY",
        "CARTESIA_API_KEY",
    ),
    "auth": (
        "AWS_REGION",
        "AWS_USERS_TABLE",
        "AWS_SESSIONS_TABLE",
        "AWS_TURNS_TABLE",
        "AWS_MODULES_TABLE",
        "AWS_FEEDBACK_TABLE",
        "JWT_SECRET",
    ),
    "eval": (
        "EVAL_PROVIDER",
        "BEDROCK_MODEL_ID",
    ),
}


@dataclass(frozen=True)
class Settings:
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    google_api_key: str
    deepgram_api_key: str
    cartesia_api_key: str
    agent_stt: str = "deepgram/flux-general:en"
    agent_llm: str = "google/gemini-2.0-flash"
    agent_tts: str = "cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
    llm_input_cost_per_1k_tokens: float = 0.0
    llm_output_cost_per_1k_tokens: float = 0.0
    eval_provider: str = "bedrock"
    bedrock_model_id: str = ""
    backend_base_url: str = ""
    internal_api_key: str = ""
    egress_s3_access_key: str = ""
    egress_s3_secret_key: str = ""
    egress_s3_bucket: str = ""
    egress_s3_region: str = ""
    aws_region: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_users_table: str = "users"
    aws_sessions_table: str = "sessions"
    aws_turns_table: str = "turns"
    aws_modules_table: str = "learning_modules"
    aws_personas_table: str = "personas"
    aws_feedback_table: str = "user_feedback"
    jwt_secret: str = ""
    jwt_exp_minutes: int = 60
    log_level: str = "INFO"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def missing_env_vars(scopes: Iterable[str]) -> list[str]:
    missing: list[str] = []
    for scope in scopes:
        for var_name in REQUIRED_ENV_BY_SCOPE.get(scope, ()):
            if not _env(var_name):
                missing.append(var_name)
    return missing


def validate_required_env(scopes: Iterable[str]) -> None:
    missing = missing_env_vars(scopes)
    if missing:
        missing_sorted = ", ".join(sorted(set(missing)))
        raise RuntimeError(f"Missing required environment variables: {missing_sorted}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        livekit_url=_env("LIVEKIT_URL"),
        livekit_api_key=_env("LIVEKIT_API_KEY"),
        livekit_api_secret=_env("LIVEKIT_API_SECRET"),
        google_api_key=_env("GOOGLE_API_KEY"),
        deepgram_api_key=_env("DEEPGRAM_API_KEY"),
        cartesia_api_key=_env("CARTESIA_API_KEY"),
        agent_stt=_env("AGENT_STT", "deepgram/flux-general:en"),
        agent_llm=_env("AGENT_LLM", "google/gemini-2.5-flash"),
        agent_tts=_env(
            "AGENT_TTS", "cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
        ),
        llm_input_cost_per_1k_tokens=float(_env("LLM_INPUT_COST_PER_1K_TOKENS", "0")),
        llm_output_cost_per_1k_tokens=float(
            _env("LLM_OUTPUT_COST_PER_1K_TOKENS", "0")
        ),
        eval_provider=_env("EVAL_PROVIDER", "gemini"),
        bedrock_model_id=_env("BEDROCK_MODEL_ID", ""),
        backend_base_url=_env("BACKEND_BASE_URL"),
        internal_api_key=_env("INTERNAL_API_KEY"),
        egress_s3_access_key=_env("EGRESS_S3_ACCESS_KEY"),
        egress_s3_secret_key=_env("EGRESS_S3_SECRET_KEY"),
        egress_s3_bucket=_env("EGRESS_S3_BUCKET"),
        egress_s3_region=_env("EGRESS_S3_REGION"),
        aws_region=_env("AWS_REGION"),
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY"),
        aws_users_table=_env("AWS_USERS_TABLE", "users"),
        aws_sessions_table=_env("AWS_SESSIONS_TABLE", "sessions"),
        aws_turns_table=_env("AWS_TURNS_TABLE", "turns"),
        aws_modules_table=_env("AWS_MODULES_TABLE", "learning_modules"),
        aws_personas_table=_env("AWS_PERSONAS_TABLE", "personas"),
        aws_feedback_table=_env("AWS_FEEDBACK_TABLE", "user_feedback"),
        jwt_secret=_env("JWT_SECRET"),
        jwt_exp_minutes=int(_env("JWT_EXP_MINUTES", "60")),
        log_level=_env("LOG_LEVEL", "INFO"),
    )
