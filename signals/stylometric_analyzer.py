import re
import statistics


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

    # ── Metric 1: sentence-length standard deviation ──────────────────────
    # AI writes uniformly-lengthed sentences; human writing varies more.
    lengths = [len(s.split()) for s in sents]
    sent_std = statistics.stdev(lengths) if len(lengths) >= 2 else 0.0
    # std=0 → 0.0 (AI-like),  std≥25 → 1.0 (human-like)
    variance_score = min(sent_std / 25.0, 1.0)

    # ── Metric 2: type-token ratio (vocabulary diversity) ────────────────
    # Higher diversity → more human-like.
    ttr = len(set(tokens)) / len(tokens) if tokens else 0.5
    # AI text typically clusters 0.45–0.60; human 0.60–0.80+
    # Map: ttr=0.40 → 0.0,  ttr=0.80 → 1.0
    ttr_score = max(0.0, min((ttr - 0.40) / 0.40, 1.0))

    # ── Metric 3: average sentence length ────────────────────────────────
    # AI gravitates toward 12–22-word sentences; deviating either direction
    # (very short or very long) is a mild human signal.
    avg_len = statistics.mean(lengths) if lengths else 15.0
    if avg_len < 12:
        length_score = (12 - avg_len) / 12.0             # short → human
    elif avg_len > 22:
        length_score = min((avg_len - 22) / 20.0, 1.0)   # long  → human
    else:
        length_score = 0.0                                # mid   → AI-like

    # ── Weighted human score ──────────────────────────────────────────────
    human_score = 0.45 * variance_score + 0.35 * ttr_score + 0.20 * length_score

    # ── Map to prediction + confidence ───────────────────────────────────
    # At human_score=0.5: confidence=0.5 (truly uncertain)
    # At human_score=0.0 or 1.0: confidence=0.90 (strong signal)
    prediction = "Human" if human_score >= 0.5 else "AI"
    confidence = round(0.5 + min(abs(human_score - 0.5), 0.5) * 0.8, 3)

    return {
        "prediction": prediction,
        "confidence": confidence,
        "metrics": {
            "sentence_length_std": round(sent_std, 2),
            "type_token_ratio": round(ttr, 3),
            "avg_sentence_length": round(avg_len, 1),
        },
    }
