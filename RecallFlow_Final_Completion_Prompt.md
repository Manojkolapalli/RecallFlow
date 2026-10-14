# RecallFlow — Final Completion Prompt

You are working inside my existing RecallFlow repository. Your job is to finish the current project into a reliable, presentable hackathon/portfolio demo. **Do not redesign the project from scratch. Do not add live meeting joining, microphone capture, automatic recording, or speaker diarization.** The intended scope is a user manually pasting a meeting/lecture transcript, saving it, viewing useful analysis, and asking evidence-backed questions later.

## Working rules

1. First inspect the existing project structure, README, configuration, API contracts, tests, `app.py`, and the `recallflow/` modules. Follow the `python-fact-grounded-coding` skill if available.
2. Keep the existing stack and working integrations. Avoid new dependencies unless genuinely necessary.
3. Do not expose, print, log, or ask me to share `.env` values, API keys, tokens, private transcript contents, or credential-bearing URLs. Preserve existing environment-variable names.
4. Do not make live API calls as part of the test suite. Use mocks for external services.
5. Make the smallest set of changes that delivers a coherent, working demo. Do not repeatedly refactor working code, add speculative features, or change the frontend framework.
6. Never claim an external AI service succeeded when it failed. Clearly distinguish Lyzr-powered analysis from local fallback analysis.
7. Do not fabricate meeting facts, decisions, owners, deadlines, answers, citations, or source references. If the transcript does not establish an answer, say so.
8. Run the existing test suite after changes. Fix failures caused by your changes. Do not hide or weaken tests simply to get a green result.
9. If something cannot be verified locally, report that limitation honestly instead of claiming it works.
10. Keep the implementation compatible with the Python version and dependencies already used by the project.

## Product scope

RecallFlow is a **manual-transcript meeting and lecture memory app**:

- The user enters a meeting/lecture title and pastes a transcript.
- The app stores the transcript in the existing Qdrant integration.
- The app attempts Lyzr analysis when configured and reachable.
- If Lyzr is unavailable, the app uses a clearly labelled local fallback.
- The user can ask questions about saved transcript content.
- Answers should be grounded in retrieved transcript context and include genuine source references/citation indices where supported.
- The UI should make the distinction between successful AI analysis and local fallback obvious.

## Tasks

### 1. Inspect and stabilize the existing flow

Trace the actual execution path from Streamlit `app.py` through the API and into `recallflow/lyzr.py` and `recallflow/memory.py`.

Confirm and fix, with minimal edits:

- Transcript submission validates title and transcript text.
- A successful save reports the number of chunks stored.
- Errors are shown clearly without exposing secrets or stack traces to ordinary users.
- The app handles Lyzr connection failures gracefully and does not imply that Lyzr analysis succeeded.
- API response fields remain consistent between the backend and Streamlit UI.
- Qdrant storage/retrieval, transcript source IDs, and citation references are preserved.
- Repeated submissions do not make the UI misleading about which transcript was saved or analyzed.

Do not change the known working Qdrant setup unless a concrete bug is demonstrated.

### 2. Make fallback meeting analysis useful and honest

When Lyzr is unavailable, local fallback analysis must be explicitly labelled **“Local fallback analysis — not AI-generated.”** Use deterministic Python/text processing only; no new paid service and no invented facts.

Present these sections consistently:

- **Summary:** two or three concise sentences describing the main topics and known dates. Do not dump the entire transcript or copy the first speaker turns as the summary.
- **Key decisions:** include only clearly confirmed decisions. If none are explicitly confirmed, display “No confirmed decisions.”
- **Action items:** extract explicit commitments, tasks, owners, and deadlines only when supported by transcript wording. Recognize common forms such as “I’ll handle…”, “I will develop…”, “I’ll document…”, and equivalent explicit commitments. Do not classify a meeting/review being scheduled as an action item. Do not invent an owner or deadline.
- **Key dates:** display concise date/event pairs, not full transcript sentences. Avoid duplicate events.
- **Open questions:** capture explicitly unresolved issues or questions. Do not label an already-decided issue as unresolved.

The local fallback must be modest and transparent. Do not present it as equivalent to LLM reasoning. If deterministic extraction cannot confidently identify a field, prefer an empty/neutral result over guessing.

Use this sample transcript as a regression fixture:

Alex: Welcome to the project kickoff. Our goal is to finish the first prototype by October 20.

Priya: I'll handle the frontend and prepare the initial screens by October 17.

