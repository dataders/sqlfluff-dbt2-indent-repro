"""Characterize the observed bug and its isolated diagnostic control."""

import pytest

from repro import CASES, investigate


@pytest.mark.parametrize("case", CASES)
def test_replay_and_controls(case):
    result = investigate(case)
    should_cycle = case in {"nested", "no_inner_conditional", "no_outer_conditional"}
    assert result["dbt2"]["two_state_cycle"] == should_cycle
    assert result["builtin_jinja"]["changed"][1] is False
    assert result["raw_rendered_sql"]["changed"][1] is False
    assert result["diagnostic_normalization"]["changed"][1] is False
