"""The suite guarding the two retrieval strategies."""

import pytest

from retrieval import bm25_search, lexical_search

STRATEGIES = {"bm25": bm25_search, "lexical": lexical_search}


@pytest.mark.parametrize("strategy", sorted(STRATEGIES))
def test_finds_a_phrase_from_the_corpus(strategy: str) -> None:
    results = STRATEGIES[strategy]("identifier")
    assert [evidence.chunk_id for evidence in results] == [2]


@pytest.mark.parametrize("strategy", sorted(STRATEGIES))
def test_empty_query_returns_nothing(strategy: str) -> None:
    assert STRATEGIES[strategy]("") == []


def test_strategies_satisfy_the_same_contract() -> None:
    """Both strategies return the same kind of result for the same query."""
    query = "embeddings"
    assert {type(evidence) for evidence in lexical_search(query)} == {
        type(evidence) for evidence in bm25_search(query)
    }
