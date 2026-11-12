from report import mcnemar, paired


def test_mcnemar_exact():
    assert mcnemar(0, 0) == 1.0
    assert mcnemar(3, 3) == 1.0
    assert round(mcnemar(0, 5), 4) == 0.0625
    assert round(mcnemar(1, 9), 4) == 0.0215


def test_paired_counts_only_turns_both_arms_answered():
    rows = [
        {"arm": "genie_one", "question_id": "a", "passed": True},
        {"arm": "custom_agent", "question_id": "a", "passed": True},
        {"arm": "genie_one", "question_id": "b", "passed": False},
        {"arm": "custom_agent", "question_id": "b", "passed": True},
        {"arm": "genie_one", "question_id": "c", "passed": False},
        {"arm": "custom_agent", "question_id": "c", "passed": False},
        {"arm": "genie_one", "question_id": "d", "passed": True},
    ]
    result = paired(rows)
    assert (result["both"], result["only_a"], result["only_b"], result["neither"]) == (1, 0, 1, 1)
    assert result["p"] == 1.0
