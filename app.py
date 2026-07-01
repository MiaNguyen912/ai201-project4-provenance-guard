import json
import os
import uuid

import config
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import audit_logger
import confidence_evaluator
from signals.llm_classifier import classify as llm_classify
from signals.stylometric_analyzer import analyze as stylo_analyze

app = Flask(__name__)


def _client_key():
    """Rate-limit key: creator_id from body, fallback to IP."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        return data.get("creator_id") or get_remote_address()
    except Exception:
        return get_remote_address()


limiter = Limiter(
    key_func=_client_key,
    app=app,
    default_limits=config.RATE_LIMIT_GLOBAL,
    storage_uri="memory://", # "memory://"" resets every time the server restarts, that's fine for this project
)


@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({"error": "Rate limit exceeded"}), 429


# ---------------------------------------------------------------------------
# POST /submit
# ---------------------------------------------------------------------------

@app.route("/submit", methods=["POST"])
@limiter.limit(config.RATE_LIMIT_SUBMIT)
def submit():
    data = request.get_json(force=True, silent=True) or {}

    creator_id = data.get("creator_id") or get_remote_address()
    text = data.get("text")
    if not text:
        return jsonify({"error": "Missing required fields: text"}), 400

    content_id = "cnt_" + uuid.uuid4().hex[:8]
    request_id = "req_" + uuid.uuid4().hex[:8]

    # Signal A — LLM Classification
    llm_result = llm_classify(text)

    # Signal B — Stylometric Analysis
    stylo_result = stylo_analyze(text)

    # Combine signals → final classification + label
    evaluation = confidence_evaluator.evaluate(llm_result, stylo_result)
    attribution = evaluation["attribution"]
    confidence     = evaluation["confidence"]
    label          = evaluation["label"]

    audit_logger.add_log(
        event_type="classification",
        creator_id=creator_id,
        content_id=content_id,
        request_id=request_id,
        original_request_id=request_id,
        text=text,
        llm_result=llm_result,
        stylometric_result=stylo_result,
        final_classification=attribution,
        confidence=confidence,
        status="classified",
    )

    return jsonify({
        "content_id": content_id,
        "request_id": request_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
    })
        


# ---------------------------------------------------------------------------
# GET /audit/<content_id>
# ---------------------------------------------------------------------------

@app.route("/audit/<content_id>", methods=["GET"])
@limiter.limit(config.RATE_LIMIT_SUBMIT)
def get_audit(content_id):
    events = audit_logger.get_entries_by_content_id(content_id)
    if not events:
        return jsonify({"error": f"No audit records found for content_id: {content_id}"}), 404
    return jsonify({"content_id": content_id, "events": events})


# ---------------------------------------------------------------------------
# GET /log?num_latest_logs=<n>
# ---------------------------------------------------------------------------

@app.route("/log", methods=["GET"])
@limiter.limit(config.RATE_LIMIT_SUBMIT)
def get_log():
    raw = request.args.get("num_latest_logs", "50")
    try:
        limit = int(raw)
    except ValueError:
        return jsonify({"error": "num_latest_logs must be an integer"}), 400
    entries = audit_logger.get_logs(limit=limit)
    return jsonify({"entries": entries})


# ---------------------------------------------------------------------------
# POST /appeals
# ---------------------------------------------------------------------------

@app.route("/appeal", methods=["POST"])    
@limiter.limit(config.RATE_LIMIT_SUBMIT)
def submit_appeal():
    data = request.get_json(force=True, silent=True) or {}

    content_id = data.get("content_id")
    creator_id = data.get("creator_id") or get_remote_address()
    appeal_reason = data.get("creator_reasoning")

    if not content_id or not appeal_reason:
        return jsonify({"error": "Missing required fields: content_id, creator_reasoning"}), 400

    # Retrieve original classification event
    original_events = audit_logger.get_entries_by_content_id(content_id)
    if not original_events:
        return jsonify({"error": f"No classification found for content_id: {content_id}"}), 404

    # Find the original classification event (most recent one with event_type='classification')
    original_event = None
    for event in reversed(original_events):
        if event.get("event_type") == "classification":
            original_event = event
            break

    if not original_event:
        return jsonify({"error": f"No classification found for content_id: {content_id}"}), 404

    # Generate appeal request ID
    appeal_request_id = "req_" + uuid.uuid4().hex[:8]

    # Update original classification status to "under_review"
    audit_logger.update_status(content_id, "under_review")

    # Log appeal_submitted audit event
    audit_logger.add_log(
        event_type="appeal_submitted",
        creator_id=creator_id,
        content_id=content_id,
        request_id=appeal_request_id,
        original_request_id=original_event.get("request_id"),
        text=appeal_reason,
        status="under_review",
    )                

    # Append to appeal_queue.jsonl
    appeal_entry = {
        "appeal_request_id": appeal_request_id,
        "content_id": content_id,
        "creator_id": creator_id,
        "original_request_id": original_event.get("request_id"),
        "original_classification": original_event.get("final_classification"),
        "original_confidence": original_event.get("confidence"),
        "appeal_reason": appeal_reason,
        "text": original_event.get("text"),
        "submitted_at": audit_logger.datetime.now(audit_logger.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "pending_review",
    }

    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    appeal_queue_path = os.path.join(logs_dir, "appeal_queue.jsonl")
    with open(appeal_queue_path, "a") as f:
        f.write(json.dumps(appeal_entry) + "\n")

    return jsonify({
        "appeal_request_id": appeal_request_id,
        "content_id": content_id,
        "status": "under_review",
        "message": "Appeal submitted successfully",
    }), 201


if __name__ == "__main__":
    app.run(debug=True, port=8000)
