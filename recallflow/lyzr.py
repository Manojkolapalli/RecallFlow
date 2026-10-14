import json
import re
from dataclasses import dataclass, field
from typing import Any
import uuid

import requests

from recallflow.config import Settings
from recallflow.memory import RetrievedChunk


class LyzrError(RuntimeError):
    """An explicit configuration, API, or response error from Lyzr."""

    def __init__(
        self,
        message: str,
        failure_type: str = "LyzrError",
        upstream_status_code: int | None = None,
        availability_failure: bool = False,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.upstream_status_code = upstream_status_code
        self.availability_failure = availability_failure

    @property
    def diagnostic(self) -> str:
        status = (
            f"upstream HTTP {self.upstream_status_code}"
            if self.upstream_status_code is not None
            else "upstream HTTP status unavailable"
        )
        return f"{self.failure_type}, {status}"


@dataclass(frozen=True)
class ActionItem:
    task: str
    owner: str
    deadline: str


@dataclass(frozen=True)
class MeetingAnalysis:
    summary: str
    decisions: list[str]
    action_items: list[ActionItem]
    key_dates: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    analysis_mode: str = "lyzr"


class LyzrClient:
    CHAT_URL = "https://agent.api.lyzr.app/v2/chat/"
    USER_ID = "recallflow"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.lyzr_api_key and self.settings.lyzr_agent_id)

    def _chat(self, message: str, session_id: str) -> str:
        if not self.configured:
            raise LyzrError(
                "Lyzr is not configured. Set LYZR_API_KEY and LYZR_AGENT_ID in .env."
            )

        try:
            response = requests.post(
                self.CHAT_URL,
                headers={
                    "x-api-key": self.settings.lyzr_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "user_id": self.USER_ID,
                    "agent_id": self.settings.lyzr_agent_id,
                    "session_id": session_id,
                    "message": message,
                },
                timeout=60,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise LyzrError(
                "Lyzr did not respond before the 60-second timeout.",
                failure_type=type(exc).__name__,
                availability_failure=True,
            ) from exc
        except requests.ConnectionError as exc:
            raise LyzrError(
                "Could not connect to Lyzr.",
                failure_type=type(exc).__name__,
                availability_failure=True,
            ) from exc
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise LyzrError(
                "Lyzr rejected the request. Check the agent configuration.",
                failure_type=type(exc).__name__,
                upstream_status_code=status_code,
                availability_failure=status_code is not None and status_code >= 500,
            ) from exc
        except requests.RequestException as exc:
            raise LyzrError(
                "Could not connect to Lyzr.",
                failure_type=type(exc).__name__,
            ) from exc

        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise LyzrError(
                "Lyzr returned a response that was not valid JSON.",
                failure_type=type(exc).__name__,
                upstream_status_code=response.status_code,
            ) from exc

        text = self._find_response_text(payload)
        if not text:
            raise LyzrError(
                "Lyzr returned no answer text.",
                failure_type="EmptyResponseError",
                upstream_status_code=response.status_code,
            )
        return text.strip()

    @staticmethod
    def analyze_locally(title: str, transcript: str, source_id: str) -> MeetingAnalysis:
        del source_id
        sentences = [
            sentence.strip(" -*\t")
            for sentence in re.split(r"(?<=[.!?])\s+|\r?\n+", transcript.strip())
            if sentence.strip(" -*\t")
        ]
        decisions: list[str] = []
        open_questions: list[str] = []
        key_dates: list[str] = []
        action_items: list[ActionItem] = []
        date_pattern = re.compile(
            r"\b(?:"
            r"\d{4}-\d{1,2}-\d{1,2}"
            r"|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"
            r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
            r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
            r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?"
            r"|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
            r"(?:\s+(?:morning|afternoon|evening))?"
            r"|(?:next|this)\s+(?:week|month|Monday|Tuesday|Wednesday|Thursday|"
            r"Friday|Saturday|Sunday)"
            r")(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))?\b",
            re.IGNORECASE,
        )
        action_pattern = re.compile(
            r"^(?P<speaker>[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?):\s*"
            r"(?P<utterance>.*)$"
        )
        task_pattern = re.compile(
            r"\b(?P<owner>I|we)(?:\s+will|['’]ll)\s+"
            r"(?P<verb>develop|handle|document|send|prepare|create|"
            r"follow up|own|build|investigate|draft|update|share|coordinate|"
            r"write|confirm|contact|organize)\s+"
            r"(?P<task>[^.!?]+)",
            re.IGNORECASE,
        )
        deadline_pattern = re.compile(
            r"\b(?:by|before|due(?:\s+on)?|no later than)\s+"
            r"(?:"
            r"\d{4}-\d{1,2}-\d{1,2}"
            r"|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"
            r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
            r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
            r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?"
            r"|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
            r"|tomorrow|today|next week|next month|(?:the\s+)?review"
            r")\b",
            re.IGNORECASE,
        )
        unresolved_pattern = re.compile(
            r"\b(?:undecided|not yet decided|haven['’]t decided|"
            r"have not decided|didn['’]t decide|did not decide|"
            r"not approved|not selected|not confirmed|still deciding|"
            r"open question|unclear|"
            r"not sure whether|tbd|to be determined|remains? open)\b",
            re.IGNORECASE,
        )
        confirmed_pattern = re.compile(
            r"\b(?:decided|agreed|confirmed|approved|selected|chose)\b",
            re.IGNORECASE,
        )
        negated_confirmation_pattern = re.compile(
            r"\b(?:not|never|isn['’]t|is not|wasn['’]t|was not|"
            r"hasn['’]t|has not|haven['’]t|have not|didn['’]t|did not)\s+"
            r"(?:yet\s+)?(?:decided|agree[d]?|confirmed|approved|selected|chose)\b",
            re.IGNORECASE,
        )

        def date_event(
            sentence: str,
            date_match: re.Match[str],
            task_match: re.Match[str] | None,
        ) -> str:
            date = date_match.group(0)
            if task_match:
                task = task_match.group("task")
                deadline_match = deadline_pattern.search(task)
                if deadline_match:
                    task = task[: deadline_match.start()]
                task = re.sub(
                    r"\s+and\s+(?:aim|plan|hope)\s+to\s+"
                    r"(?:finish|complete|deliver)\b.*$",
                    "",
                    task,
                    flags=re.IGNORECASE,
                )
                task = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    task.strip(" ,;:"),
                    flags=re.IGNORECASE,
                )
                event = f"{task} deadline"
            else:
                before_date = sentence[: date_match.start()].strip(" ,;:")
                is_deadline = bool(
                    re.search(
                        r"\b(?:goal|finish|complete|deliver|deadline)\b",
                        before_date,
                        flags=re.IGNORECASE,
                    )
                ) or bool(
                    re.search(
                        r"\b(?:by|before|due)\s*$",
                        before_date,
                        flags=re.IGNORECASE,
                    )
                )
                speaker_match = action_pattern.match(sentence)
                if speaker_match:
                    before_date = sentence[
                        speaker_match.start("utterance") : date_match.start()
                    ].strip(" ,;:")
                before_date = re.sub(
                    r"\s+(?:is|was|are|were)\s+scheduled\s+(?:for|on)$",
                    "",
                    before_date,
                    flags=re.IGNORECASE,
                )
                before_date = re.sub(
                    r"\s+(?:on|by|before|for|due(?:\s+on)?|no later than)$",
                    "",
                    before_date,
                    flags=re.IGNORECASE,
                )
                before_date = re.sub(
                    r"^(?:(?:the\s+team|we|our goal|the goal)\s+)?"
                    r"(?:agreed|decided|confirmed|approved|selected|chose)\s+to\s+"
                    r"|^(?:our goal|the goal)\s+is\s+to\s+"
                    r"|^we(?:\s+will|['’]ll)\s+",
                    "",
                    before_date,
                    flags=re.IGNORECASE,
                )
                event = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    before_date,
                    flags=re.IGNORECASE,
                )
                event = re.sub(
                    r"^(launch|release|ship|deploy)\s+(?:the\s+)?(.+)$",
                    r"\2 \1",
                    event,
                    flags=re.IGNORECASE,
                )
                event = re.sub(
                    r"^(?:finish|complete|deliver)\s+",
                    "",
                    event,
                    flags=re.IGNORECASE,
                )
                event = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    event,
                    flags=re.IGNORECASE,
                )
                event = re.sub(
                    r"^(?:review)\s+(?:the\s+)?(.+?)(?:\s+together)?$",
                    r"\1 review",
                    event,
                    flags=re.IGNORECASE,
                )
                if is_deadline and event:
                    event = f"{event} deadline"
                if not event:
                    after_date = sentence[date_match.end() :].strip(" ,;:.")
                    event = re.sub(
                        r"^(?:is|was|are|were)\s+",
                        "",
                        after_date,
                        flags=re.IGNORECASE,
                    )
            event = re.sub(r"\s+", " ", event).strip(" ,;:.")
            return f"{date} - {event}" if event else date

        for sentence in sentences:
            unresolved = bool(unresolved_pattern.search(sentence))
            if sentence.rstrip().endswith("?") or unresolved:
                open_questions.append(sentence)
            elif (
                confirmed_pattern.search(sentence)
                and not negated_confirmation_pattern.search(sentence)
            ):
                decisions.append(sentence)

            speaker_match = action_pattern.match(sentence)
            utterance = speaker_match.group("utterance") if speaker_match else sentence
            speaker = speaker_match.group("speaker") if speaker_match else None
            utterance_offset = (
                speaker_match.start("utterance") if speaker_match else 0
            )
            task_matches = list(task_pattern.finditer(utterance))
            for match in task_matches:
                task = match.group("task").strip(" ,;:")
                deadline_match = deadline_pattern.search(task)
                deadline = "Not specified"
                if deadline_match:
                    deadline = deadline_match.group(0).strip()
                    task = task[: deadline_match.start()].strip(" ,;:")
                task = re.sub(
                    r"\s+and\s+(?:aim|plan|hope)\s+to\s+"
                    r"(?:finish|complete|deliver)\b.*$",
                    "",
                    task,
                    flags=re.IGNORECASE,
                ).strip(" ,;:")
                if task:
                    task = f"{match.group('verb')} {task}"
                    task = re.sub(
                        r"^(?P<verb>develop|handle|document|send|prepare|create|"
                        r"follow up|own|build|investigate|draft|update|share|"
                        r"coordinate|write|confirm|contact|organize)\s+"
                        r"(?:the|a|an)\s+",
                        r"\g<verb> ",
                        task,
                        flags=re.IGNORECASE,
                    )
                    action_items.append(
                        ActionItem(
                            task=task[0].upper() + task[1:],
                            owner=speaker or match.group("owner").capitalize(),
                            deadline=deadline,
                        )
                    )

            for date_match in date_pattern.finditer(sentence):
                task_match = next(
                    (
                        match
                        for match in task_matches
                        if utterance_offset + match.start()
                        <= date_match.start()
                        < utterance_offset + match.end()
                    ),
                    None,
                )
                key_date = date_event(sentence, date_match, task_match)
                if key_date.casefold() not in {item.casefold() for item in key_dates}:
                    key_dates.append(key_date)

        summary_sentences = [
            f"The discussion focused on {title.strip()}."
            if title.strip()
            else "The discussion covered the transcript's stated topics."
        ]
        if decisions:
            summary_sentences.append(
                "Confirmed decisions include "
                + "; ".join(decision.rstrip(".!?") for decision in decisions[:2])
                + "."
            )
        if key_dates:
            summary_dates = key_dates[:3]
            if len(key_dates) > len(summary_dates):
                summary_dates.append(
                    f"{len(key_dates) - len(summary_dates)} additional date event(s)"
                )
            summary_sentences.append(
                "Key dates include "
                + "; ".join(summary_dates)
                + "."
            )
        elif action_items:
            summary_sentences.append(
                "Explicit commitments include "
                + "; ".join(
                    f"{item.owner}: {item.task}"
                    for item in action_items[:3]
                )
                + "."
            )
        elif open_questions:
            summary_sentences.append(
                "An unresolved issue is "
                + open_questions[0].rstrip(".!?")
                + "."
            )
        else:
            summary_sentences.append(
                "No confirmed decisions or explicit action items were identified."
            )
        summary = (
            "Local fallback analysis — not AI-generated. "
            + " ".join(summary_sentences)
        )

        return MeetingAnalysis(
            summary=summary,
            decisions=decisions or ["No confirmed decisions."],
            action_items=action_items,
            key_dates=key_dates,
            open_questions=open_questions,
            analysis_mode="local_fallback",
        )

    @staticmethod
    def answer_locally(question: str, sources: list[RetrievedChunk]) -> str:
        del question
        excerpts = "\n\n".join(
            f"[{index}] {source.title} ({source.reference}; "
            f"source_id: {source.source_id})\n{source.text}"
            for index, source in enumerate(sources, start=1)
        )
        return (
            "Local fallback — not AI-generated: no answer was synthesized. "
            "If these excerpts do not directly state the answer, the transcript "
            "does not provide enough information to determine it. "
            f"Retrieved transcript evidence follows:\n{excerpts}"
        )

    @classmethod
    def _find_response_text(cls, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            for key in ("response", "answer", "output", "text", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
                if isinstance(value, (dict, list)):
                    nested = cls._find_response_text(value)
                    if nested:
                        return nested
            for key in ("data", "result"):
                nested = cls._find_response_text(payload.get(key))
                if nested:
                    return nested
        if isinstance(payload, list):
            for value in payload:
                nested = cls._find_response_text(value)
                if nested:
                    return nested
        return ""

    def analyze(self, title: str, transcript: str, source_id: str) -> MeetingAnalysis:
        message = f"""Analyze the following meeting transcript. Use only facts explicitly present.
Return valid JSON only, with exactly these keys:
{{
  "summary": "concise summary",
  "decisions": ["decision"],
  "action_items": [{{"task": "specific task", "owner": "person or Unassigned", "deadline": "stated deadline or Not specified"}}]
}}
Use empty arrays when no decisions or actions are stated. Do not infer or invent deadlines.

Meeting title: {title}
Transcript:
{transcript}"""
        response = self._chat(message, session_id=f"analysis-{source_id}")
        return self._parse_analysis(response)

    def answer(self, question: str, sources: list[RetrievedChunk]) -> str:
        if not sources:
            raise LyzrError("Cannot answer without retrieved transcript sources.")

        context = "\n\n".join(
            f"[{index}] Source: {item.title} ({item.reference}; "
            f"source_id: {item.source_id})\n{item.text}"
            for index, item in enumerate(sources, start=1)
        )
        message = f"""Answer the question using only the retrieved transcript excerpts below.
If the excerpts do not contain the answer, say you cannot determine it from the available transcripts.
Cite every factual statement using the matching source marker, such as [1]. Never invent citations.

Retrieved excerpts:
{context}

Question: {question}"""
        answer = self._chat(message, session_id=str(uuid.uuid4()))
        cited_sources = re.findall(r"\[(\d+)\]", answer)
        valid_sources = {str(index) for index in range(1, len(sources) + 1)}
        if any(source not in valid_sources for source in cited_sources):
            raise LyzrError("Lyzr answer cited a source that was not retrieved.")
        return answer

    @staticmethod
    def _parse_analysis(text: str) -> MeetingAnalysis:
        candidate = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
        if fenced:
            candidate = fenced.group(1)
        else:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start : end + 1]

        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LyzrError(
                "Lyzr analysis was not valid JSON; check the agent instructions.",
                failure_type=type(exc).__name__,
            ) from exc
        if not isinstance(data, dict):
            raise LyzrError(
                "Lyzr analysis JSON must be an object.",
                failure_type="ResponseSchemaError",
            )

        summary = data.get("summary")
        decisions = data.get("decisions")
        action_items = data.get("action_items")
        if (
            not isinstance(summary, str)
            or not isinstance(decisions, list)
            or not all(isinstance(item, str) for item in decisions)
            or not isinstance(action_items, list)
        ):
            raise LyzrError(
                "Lyzr analysis JSON does not match the required schema.",
                failure_type="ResponseSchemaError",
            )

        parsed_actions: list[ActionItem] = []
        for item in action_items:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(key), str) for key in ("task", "owner", "deadline")
            ):
                raise LyzrError(
                    "Each action item must contain string task, owner, and deadline fields.",
                    failure_type="ResponseSchemaError",
                )
            parsed_actions.append(
                ActionItem(
                    task=item["task"],
                    owner=item["owner"],
                    deadline=item["deadline"],
                )
            )
        return MeetingAnalysis(summary, decisions, parsed_actions)
