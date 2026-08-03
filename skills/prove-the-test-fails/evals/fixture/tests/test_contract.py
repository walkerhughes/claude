"""The suite guarding the two route matchers."""

import pytest
from routing import regex_router, segment_router

ROUTERS = {"regex": regex_router, "segment": segment_router}


@pytest.mark.parametrize("router", sorted(ROUTERS))
def test_matches_a_route_with_a_parameter(router: str) -> None:
    matches = ROUTERS[router]("/users/42")
    assert [match.route_id for match in matches] == [2]


@pytest.mark.parametrize("router", sorted(ROUTERS))
def test_empty_path_matches_nothing(router: str) -> None:
    assert ROUTERS[router]("") == []


def test_routers_satisfy_the_same_contract() -> None:
    """Both routers return the same kind of result for the same path."""
    path = "/orders/7"
    assert {type(match) for match in regex_router(path)} == {
        type(match) for match in segment_router(path)
    }
