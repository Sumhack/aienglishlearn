import re
from dataclasses import dataclass


DEFAULT_FILLERS = (
    "um",
    "uh",
    "like",
    "actually",
    "basically",
    "you know",
    "sort of",
    "kind of",
)


@dataclass(frozen=True)
class FastMetrics:
    word_count: int
    filler_count: int
    filler_ratio: float
    sentence_count: int
    avg_words_per_sentence: float


_word_re = re.compile(r"[A-Za-z']+")


def compute_fast_metrics(text: str, fillers: tuple[str, ...] = DEFAULT_FILLERS) -> FastMetrics:
    words = _word_re.findall(text.lower())
    word_count = len(words)
    filler_count = 0
    for filler in fillers:
        filler_count += text.lower().count(filler)
    filler_ratio = (filler_count / word_count) if word_count else 0.0
    sentence_count = max(1, len(re.findall(r"[.!?]+", text)))
    avg_words_per_sentence = word_count / sentence_count if sentence_count else word_count
    return FastMetrics(
        word_count=word_count,
        filler_count=filler_count,
        filler_ratio=round(filler_ratio, 4),
        sentence_count=sentence_count,
        avg_words_per_sentence=round(avg_words_per_sentence, 2),
    )
