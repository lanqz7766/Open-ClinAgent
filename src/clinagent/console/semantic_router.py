from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Any

from clinagent.console.workspace import ROUTING_KEYWORDS, WORKFLOWS, augment_message_with_ingest_context

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_GENERAL_CHAT_QUERIES = [
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "how are you",
    "who are you",
    "what can you do",
    "chat with me",
    "talk with me",
    "help me think this through",
    "answer a general question",
]


def _tokenize(text: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9\s]+", " ", text.lower())
    words = [token for token in _TOKEN_RE.findall(normalized) if token]
    if not words:
        return []
    unigrams = words
    bigrams = [f"{words[index]}_{words[index + 1]}" for index in range(len(words) - 1)]
    return unigrams + bigrams


def _document_text(workflow: dict[str, Any]) -> str:
    parts = [
        str(workflow.get("id") or ""),
        str(workflow.get("title") or ""),
        str(workflow.get("module") or ""),
        str(workflow.get("summary") or ""),
        " ".join(str(item) for item in workflow.get("tags", [])),
        " ".join(str(item) for item in workflow.get("examples", [])),
        " ".join(str(item) for item in workflow.get("tools", [])),
        " ".join(sorted(ROUTING_KEYWORDS.get(str(workflow.get("module") or ""), set()))),
    ]
    if workflow.get("id") == "general_chat":
        parts.append(" ".join(_GENERAL_CHAT_QUERIES))
    return "\n".join(part for part in parts if part)


@lru_cache(maxsize=1)
def _semantic_index() -> dict[str, Any]:
    documents = []
    doc_frequency: Counter[str] = Counter()
    for workflow in WORKFLOWS:
        tokens = _tokenize(_document_text(workflow))
        token_counts = Counter(tokens)
        for token in token_counts:
            doc_frequency[token] += 1
        documents.append(
            {
                "workflow_id": workflow["id"],
                "module": workflow["module"],
                "title": workflow["title"],
                "token_counts": token_counts,
            }
        )

    doc_count = max(len(documents), 1)
    idf = {
        token: math.log((1 + doc_count) / (1 + frequency)) + 1.0
        for token, frequency in doc_frequency.items()
    }

    for document in documents:
        weighted = {
            token: float(count) * idf[token]
            for token, count in document["token_counts"].items()
            if token in idf
        }
        norm = math.sqrt(sum(value * value for value in weighted.values())) or 1.0
        document["vector"] = {token: value / norm for token, value in weighted.items()}

    return {"documents": documents, "idf": idf}


def _query_vector(message: str, ingest_context: dict[str, Any] | None = None) -> dict[str, float]:
    enriched = augment_message_with_ingest_context(message, ingest_context)
    tokens = _tokenize(enriched)
    token_counts = Counter(tokens)
    index = _semantic_index()
    idf = index["idf"]
    weighted = {
        token: float(count) * idf[token]
        for token, count in token_counts.items()
        if token in idf
    }
    norm = math.sqrt(sum(value * value for value in weighted.values())) or 1.0
    return {token: value / norm for token, value in weighted.items()}


def retrieve_semantic_workflow_candidates(
    message: str,
    ingest_context: dict[str, Any] | None = None,
    *,
    top_k: int = 4,
) -> list[dict[str, Any]]:
    query_vector = _query_vector(message, ingest_context)
    if not query_vector:
        return []

    candidates: list[dict[str, Any]] = []
    for document in _semantic_index()["documents"]:
        score = 0.0
        for token, value in query_vector.items():
            score += value * document["vector"].get(token, 0.0)
        if score <= 0:
            continue
        candidates.append(
            {
                "workflow_id": document["workflow_id"],
                "module": document["module"],
                "title": document["title"],
                "score": round(score, 4),
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:top_k]
