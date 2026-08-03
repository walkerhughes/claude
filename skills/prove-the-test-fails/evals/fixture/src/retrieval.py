"""Two lexical retrieval strategies over one small corpus.

Both are expected to satisfy the same result contract: for a given query they
return `Evidence` objects drawn from the corpus, ordered best first.
"""

from dataclasses import dataclass

CORPUS: list[tuple[int, str]] = [
    (1, "chunks pack consecutive turns toward two hundred words"),
    (2, "ranked results break ties on identifier"),
    (3, "the search index is a projection of the chunk table"),
    (4, "a quarter of real turns are under twenty words"),
]


@dataclass(frozen=True)
class Evidence:
    """One retrieved passage and the score the strategy gave it."""

    chunk_id: int
    text: str
    score: float


def _terms(query: str) -> list[str]:
    return [term for term in query.lower().split() if term]


def _matches(term: str, text: str) -> bool:
    return term in text.split()


def lexical_search(query: str) -> list[Evidence]:
    """Full-text ranking: every match scores the same, ties break on identifier."""
    terms = _terms(query)
    hits = [
        Evidence(chunk_id, text, 1.0)
        for chunk_id, text in CORPUS
        if any(_matches(term, text) for term in terms)
    ]
    return sorted(hits, key=lambda evidence: evidence.chunk_id)


def bm25_search(query: str) -> list[Evidence]:
    """BM25-style ranking: a term matching fewer documents contributes more."""
    terms = _terms(query)
    scored: list[Evidence] = []
    for chunk_id, text in CORPUS:
        score = sum(
            1.0 / sum(1 for _, other in CORPUS if _matches(term, other))
            for term in terms
            if _matches(term, text)
        )
        if score:
            scored.append(Evidence(chunk_id, text, score))
    return sorted(scored, key=lambda evidence: (-evidence.score, evidence.chunk_id))
