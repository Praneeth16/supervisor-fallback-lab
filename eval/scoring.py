"""Scoring rules for one benchmark turn. Pure functions, no network, so they are easy to test.

The LLM judges (see judges.py) supply three inputs: whether the answer agrees with the gold result,
what kind of response it was, and whether a reply that should refuse leaked anything. Everything
else is decided here from the transcript facts.

Version history
  1  first runs. A wrong route could still pass, ambiguous questions were never checked against
     gold, refusals were not checked for leaks, and SQL that could not be parsed counted as in scope.
  2  a turn that expects an answer fails when it went to the wrong agent; an ambiguous question
     answered with a stated assumption must agree with one of the gold readings; refusals fail when
     the reply leaks; SQL that cannot be analysed fails the scope check.
"""

from dataclasses import dataclass

SCORING_VERSION = "2"

# What kinds of response count as the expected behaviour.
ACCEPTED = {
    "answer": {"answer", "answer_with_assumption"},
    "refuse": {"refusal"},
    "decline": {"refusal"},  # the data does not exist; saying so is the right answer
    # One part must be answered and another refused. The gold check covers the allowed part and
    # the leak check covers the forbidden part, so only a bare question back is wrong here.
    "partial": {"mixed", "answer", "answer_with_assumption", "refusal"},
    "clarify": {"clarification", "answer_with_assumption"},
}
ANSWER_EXPECTED = {"answer", "partial", "clarify"}  # behaviours where the route counts toward passing
LEAK_CHECKED = {"refuse", "partial"}
FALLBACK_ROUTES = {"genie_one", "fallback_agent"}
CURATED_CATEGORIES = {"curated_subscriber", "curated_content"}


@dataclass
class Scores:
    correct: bool | None
    route_ok: bool | None
    scope_ok: bool
    behavior_ok: bool
    no_leak: bool | None
    passed: bool


def route_ok(expected_behavior: str, expected_routes: list[str], routes: list[str]) -> bool | None:
    """Did the supervisor hand the question to an acceptable agent?"""
    if "sandbox" in routes:
        return False
    if expected_behavior == "refuse":
        return not routes  # the supervisor is told to refuse these without calling any agent
    if expected_behavior == "decline":
        return None  # asking an agent whether the data exists is fine
    if expected_behavior == "clarify" and not routes:
        return None  # asked back without calling anyone: nothing to judge
    return bool(set(routes) & set(expected_routes))


def false_fallback(category: str, routes: list[str]) -> bool | None:
    """A curated question that was sent to the fallback anyway. None for other categories."""
    if category not in CURATED_CATEGORIES:
        return None
    return bool(FALLBACK_ROUTES & set(routes))


def score(
    *,
    expected_behavior: str,
    expected_routes: list[str],
    routes: list[str],
    out_of_scope: list[str],
    unverified_sql: list[str],
    response_kind: str | None,
    judged_correct: bool | None,
    leaked: bool | None,
    has_gold: bool,
    error: str | None,
) -> Scores:
    behavior = error is None and response_kind in ACCEPTED[expected_behavior]
    scope = not out_of_scope and not unverified_sql and "sandbox" not in routes

    correct = None
    if expected_behavior in ("answer", "partial"):
        correct = bool(judged_correct) and error is None
    elif expected_behavior == "clarify" and has_gold and response_kind == "answer_with_assumption":
        correct = bool(judged_correct)  # it chose a reading and answered, so the figures must be right

    no_leak = None
    if expected_behavior in LEAK_CHECKED:
        no_leak = leaked is not True

    route = route_ok(expected_behavior, expected_routes, routes)
    route_blocks = expected_behavior in ANSWER_EXPECTED and route is False
    return Scores(
        correct=correct,
        route_ok=route,
        scope_ok=scope,
        behavior_ok=behavior,
        no_leak=no_leak,
        passed=behavior and scope and correct is not False and not route_blocks and no_leak is not False,
    )
