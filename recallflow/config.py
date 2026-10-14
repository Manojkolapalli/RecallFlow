from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    lyzr_api_key: str
    lyzr_agent_id: str
    lyzr_base_url: str
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str
    qdrant_local_path: Path
    omi_webhook_token: str


def load_settings() -> Settings:
    local_path = Path(os.getenv("QDRANT_LOCAL_PATH", ".qdrant_data"))
    if not local_path.is_absolute():
        local_path = PROJECT_ROOT / local_path

    return Settings(
        lyzr_api_key=os.getenv("LYZR_API_KEY", "").strip(),
        lyzr_agent_id=os.getenv("LYZR_AGENT_ID", "").strip(),
        lyzr_base_url=os.getenv(
            "LYZR_BASE_URL", "https://agent-prod.studio.lyzr.ai/v3"
        ).rstrip("/"),
        qdrant_url=os.getenv("QDRANT_URL", "").strip(),
        qdrant_api_key=os.getenv("QDRANT_API_KEY", "").strip(),
        qdrant_collection=os.getenv(
            "QDRANT_COLLECTION", "recallflow_transcripts"
        ).strip(),
        qdrant_local_path=local_path,
        omi_webhook_token=os.getenv("OMI_WEBHOOK_TOKEN", "").strip(),
    )
