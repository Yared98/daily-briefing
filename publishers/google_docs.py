import os
import requests
from google.oauth2 import service_account
import google.auth.transport.requests


def publish(doc_text: str) -> str:
    """Sobrescreve o documento permanente no Google Docs usando Service Account."""
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "./service_account.json")
    doc_id = os.getenv("GOOGLE_DOC_ID", "")

    if not doc_id:
        raise ValueError("GOOGLE_DOC_ID não configurado no .env.")
    if not os.path.exists(sa_path):
        raise FileNotFoundError(f"Service Account não encontrada em: {sa_path}")

    scopes = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = service_account.Credentials.from_service_account_file(sa_path, scopes=scopes)
    creds.refresh(google.auth.transport.requests.Request())
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}

    doc_meta = requests.get(f"https://docs.googleapis.com/v1/documents/{doc_id}", headers=headers, timeout=15).json()
    content = doc_meta.get("body", {}).get("content", [])
    end_idx = content[-1].get("endIndex", 1) - 1 if content else 1

    reqs = []
    if end_idx > 1:
        reqs.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_idx}}})
    reqs.append({"insertText": {"endOfSegmentLocation": {}, "text": doc_text}})

    resp = requests.post(
        f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
        headers=headers,
        json={"requests": reqs},
        timeout=20,
    )
    resp.raise_for_status()
    return f"https://docs.google.com/document/d/{doc_id}/edit"
