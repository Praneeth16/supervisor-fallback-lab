import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_overlap import find_overlaps, similarity, sql_tokens, text_tokens


def test_no_evaluation_question_is_also_an_agent_example():
    assert find_overlaps() == []


def test_same_query_and_same_wording_are_caught():
    a = "SELECT COUNT(*) AS n FROM {rights}.license_agreement WHERE agreement_status = 'Active'"
    b = "select count(*) as n\nfrom {rights}.license_agreement\nwhere agreement_status = 'Active'"
    assert similarity(sql_tokens(a), sql_tokens(b)) == 1.0
    assert (
        similarity(text_tokens("paying subscribers by plan pls"), text_tokens("How many paying subscribers by plan?"))
        >= 0.6
    )


def test_same_query_over_another_period_is_not_the_same():
    a = "SELECT COUNT(*) FROM {billing}.payment WHERE payment_date >= DATE'2025-01-01' AND method_type = 'Gift Card'"
    b = "SELECT SUM(amount) FROM {billing}.refund WHERE processing_date >= DATE'2026-10-01'"
    assert similarity(sql_tokens(a), sql_tokens(b)) < 0.8
