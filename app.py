from pathlib import Path
import uuid

import streamlit as st
from qdrant_client.http.exceptions import ApiException

from recallflow.config import load_settings
from recallflow.lyzr import LyzrClient, LyzrError, MeetingAnalysis
from recallflow.memory import RetrievedChunk, TranscriptMemory


st.set_page_config(page_title="RecallFlow", page_icon="🧠", layout="centered")
settings = load_settings()


@st.cache_resource
def get_memory(
    url: str,
    api_key: str,
    collection: str,
    local_path: str,
) -> TranscriptMemory:
    return TranscriptMemory(
        collection=collection,
        local_path=Path(local_path),
        url=url,
        api_key=api_key,
    )


st.title("RecallFlow")
st.caption("Turn meetings and lectures into searchable, actionable memory.")

if settings.qdrant_url:
    st.caption("Transcript memory: connected to configured Qdrant.")
else:
    st.caption("Transcript memory: persistent local Qdrant (.qdrant_data).")
if LyzrClient(settings).configured:
    st.caption("AI analysis and answers: Lyzr configured.")
else:
    st.info("Lyzr is not configured; local transcript analysis and evidence-only answers are available.")

memory = get_memory(
    settings.qdrant_url,
    settings.qdrant_api_key,
    settings.qdrant_collection,
    str(settings.qdrant_local_path),
)
lyzr = LyzrClient(settings)

with st.form("transcript_form"):
    title = st.text_input(
        "Meeting or lecture title",
        placeholder="Project kickoff",
        help="A title is required to save and analyze a transcript.",
    )
    transcript = st.text_area(
        "Transcript",
        height=240,
        placeholder="Paste the transcript here...",
    )
    submitted = st.form_submit_button("Save and analyze")

if submitted:
    st.session_state.pop("analysis", None)
    st.session_state.pop("analysis_fallback", None)
    st.session_state.pop("saved_transcript_title", None)
    st.session_state.pop("saved_source_id", None)
    st.session_state.pop("saved_chunk_count", None)
    if not title.strip():
        st.warning("Enter a meeting or lecture title before submitting.")
    elif not transcript.strip():
        st.warning("Paste a transcript before submitting.")
    else:
        title = title.strip()
        transcript = transcript.strip()
        source_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{title}|{transcript}")
        )
        try:
            with st.spinner("Saving transcript to Qdrant..."):
                chunk_count = memory.ingest(title, transcript, source_id)
        except ImportError:
            st.error(
                "Qdrant embedding support is unavailable. Install dependencies from "
                "requirements.txt, including qdrant-client[fastembed]."
            )
        except (ApiException, RuntimeError):
            st.error("Qdrant is unavailable or failed to store the transcript.")
        else:
            st.session_state["saved_transcript_title"] = title
            st.session_state["saved_source_id"] = source_id
            st.session_state["saved_chunk_count"] = chunk_count
            st.success(f"Saved {chunk_count} transcript chunk(s) to Qdrant.")
            if not lyzr.configured:
                analysis = lyzr.analyze_locally(title, transcript, source_id)
                st.session_state["analysis"] = analysis
                st.session_state["analysis_fallback"] = True
                st.warning("Local fallback analysis shown; Lyzr is not configured.")
            else:
                with st.spinner("Extracting summary, decisions, and actions with Lyzr..."):
                    try:
                        analysis = lyzr.analyze(title, transcript, source_id)
                    except LyzrError as exc:
                        if exc.availability_failure:
                            analysis = lyzr.analyze_locally(title, transcript, source_id)
                            st.session_state["analysis"] = analysis
                            st.session_state["analysis_fallback"] = True
                            st.warning("Local fallback analysis shown; Lyzr is unavailable.")
                        else:
                            st.error(str(exc))
                    else:
                        st.session_state["analysis"] = analysis

