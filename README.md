# RecallFlow

RecallFlow turns manually supplied meeting or lecture transcripts into
searchable memory. Save a title and transcript, review clearly labelled
analysis, and ask questions against retrieved transcript excerpts with source
references.

RecallFlow does not join meetings, record audio, or identify speakers. The
optional Omi webhook accepts transcript text produced by an external Omi
integration; it does not add those capabilities to RecallFlow.

## How it works

- **Streamlit UI (`app.py`):** validates the title and transcript, stores
  transcript chunks in Qdrant, requests Lyzr analysis when configured, and
  otherwise presents deterministic local analysis. Questions search saved
  chunks before the UI asks Lyzr or shows the retrieved evidence as a local
  fallback.
- **FastAPI backend (`recallflow.api`):** exposes transcript ingestion,
  question-answering, and health endpoints using the same Qdrant and Lyzr
  integrations. The Streamlit app currently calls those integrations directly;
  it does not proxy its requests through FastAPI.
- **Qdrant:** stores transcript chunks with a source ID, title, and chunk
  reference. Question results display references from the chunks actually
  retrieved.
- **Lyzr:** when configured and reachable, analyzes transcripts and answers
  questions from retrieved excerpts. If it is unconfigured or unavailable,
  RecallFlow labels local analysis as **“Local fallback analysis — not
  AI-generated.”** Local question fallback shows retrieved excerpts instead
  of claiming to synthesize a natural-language answer. When context is
  missing, RecallFlow says it cannot determine the answer from the available
  transcript evidence.

The local analysis uses conservative text patterns. It may miss phrasing that
does not match those patterns; it does not invent decisions, owners, dates, or
deadlines.

## Requirements and configuration

Use Python 3.10 or newer. Install the dependencies from the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and configure the variable names below as needed.
Do not commit `.env`.

| Variable | Purpose |
| --- | --- |
| `LYZR_API_KEY` | Enables Lyzr analysis and question answering. |
| `LYZR_AGENT_ID` | Selects the configured Lyzr agent. |
| `LYZR_BASE_URL` | Retained in settings for compatibility; the current client does not use this setting. |
| `QDRANT_URL` | Optional Qdrant server URL. Leave unset to use persistent local Qdrant storage. |
| `QDRANT_API_KEY` | Optional key for a Qdrant server that requires authentication. |
| `QDRANT_COLLECTION` | Qdrant collection name. |
| `QDRANT_LOCAL_PATH` | Filesystem path for persistent local Qdrant storage. |
| `OMI_WEBHOOK_TOKEN` | Optional authentication token for the separate Omi webhook service. |

When `QDRANT_URL` is unset, the app uses `.qdrant_data`. Embedded local Qdrant
storage is intended for a single process at a time. To run the FastAPI backend
and Streamlit UI simultaneously, configure both to use the same reachable
Qdrant server via `QDRANT_URL`; otherwise run one app process at a time when
using local embedded storage. The first ingestion may download the configured
FastEmbed model.

## Run the demo

Start the FastAPI backend in one terminal from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn recallflow.api:app --host 127.0.0.1 --port 8000
```

Start the Streamlit UI in a separate terminal:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

The backend health check is `GET /health`. Its transcript and question
endpoints are `POST /api/transcripts` and `POST /api/questions`. The Streamlit
UI opens at the local URL printed by Streamlit.

In the UI:

1. Enter a meeting or lecture title and paste its transcript.
2. Select **Save and analyze**. The UI reports the stored chunk count and
   identifies which transcript the analysis belongs to.
3. Review the summary, key decisions, action items, key dates, and open
   questions. Empty or unconfirmed fields are shown neutrally.
4. Enter a question and select **Ask**. The answer and the references for the
   retrieved transcript excerpts are displayed together.

Qdrant failures are reported without exposing exception details. Lyzr
availability failures use the labelled local fallback; other Lyzr errors are
shown explicitly and are not represented as successful AI analysis.

## Optional Omi transcript webhook

The separate webhook service can ingest transcript text delivered by an
external Omi integration. It requires a reachable Qdrant server, configured
with `QDRANT_URL`, and an `OMI_WEBHOOK_TOKEN`. It does not connect to or record
a meeting.

Run it with:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn omi_webhook:app --host 127.0.0.1 --port 8001
```

The service accepts `POST /omi/memory` for completed-memory payloads and
`POST /omi/transcript` for transcript-segment payloads. Authenticate requests
with the configured token. Keep the webhook private or expose it only through
a properly secured HTTPS endpoint.

## Tests

Run the backend, API-contract, and Streamlit UI tests from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
```

The tests use mocks for Qdrant, embedding, and Lyzr integrations; they do not
make live service calls.
