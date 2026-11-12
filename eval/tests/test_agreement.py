from judge_agreement import agreement, parse_label, pick


def test_agreement_and_kappa():
    same = agreement([(True, True), (False, False), (True, True), (False, False)])
    assert same == {"n": 4, "agreement": 1.0, "kappa": 1.0}
    chance = agreement([(True, True), (True, False), (False, True), (False, False)])
    assert chance["agreement"] == 0.5 and chance["kappa"] == 0.0
    one_label = agreement([(True, True), (True, True)])
    assert one_label["agreement"] == 1.0 and one_label["kappa"] is None
    assert agreement([]) == {"n": 0, "agreement": None, "kappa": None}


def test_pick_is_seeded_and_covers_every_behaviour():
    pool = [{"expected_behavior": b, "id": f"{b}{i}"} for b in ("answer", "refuse", "clarify") for i in range(10)]
    first = pick([dict(r) for r in pool], 9, seed=7)
    again = pick([dict(r) for r in pool], 9, seed=7)
    assert [r["id"] for r in first] == [r["id"] for r in again]
    assert {r["expected_behavior"] for r in first} == {"answer", "refuse", "clarify"}
    assert len(pick([dict(r) for r in pool[:4]], 9, seed=7)) == 4


def test_parse_label():
    assert parse_label("correct", " Yes ") is True
    assert parse_label("leaked", "false") is False
    assert parse_label("correct", "") is None
    assert parse_label("response_kind", "Refusal") == "refusal"