analysis = st.session_state.get("analysis")
if isinstance(analysis, MeetingAnalysis):
    st.subheader("Meeting intelligence")
    saved_title = st.session_state.get("saved_transcript_title", "Saved transcript")
    saved_chunk_count = st.session_state.get("saved_chunk_count", 0)
    st.caption(f"Analysis for {saved_title} · {saved_chunk_count} stored chunk(s)")
    if (
        st.session_state.get("analysis_fallback")
        or analysis.analysis_mode == "local_fallback"
    ):
        st.info("Local fallback analysis — not AI-generated.")
    st.markdown("**Summary**")
    st.write(analysis.summary)

    st.markdown("**Key decisions**")
    if analysis.decisions:
        for decision in analysis.decisions:
            st.markdown(f"- {decision}")
    else:
        st.write("No explicit decisions found.")

    st.markdown("**Action items and deadlines**")
    if analysis.action_items:
        for item in analysis.action_items:
            st.markdown(
                f"- **{item.task}** — {item.owner}; deadline: {item.deadline}"
            )
    else:
        st.write("No explicit action items found.")

    st.markdown("**Key dates**")
    if analysis.key_dates:
        for date_event in analysis.key_dates:
            st.markdown(f"- {date_event}")
    else:
        st.write("No explicit dates found.")

    st.markdown("**Open questions**")
    if analysis.open_questions:
        for open_question in analysis.open_questions:
            st.markdown(f"- {open_question}")
    else:
        st.write("No explicit open questions found.")
elif not st.session_state.get("saved_source_id"):
    st.info("Paste a transcript above to save it and see its analysis here.")

st.divider()
st.subheader("Ask your transcript memory")
st.caption("Questions are searched against saved transcript excerpts in Qdrant.")
with st.form("question_form"):
    question = st.text_input("Question", placeholder="What did we decide about the launch?")
    ask = st.form_submit_button("Ask")

if ask:
    if not question.strip():
        st.warning("Enter a question before submitting.")
    else:
        try:
            sources: list[RetrievedChunk] = memory.search(question.strip())
        except ImportError:
            st.error("Qdrant embedding support is unavailable. Install requirements.txt.")
        except (ApiException, RuntimeError):
            st.error("Qdrant is unavailable or failed to search transcript memory.")
        else:
            if not sources:
                st.info(
                    "No matching transcript context was found; the saved transcripts "
                    "do not provide enough information to answer."
                )
            else:
                if not lyzr.configured:
                    answer = lyzr.answer_locally(question.strip(), sources)
                    st.info("Local fallback answer — not AI-generated.")
                    st.markdown("**Answer**")
                    st.write(answer)
                    st.markdown(
                        "**Sources**\n" + "\n".join(
                            f"- [{index}] {source.title} — {source.reference} "
                            f"(source_id: {source.source_id})"
                            for index, source in enumerate(sources, start=1)
                        )
                    )
                else:
                    with st.spinner("Answering from retrieved transcript context..."):
                        try:
                            answer = lyzr.answer(question.strip(), sources)
                        except LyzrError as exc:
                            if exc.availability_failure:
                                answer = lyzr.answer_locally(question.strip(), sources)
                                st.info(
                                    "Local fallback answer — not AI-generated; "
                                    "Lyzr is unavailable."
                                )
                                st.markdown("**Answer**")
                                st.write(answer)
                                st.markdown(
                                    "**Sources**\n"
                                    + "\n".join(
                                        f"- [{index}] {source.title} — {source.reference} "
                                        f"(source_id: {source.source_id})"
                                        for index, source in enumerate(sources, start=1)
                                    )
                                )
                            else:
                                st.error(str(exc))
                        else:
                            st.markdown("**Answer**")
                            st.write(answer)
                            st.markdown(
                                "**Sources**\n"
                                + "\n".join(
                                    f"- [{index}] {source.title} — {source.reference} "
                                    f"(source_id: {source.source_id})"
                                    for index, source in enumerate(sources, start=1)
                                )
                            )
