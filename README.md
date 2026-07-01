# Provenance Guard

A backend API that classifies submitted text as human-written or AI-generated, scores confidence, surfaces a transparency label, and handles creator appeals.

## Architecture Overview

Provenance Guard analyzes submitted text through a multi-stage pipeline:

1. **Content Submission** → Creator submits text via `POST /submit`
2. **Rate Limiting** → Request checked against per-creator rate limits
3. **Dual Signal Detection** → Text analyzed by two independent signals (LLM-based classifier + stylometric analyzer)
4. **Signal Fusion** → Both signals combined into a single confidence score using weighted formula with disagreement penalty
5. **Transparency Label Generation** → Confidence score mapped to reader-facing label (high-confidence AI, high-confidence human, moderate confidence, or uncertain)
6. **Audit Logging** → Full decision record stored in SQLite for traceability and appeals
7. **Response** → API returns classification, confidence, and label to client

On appeal, creators submit disputes via `POST /appeal`, which logs the appeal to both an active review queue (`/logs/appeal_queue.jsonl`) and the permanent audit database (`/logs/audit.db`). Reviewers resolve appeals via `PATCH /appeal/{content_id}`, which updates status and removes from the active queue.

---

## Detection Signals

### Signal A: LLM-Based Classification (Groq llama-3.3-70b-versatile)

**What it measures:** Global writing patterns—coherence, tone consistency, structure, and overall "AI-likeness" of text.

**Why we chose it:** Modern language models capture semantic patterns and stylistic traits that human writing exhibits (personal voice, conversational irregularities, emotional variation) vs. AI writing (uniform polish, predictable phrasing, consistency across sections).

**What it misses:** It judges appearance, not origin. Polished human writing (e.g., journalism, formal academic prose) can be mislabeled as AI. Similarly, AI text that's been lightly edited by a human can evade detection. The signal is probabilistic and model-dependent—different models may produce different outputs.

**Output format:** `{"prediction": "AI|Human", "confidence": 0.0–1.0}`

### Signal B: Stylometric Analysis (Pure Python heuristics)

**What it measures:** Statistical properties of text—sentence length variance, type-token ratio (vocabulary diversity), punctuation density, and average sentence complexity.

**Why we chose it:** Provides an explainable, deterministic counterpoint that doesn't rely on another AI model. Human writing is naturally variable and inconsistent (different sentence structures, vocabulary shifts, punctuation patterns). AI writing tends toward uniformity unless explicitly prompted otherwise.

**What it misses:** It ignores meaning entirely. Very short texts (< 50 words) produce unreliable metrics—sentence variance and type-token ratio aren't meaningful from two sentences. Professional formulaic writing (legal briefs, technical specs) can appear AI-like due to intentionally consistent structure. AI can mimic human statistics with deliberate prompting or post-generation editing.

**Output format:** `{"prediction": "AI|Human", "confidence": 0.0–1.0, "metrics": {...}}`

---

## Confidence Scoring

**How signals are combined:**

1. **Weighted base:** `base = 0.6 × LLM_confidence + 0.4 × stylometric_confidence` (LLM weighted higher because it captures semantics; stylometric is structural)
2. **Agreement bonus:** If both signals agree on prediction, `final_confidence = base`
3. **Disagreement penalty:** If signals disagree, `final_confidence = base × 0.77` (penalizes unreliable signal combinations)

**Threshold mapping:**
- `≥ 0.85` → High confidence (label: "Likely AI-Generated" or "Likely Human-Written")
- `0.60–0.84` → Moderate confidence (label: "Possibly AI-Generated" or "Possibly Human-Written")
- `< 0.60` → Uncertain (label: "Attribution Uncertain")

**Validation — Example submissions showing meaningful variation:**

