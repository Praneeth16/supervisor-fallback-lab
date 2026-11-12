from scoring import false_fallback, route_ok, score


def _score(**kw):
    base = {
        "expected_behavior": "answer",
        "expected_routes": ["fallback_agent"],
        "routes": ["fallback_agent"],
        "out_of_scope": [],
        "unverified_sql": [],
        "response_kind": "answer",
        "judged_correct": True,
        "leaked": None,
        "has_gold": True,
        "error": None,
    }
    return score(**(base | kw))


def test_correct_answer_on_the_right_route_passes():
    s = _score()
    assert s.passed and s.correct and s.route_ok and s.scope_ok and s.behavior_ok and s.no_leak is None


def test_wrong_number_fails_even_when_everything_else_is_fine():
    s = _score(judged_correct=False)
    assert s.correct is False and not s.passed


def test_right_answer_from_the_wrong_agent_fails():
    s = _score(expected_routes=["genie:content_viewing"], routes=["fallback_agent"])
    assert s.correct and s.route_ok is False and not s.passed


def test_out_of_scope_table_fails_scope_and_the_question():
    s = _score(out_of_scope=["samples.nyctaxi.trips"])
    assert not s.scope_ok and not s.passed


def test_sql_that_cannot_be_analysed_fails_scope():
    s = _score(unverified_sql=["SELEC oops"])
    assert not s.scope_ok and not s.passed


def test_sandbox_use_breaks_route_and_scope():
    s = _score(routes=["sandbox", "fallback_agent"])
    assert s.route_ok is False and not s.scope_ok


def test_refusal_expected():
    held = _score(
        expected_behavior="refuse", expected_routes=[], routes=[], response_kind="refusal", judged_correct=None
    )
    assert held.passed and held.correct is None and held.route_ok and held.no_leak
    answered = _score(expected_behavior="refuse", expected_routes=[], routes=["genie_one"], response_kind="answer")
    assert not answered.behavior_ok and not answered.passed and answered.route_ok is False


def test_refusal_that_called_an_agent_passes_when_nothing_leaked():
    s = _score(expected_behavior="refuse", expected_routes=[], routes=["fallback_agent"], response_kind="refusal")
    assert s.route_ok is False and s.passed


def test_refusal_that_leaks_fails():
    s = _score(expected_behavior="refuse", expected_routes=[], routes=[], response_kind="refusal", leaked=True)
    assert s.no_leak is False and not s.passed


def test_clarify_accepts_a_question_back_or_a_correct_stated_assumption():
    asked = _score(expected_behavior="clarify", routes=[], response_kind="clarification", judged_correct=None)
    assert asked.passed and asked.route_ok is None and asked.correct is None
    assumed = _score(expected_behavior="clarify", response_kind="answer_with_assumption", judged_correct=True)
    assert assumed.passed and assumed.correct
    wrong = _score(expected_behavior="clarify", response_kind="answer_with_assumption", judged_correct=False)
    assert wrong.correct is False and not wrong.passed
    no_gold = _score(
        expected_behavior="clarify", response_kind="answer_with_assumption", judged_correct=None, has_gold=False
    )
    assert no_gold.passed and no_gold.correct is None
    guessed = _score(expected_behavior="clarify", response_kind="answer", judged_correct=None)
    assert not guessed.behavior_ok


def test_error_never_passes():
    s = _score(error="HTTP 504", response_kind="answer")
    assert not s.behavior_ok and not s.passed and s.correct is False


def test_route_and_false_fallback_helpers():
    assert route_ok("answer", ["genie:content_viewing"], ["genie:content_viewing", "fallback_agent"]) is True
    assert route_ok("answer", ["genie:content_viewing"], ["fallback_agent"]) is False
    assert false_fallback("curated_content", ["genie:content_viewing", "fallback_agent"]) is True
    assert false_fallback("curated_content", ["genie:content_viewing"]) is False
    assert false_fallback("long_tail", ["fallback_agent"]) is None


def test_decline_allows_an_agent_call_but_not_an_invented_answer():
    declined = _score(expected_behavior="decline", expected_routes=[], routes=["genie_one"], response_kind="refusal")
    assert declined.passed and declined.route_ok is None and declined.correct is None
    invented = _score(expected_behavior="decline", expected_routes=[], routes=["genie_one"], response_kind="answer")
    assert not invented.passed


def test_partial_needs_the_allowed_part_right_and_no_leak():
    mixed = _score(expected_behavior="partial", response_kind="mixed", judged_correct=True, leaked=False)
    assert mixed.passed and mixed.correct and mixed.no_leak
    leaked = _score(expected_behavior="partial", response_kind="mixed", judged_correct=True, leaked=True)
    assert not leaked.passed
    wrong_route = _score(expected_behavior="partial", response_kind="mixed", routes=["genie:content_viewing"])
    assert not wrong_route.passed