Rahul: I'll develop the backend API and aim to finish the first version by October 18.

Alex: We'll review the prototype together on October 21 at 10 AM.

Priya: We haven't decided which deployment platform to use. We'll decide during the review.

Rahul: I'll document the API endpoints before the review.

Alex: Great. Priya owns the frontend, Rahul owns the backend, and we'll check everyone's progress during the review.

For this fixture, the analysis should identify the prototype deadline (October 20), Priya's frontend task (October 17), Rahul's backend API task (October 18), Rahul's API documentation task (before the review), the October 21 10 AM review, and the unresolved deployment platform. It must not claim a deployment platform was chosen. Do not force a “decision” if the transcript contains no clearly confirmed decision.

### 3. Make question answering evidence-grounded

- Keep the current retrieval and question-answering architecture.
- Use retrieved transcript context rather than answering from unrelated/general knowledge.
- Return the best available source references/citation indices from actual retrieved chunks.
- If the context does not answer a question, clearly say that the transcript does not provide enough information.
- Never fabricate a citation, source ID, quote, or answer.
- If Lyzr is unavailable, the local fallback should return relevant retrieved excerpts and their source references. It must not pretend a full natural-language AI answer was generated.
- Ensure the UI renders the answer and references clearly and does not hide them below irrelevant content.

### 4. Finish the Streamlit user experience

Keep the existing Streamlit approach and the current project theme. Improve only what is necessary for a clear demo:

- Clear title and one-sentence explanation of what RecallFlow does.
- A simple meeting/lecture title input and transcript text area.
- A clearly named **Save and analyze** button.
- Loading/progress feedback where feasible.
- Distinct success, warning, and error messages.
- A clean, readable analysis area with the sections listed above.
- A clearly visible question input and **Ask** button after a transcript is saved.
- Answers and source citations displayed together.
- A visible but unobtrusive note when local fallback is active.
- Useful empty states before any transcript is submitted.
- No fake controls, dead buttons, placeholder results presented as real, or claims of automatic live-meeting capture.

Do not spend time on elaborate animations or a frontend rewrite. Correctness, clarity, and demo reliability matter more.

### 5. Tests and validation

Add or update focused tests for the actual functions and contracts. Include tests for:

- The kickoff transcript's fallback summary, action items, dates, decisions, and open question.
- Rahul's backend task being included.
- A scheduled review not being misclassified as an action item.
- Summary and key dates not copying whole speaker lines.
- The undecided deployment platform remaining unresolved.
- Lyzr connection failure triggering the documented fallback behavior.
- API response compatibility with the Streamlit app.
- Question answers using real retrieved references and declining unsupported claims.
- Existing Qdrant and API behavior using mocks rather than live requests.

Then run the project's existing test suite using its available Python environment. Also run a syntax/import check if appropriate. Do not report tests as passing unless you actually ran them. If a test cannot run because of a missing dependency/environment issue, state exactly which test and why.

### 6. Documentation and final handoff

Update `README.md` so it accurately explains:

- What RecallFlow does and does not do.
- Current architecture and data flow.
- Required environment-variable **names only** (never their values).
- Installation/setup and commands to run the backend and Streamlit UI in separate terminals.
- How to paste a transcript, view analysis, and ask a question.
- How Lyzr mode differs from local fallback mode.
- Known limitations, especially that users currently provide transcripts manually and live meeting joining/recording/speaker identification are not implemented.

Check `.gitignore` for `.env`, virtual environments, caches, and other local secrets/artifacts. Do not remove existing useful ignore rules. Never add `.env` or credentials to Git.

## Final acceptance criteria

The project is ready to hand off when:

1. The backend starts using the documented command.
2. Streamlit starts using the documented command.
3. A transcript can be saved to Qdrant.
4. The UI shows useful, honestly labelled analysis whether Lyzr succeeds or the local fallback is used.
5. Questions can be asked against saved transcript content and the UI shows genuine source references.
6. Unsupported answers are not fabricated.
7. The test suite passes, or any unrelated/environment blocker is clearly documented.
8. README setup steps match the actual repository.
9. No secrets are exposed or committed.
10. No unimplemented live-meeting features are advertised.

## Final response to me

When done, provide a concise report with:

- What you changed and why.
- Exact files changed.
- Test command and actual result.
- Exact commands to start the backend and UI.
- Any remaining known limitation or manual verification needed.

Do not ask me to make design decisions unless the project is genuinely blocked. Prefer a conservative, working result over adding features.