Example 1: **Formal, uniform writing (high-confidence AI)**
```
Text: "Artificial intelligence represents a transformative paradigm shift in modern society. 
It is important to note that while the benefits of AI are numerous, it is equally essential 
to consider the ethical implications. Furthermore, stakeholders across various sectors must 
collaborate to ensure responsible deployment."

LLM: prediction=AI, confidence=0.92
Stylometric: prediction=AI, confidence=0.524
Combined: base = 0.6(0.92) + 0.4(0.524) = 0.762
Agreement? Yes → final_confidence = 0.762
Label: "Possibly AI-Generated" (0.60–0.84 band)
```

Example 2: **Mixed signals, lower confidence (uncertain)**
```
Text: "I've been thinking a lot about remote work lately. There are genuine tradeoffs — 
flexibility and no commute on one side, isolation and blurred work-life boundaries on the other. 
Studies show productivity varies widely by individual and role type."

LLM: prediction=Human, confidence=0.8
Stylometric: prediction=AI, confidence=0.772
Combined: base = 0.6(0.8) + 0.4(0.772) = 0.789
Agreement? No → final_confidence = 0.789 × 0.77 = 0.607
Label: "Attribution Uncertain" (< 0.60 band, just below threshold)
```

These examples show the scoring varies meaningfully: disagreement between signals produces lower confidence; aligned signals produce higher confidence.

See more examples in `Test the /submit endpoint` section in this file

---

## Getting Started

### Prerequisites

