import re
import statistics

_FILLER_WORDS = {
    "ok", "okay", "honestly", "anyway", "actually", "literally",
    "basically", "tbh", "btw", "lol", "idk", "omg", "imo", "fyi",
    "kinda", "sorta", "gonna", "wanna", "gotta", "yep", "nope",
}


def _sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in parts if s.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r'\b[a-zA-Z]+\b', text.lower())


def analyze(text: str) -> dict:
    """
    Runs stylometric analysis on text.

    Returns:
        {
            "prediction": "AI" | "Human",
            "confidence": float,   # 0.0 – 1.0
            "metrics": {
                "sentence_length_std": float,
                "type_token_ratio":    float,
                "avg_sentence_length": float,
            }
        }
    """
    sents = _sentences(text)
    tokens = _words(text)
    lengths = [len(s.split()) for s in sents]

    # ── Metric 1: sentence-length standard deviation (weight 0.30) ───────
    # AI writes uniformly-lengthed sentences; human writing varies more.
    # Threshold lowered from 25→12 to be sensitive at short-text scales.
    sent_std = statistics.stdev(lengths) if len(lengths) >= 2 else 0.0
    variance_score = min(sent_std / 12.0, 1.0)

    # ── Metric 2: informal register (weight 0.50) ─────────────────────────
    # TTR is uniformly high (0.85+) for both AI and human in short texts and
    # provides no separation. Replaced with signals that actually differ:
    #   - contractions (won't, I've) — absent in formal/AI text
    #   - sentences starting with lowercase — casual register
    #   - filler / slang words (ok, honestly, gonna…)
    contractions = len(re.findall(r"\b\w+'\w+\b", text))
    lowercase_starts = sum(1 for s in sents if s and s[0].islower())
    filler_count = sum(1 for w in tokens if w in _FILLER_WORDS)
    informal_count = contractions + lowercase_starts + filler_count
    informal_score = min(informal_count / max(len(sents), 1), 1.0)

    # ── Metric 3: average sentence length (weight 0.20) ──────────────────
    # AI gravitates toward 12–20-word sentences; deviating either direction
    # (very short or very long) is a mild human signal.
    avg_len = statistics.mean(lengths) if lengths else 15.0
    if avg_len < 12:
        length_score = (12 - avg_len) / 12.0
    elif avg_len > 20:
        length_score = min((avg_len - 20) / 20.0, 1.0)
    else:
        length_score = 0.0

    # ── Weighted human score ──────────────────────────────────────────────
    human_score = 0.30 * variance_score + 0.50 * informal_score + 0.20 * length_score

    # ── Map to prediction + confidence ───────────────────────────────────
    # Steeper multiplier (×1.5) so a clear signal produces a
    # clearly high confidence instead of clustering near 0.5.
    prediction = "Human" if human_score >= 0.5 else "AI"
    confidence = round(min(0.5 + abs(human_score - 0.5) * 1.5, 1.0), 3)

    ttr = len(set(tokens)) / len(tokens) if tokens else 0.5
    return {
        "prediction": prediction,
        "confidence": confidence,
        "metrics": {
            "sentence_length_std": round(sent_std, 2),
            "type_token_ratio": round(ttr, 3),
            "avg_sentence_length": round(avg_len, 1),
        },
    }
