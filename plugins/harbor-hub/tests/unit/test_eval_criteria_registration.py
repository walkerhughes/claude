"""A zero-arg @criterion must not also be registered by hand.

rewardkit's decorator self-registers a criterion that takes nothing but
`workspace` (session.py: `if not factory_params and not shared: factory()`),
so a following `criteria.<name>()` scores it a second time.

The bug is silent: two registrations of the same criterion usually agree, and
the mean of [1.0, 1.0] is still 1.0. It only surfaces when they disagree --
which is what a live hub probe does on a blip -- and then it reads as a reward
regression rather than a double count. It also doubles every hub call the
criterion makes, which doubles the flake surface that makes it visible.

Static on purpose: importing the check modules would mean adding
harbor-rewardkit to the dev group, and the shape of the mistake is visible in
the source.
"""

import ast
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[2] / "evals"
CHECKS = sorted(EVALS.glob("*/tests/*/check.py"))


def _self_registering(tree: ast.Module) -> set[str]:
    """Names of @criterion functions that take only `workspace`."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        decorated = any(
            (isinstance(d, ast.Name) and d.id == "criterion")
            or (isinstance(d, ast.Call) and getattr(d.func, "id", None) == "criterion")
            for d in node.decorator_list
        )
        # A shared=True criterion does not self-register.
        shared = any(
            isinstance(d, ast.Call) and any(k.arg == "shared" for k in d.keywords) for d in node.decorator_list
        )
        args = node.args
        only_workspace = len(args.posonlyargs) + len(args.args) == 1 and not args.kwonlyargs
        if decorated and only_workspace and not shared:
            names.add(node.name)
    return names


def _explicit_criteria_calls(tree: ast.Module) -> set[str]:
    """Names called as `criteria.<name>(...)` at module level."""
    calls = set()
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if isinstance(func, ast.Attribute) and getattr(func.value, "id", "") == "criteria":
            calls.add(func.attr)
    return calls


def test_evals_have_check_modules():
    """Guard the glob: a rename that finds nothing would pass every case below."""
    assert CHECKS, f"no eval check modules found under {EVALS}"


@pytest.mark.parametrize("path", CHECKS, ids=lambda p: f"{p.parts[-4]}/{p.parts[-2]}")
def test_no_double_registered_criterion(path: Path):
    tree = ast.parse(path.read_text())
    doubled = _self_registering(tree) & _explicit_criteria_calls(tree)
    assert not doubled, (
        f"{path.relative_to(EVALS.parent)}: {sorted(doubled)} self-register at "
        f"decoration time and are registered again by hand, so each is scored "
        f"twice. Drop the criteria.<name>() call."
    )