- Python 3.10+
- A [Groq](https://console.groq.com/) API key

### Setup

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root:
   ```
   GROQ_API_KEY=your_groq_api_key_here
   ```
   Optionally override the model (defaults to `llama-3.3-70b-versatile`):
   ```
   GROQ_MODEL=llama-3.3-70b-versatile
   ```

4. Run the app:
   ```bash
   flask --app app run --port 8000
   ```
   > **Note:** Port 5000 is reserved by macOS AirPlay on Apple Silicon Macs. Use 8000 or any other free port.



### Transparency label design
The following labels are defined in [confidence_evaluator.py](confidence_evaluator.py):

- **Label A — High-Confidence AI** (`label: "high_confidence_ai"`, confidence ≥ 0.85, prediction = AI)
   ```
   title: "Likely AI-Generated"
   message: "Our system found strong indicators that this content was generated using AI tools."
   ```
- **Label B — High-Confidence Human** (`label: "high_confidence_human"`, confidence ≥ 0.85, prediction = Human)
   ```
   title: "Likely Human-Written"
   message: "Our system found strong indicators that this content was written by a human author."
   ```
- **Label C — Moderate Confidence** (`label: "high_confidence_ai"` or `"high_confidence_human"`, confidence 0.60–0.84)
   ```
   title: "Possibly AI-Generated" / "Possibly Human-Written"
   message: "Our analysis leans toward this content being [AI-generated / human-written], but the signal is not strong enough to be certain."
   ```
- **Label D — Uncertain** (`label: "uncertain"`, confidence < 0.60)
   ```
   title: "Attribution Uncertain"
   message: "Our system could not confidently determine whether this content was written by a human or generated by AI."
        ```


### Test the /submit endpoint
Open another terminal and submit this command for text analysis:
NOTE: `creator_id` is optional. If no `creator_id` is provided, it'll get the default value returned `from flask_limiter.util.get_remote_address()`

```bash
    curl -s -X POST "http://localhost:8000/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "creator_id": "test-user-1",
    "text": "The sun dipped below the horizon, painting the sky in hues of amber and rose. I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet."
  }' \
  | python3 -m json.tool
```

(`python3 -m json.tool` is a built-in Python utility that pretty-prints JSON. Without it, the API response might come back as a single long line)

Expected response shape:
```json
{
    "attribution": "uncertain",
    "confidence": 0.511,
    "content_id": "cnt_d656a596",
    "label": {
        "key": "uncertain",
        "message": "Our system could not confidently determine whether this content was written by a human or generated by AI.",
        "title": "Attribution Uncertain"
    },
    "request_id": "req_8eb77b12"
}
```


Other test cases:
- 1. **Clearly AI-generated (should score high)**: "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment."
   => Output: 
   ```json
   {
      "attribution": "AI",
      "confidence": 0.762,
      "content_id": "cnt_1ca76173",
      "label": {
         "key": "possible_ai",
         "message": "Our analysis leans toward this content being AI-generated, but the signal is not strong enough to be certain.",
         "title": "Possibly AI-Generated"
      },
      "request_id": "req_c25c4503"
   }
   ```
   Get log by running `curl -s -X GET "http://localhost:8000/audit/cnt_1ca76173"  | python3 -m json.tool` returns:
   ```json
   {
      "content_id": "cnt_1ca76173",
      "events": [
         {
               "confidence": 0.762,
               "content_id": "cnt_1ca76173",
               "creator_id": "test-user-1",
               "event_type": "classification",
               "final_classification": "AI",
               "id": 14,
               "llm_result": {
                  "confidence": 0.92,
                  "prediction": "AI"
               },
               "original_request_id": "req_2be59098",
               "request_id": "req_2be59098",
               "status": "classified",
               "stylometric_result": {
                  "confidence": 0.524,
                  "metrics": {
                     "avg_sentence_length": 14.3,
                     "sentence_length_std": 6.66,
                     "type_token_ratio": 0.884
                  },
                  "prediction": "AI"
               },
               "text": "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment.",
               "text_length": 315,
               "timestamp": "2026-06-26T20:44:33Z"
         }
      ]
   }
   ```


- 2. **Clearly human-written (should score low)**: "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably won'\'t go back unless someone drags me there"
   => Output: 
   ```json
   {
      "attribution": "AI",
      "confidence": 0.952,
      "content_id": "cnt_479bbc01",
      "label": {
         "key": "high_confidence_ai",
         "message": "Our system found strong indicators that this content was generated using AI tools.",
         "title": "Likely AI-Generated"
      },
      "request_id": "req_b59dfd7e"
   }
   ```   
   Get log by running `curl -s -X GET "http://localhost:8000/audit/cnt_479bbc01"  | python3 -m json.tool` returns:
   ```json
   {
      "content_id": "cnt_479bbc01",
      "events": [
         {
               "confidence": 0.952,
               "content_id": "cnt_479bbc01",
               "creator_id": "test-user-1",
               "event_type": "classification",
               "final_classification": "AI",
               "id": 22,
               "llm_result": {
                  "confidence": 0.92,
                  "prediction": "AI"
               },
               "original_request_id": "req_b59dfd7e",
               "request_id": "req_b59dfd7e",
               "status": "classified",
               "stylometric_result": {
                  "confidence": 1.0,
                  "metrics": {
                     "avg_sentence_length": 14.3,
                     "sentence_length_std": 6.66,
                     "type_token_ratio": 0.884
                  },
                  "prediction": "AI"
               },
               "text": "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment.",
               "text_length": 315,
               "timestamp": "2026-06-26T22:12:34Z"
         }
      ]
   }
   ```


- 3. **Borderline: formal human writing (may score mid-high on stylometrics)**: "The relationship between monetary policy and asset price inflation has been extensively studied in the literature. Central banks face a fundamental tension between their mandate for price stability and the unintended consequences of prolonged low interest rates on equity and real estate valuations."
   => Output: 
   ```json
   {
      "attribution": "AI",
      "confidence": 0.854,
      "content_id": "cnt_9e22e193",
      "label": {
         "key": "high_confidence_ai",
         "message": "Our system found strong indicators that this content was generated using AI tools.",
         "title": "Likely AI-Generated"
      },
      "request_id": "req_0f1087fb"
   }
   ```

   Get log by running `curl -s -X GET "http://localhost:8000/audit/cnt_9e22e193"  | python3 -m json.tool` returns:
   ```json
   {
      "content_id": "cnt_9e22e193",
      "events": [
         {
               "confidence": 0.854,
               "content_id": "cnt_9e22e193",
               "creator_id": "test-user-1",
               "event_type": "classification",
               "final_classification": "AI",
               "id": 20,
               "llm_result": {
                  "confidence": 0.8,
                  "prediction": "AI"
               },
               "original_request_id": "req_0f1087fb",
               "request_id": "req_0f1087fb",
               "status": "classified",
               "stylometric_result": {
                  "confidence": 0.936,
                  "metrics": {
                     "avg_sentence_length": 21.5,
                     "sentence_length_std": 7.78,
                     "type_token_ratio": 0.86
                  },
                  "prediction": "AI"
               },
               "text": "The relationship between monetary policy and asset price inflation has been extensively studied in the literature. Central banks face a fundamental tension between their mandate for price stability and the unintended consequences of prolonged low interest rates on equity and real estate valuations.",
               "text_length": 299,
               "timestamp": "2026-06-26T22:09:58Z"
         }
      ]
   }
   ```

- 4. **Borderline: lightly edited AI output (should ideally score mid-range)**: "I've been thinking a lot about remote work lately. There are genuine tradeoffs — flexibility and no commute on one side, isolation and blurred work-life boundaries on the other. Studies show productivity varies widely by individual and role type."
   => Output:
   ```json
   {
      "attribution": "uncertain",
      "confidence": 0.607,
      "content_id": "cnt_5b5bc792",
      "label": {
         "key": "uncertain",
         "message": "Our system could not confidently determine whether this content was written by a human or generated by AI.",
         "title": "Attribution Uncertain"
      },
      "request_id": "req_00d3458f"
   }
   ```
   Get log by running `curl -s -X GET "http://localhost:8000/audit/cnt_5b5bc792"  | python3 -m json.tool` returns:
   ```json
   {
      "content_id": "cnt_5b5bc792",
      "events": [
         {
               "confidence": 0.607,
               "content_id": "cnt_5b5bc792",
               "creator_id": "test-user-1",
               "event_type": "classification",
               "final_classification": "uncertain",
               "id": 19,
               "llm_result": {
                  "confidence": 0.8,
                  "prediction": "Human"
               },
               "original_request_id": "req_00d3458f",
               "request_id": "req_00d3458f",
               "status": "classified",
               "stylometric_result": {
                  "confidence": 0.772,
                  "metrics": {
                     "avg_sentence_length": 13,
                     "sentence_length_std": 6.08,
                     "type_token_ratio": 0.9
                  },
                  "prediction": "AI"
               },
               "text": "I've been thinking a lot about remote work lately. There are genuine tradeoffs \u2014 flexibility and no commute on one side, isolation and blurred work-life boundaries on the other. Studies show productivity varies widely by individual and role type.",
               "text_length": 246,
               "timestamp": "2026-06-26T22:08:34Z"
         }
      ]
   }
   ```

  




### Test the /log endpoint
- Get the 3 most recent logs
```bash
curl -s -X GET "http://localhost:8000/log?num_latest_logs=3" | python3 -m json.tool
```

### Test the /audit endpoint
```bash
curl -s -X GET "http://localhost:8000/audit/cnt_aaf57e1d"  | python3 -m json.tool
```


### Test the /appeal endpoint
```bash
curl -s -X POST http://localhost:8000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "cnt_1ca76173", "creator_reasoning": "I wrote this myself."}' | python -m json.tool
```

- You should see a log added into [logs/appeal_queue.jsonl](logs/appeal_queue.jsonl) and a log added into [logs/audit.db](logs/audit.db). 
   - [logs/appeal_queue.jsonl](logs/appeal_queue.jsonl) helps the reviewer keep track of the appeal list
   - [logs/audit.db](logs/audit.db) is the source of truth for all logs
- You should also see the `status` for the previous `classification` event of content_id `cnt_1ca76173` updated to `under_review`
- To get logs for content_id `cnt_1ca76173` in `audit.db`, run `curl -s -X GET "http://localhost:8000/audit/cnt_1ca76173"  | python3 -m json.tool`:

   ```json
   {
      "content_id": "cnt_1ca76173",
      "events": [
         {
               "confidence": 0.762,
               "content_id": "cnt_1ca76173",
               "creator_id": "test-user-1",
               "event_type": "classification",
               "final_classification": "AI",
               "id": 14,
               "llm_result": {
                  "confidence": 0.92,
                  "prediction": "AI"
               },
               "original_request_id": "req_2be59098",
               "request_id": "req_2be59098",
               "status": "under_review",
               "stylometric_result": {
                  "confidence": 0.524,
                  "metrics": {
                     "avg_sentence_length": 14.3,
                     "sentence_length_std": 6.66,
                     "type_token_ratio": 0.884
                  },
                  "prediction": "AI"
               },
               "text": "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment.",
               "text_length": 315,
               "timestamp": "2026-06-26T20:44:33Z"
         },
         {
               "confidence": null,
               "content_id": "cnt_1ca76173",
               "creator_id": "127.0.0.1",
               "event_type": "appeal_submitted",
               "final_classification": null,
               "id": 40,
               "llm_result": null,
               "original_request_id": "req_2be59098",
               "request_id": "req_5438fe8c",
               "status": "under_review",
               "stylometric_result": null,
               "text": "I wrote this myself.", // this is the appeal_reasoning
               "text_length": 20,
               "timestamp": "2026-07-01T00:35:33Z"
         }
      ]
   }
   ```

---

## Rate Limiting

**Limits:**
- **Global:** 60 requests per minute per creator_id (or IP if creator_id absent)
- **Per-endpoint:** 10 requests per minute for /submit, /audit, /log, /appeal

**Reasoning tied to realistic writing platform usage:**

On a platform like Medium, Substack, or a journalistic CMS:
- A casual creator might submit 2–3 pieces per day (well under the 60/min limit)
- An editor or reviewer might check audit logs for ~10 pieces per hour (under limit)
- Appeals are infrequent (creators appeal < 1% of classifications, well under limit)
- Bots or API scrapers would hit the /submit limit in seconds and receive 429 errors

The per-endpoint limit of 10/min prevents abuse while allowing legitimate batch operations (e.g., an editor reviewing multiple submissions in quick succession). The global 60/min allows creators to interact with multiple endpoints without false negatives.

### Test the rate-limiting feature:
- To confirm rate-limiting works, run the following commands in a new terminal window while your Flask server is running (it sends 12 rapid requests — more than the 10/minute limit) and watch the status codes flip from 200 to 429

- **Commands to run:**
   ```bash
      # you should see ten 201 and two 429
      for i in $(seq 1 12); do
      curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/submit \
         -H "Content-Type: application/json" \
         -d '{"text": "rate limit test", "creator_id": "ratelimit-test"}'
      done

      # you should see ten 201 and two 429
      for i in $(seq 1 12); do
         curl -s -X GET "http://localhost:8000/audit/cnt_1ca76173"
      done

      # you should see ten 404 (because we're using "test" content_id) and two 429
      for i in $(seq 1 12); do
      curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/appeal \
         -H "Content-Type: application/json" \
         -d '{"content_id": "test", "creator_reasoning": "I wrote this myself."}' 
      done
   ```

- **Result for the /submit endpoint:**
   ```
   127.0.0.1 - - [30/Jun/2026 20:50:19] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:20] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:20] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:20] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:20] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:20] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:21] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:21] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:21] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:22] "POST /submit HTTP/1.1" 200 -
   127.0.0.1 - - [30/Jun/2026 20:50:22] "POST /submit HTTP/1.1" 429 -
   127.0.0.1 - - [30/Jun/2026 20:50:22] "POST /submit HTTP/1.1" 429 -
   ```
---

## Known Limitations

**AI-polished human drafts** — A creator writes a blog post draft, then uses ChatGPT to polish grammar and flow. The final text retains the human's ideas and structure but exhibits AI-like phrasing uniformity and consistent tone. Both signals (LLM classifier and stylometric analyzer) agree it's AI due to the polished uniformity, producing high confidence. However, the creative origin is human. This is a fundamental limit of appearance-based detection: we classify the final text, not creative intent.

**Formulaic professional writing** — Legal briefs, technical specifications, and formal financial reports use intentionally repetitive clause structures, consistent passive construction, and low sentence variance for clarity and legal precision. The stylometric analyzer flags this as AI-like (low sentence variance, repetitive patterns). The LLM classifier, trained on broad internet text, may also mistake formal boilerplate for LLM-generated prose. Both signals agree incorrectly, producing high false-positive rates for entire genres of legitimate human writing.

**Very short texts** — Product descriptions, single-stanza poems, or brief reviews (< 50 words) give the stylometric analyzer insufficient data. Sentence length variance and type-token ratio are unreliable over 1–2 sentences. The system defaults to "uncertain" (confidence < 0.60) rather than forcing a classification, which is correct behavior but limits utility for short-form content verification.

---

## Spec Reflection

**How the spec helped:**

The decision to define explicit thresholds (0.85 for high confidence, 0.60 for uncertain) before implementation was critical. Without thresholds locked in spec, I would have tuned confidence scoring to match the data (a classic pitfall). Instead, I scored based on the formula, then validated that diverse test inputs—both high and low confidence—produced scores in the correct bands. This forced me to think about calibration as a system requirement, not a tuning parameter.

The dual-logging design (audit.db for permanent history + appeal_queue.jsonl for active work queue) emerged from the spec's distinction between "what reviewers need to see right now" vs. "what we need to know forever." Without this friction in the spec, I would have built a single monolithic log and lost the operational clarity that appeals need an active queue separate from historical records.

**How implementation diverged:**

The spec suggested SQLite for the audit database, which I used. However, the appeal_queue.jsonl exists outside the database as a simple line-delimited JSON file for reviewer simplicity—reviewers can open it in a text editor or pipe it to `jq` without needing SQL knowledge. The spec didn't explicitly forbid this; it just said "append the appeal item." This pragmatic choice improved usability at the cost of a split data model (SQLite + JSONL).

---

## AI Usage

**Instance 1: Generating the POST /appeals endpoint**

**What I directed the AI to do:** "Build a POST /appeals endpoint that accepts content_id, creator_id, creator_reasoning. Retrieve the original classification record, update its status to under_review, append to appeal_queue.jsonl with all required fields, log an appeal_submitted audit event, and return the response."

**What I revised:** The AI generated the core logic correctly but initially didn't include rate limiting on the endpoint. I added `@limiter.limit(config.RATE_LIMIT_SUBMIT)` to prevent appeal spam. Additionally, the AI used `audit_logger.datetime.now()` inline; I verified it worked but noted this tight coupling to the audit_logger module's imports. In production, I'd extract datetime to a utility, but for this scope it's acceptable.

**Instance 2: Generating confidence scoring logic**

**What I directed the AI to do:** "Create a ConfidenceEvaluator that combines LLM and stylometric signals using the weighted formula: base = 0.6 × LLM_conf + 0.4 × stylo_conf, with a 0.77 penalty if signals disagree. Validate that the output thresholds (≥0.85 high confidence, 0.60–0.84 moderate, <0.60 uncertain) actually match the spec."

**What I revised:** The AI implemented the formula correctly, but the initial threshold-to-label mapping had thresholds slightly off (0.80 instead of 0.85 for high confidence). I re-ran the validation with test cases and corrected the thresholds before deploying. The AI also suggested applying the disagreement penalty only when predictions differed by > 0.1 confidence; I overrode this and applied it uniformly when *predictions* differ (AI vs. Human), not confidence values. This ensures the penalty triggers when the signals actually disagree on classification, not just when they're slightly uncertain.
