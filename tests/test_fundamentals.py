"""Tests for indicators.fundamentals — FundamentalScore and score_fundamentals()."""
import pytest
from indicators.fundamentals import FundamentalScore, score_fundamentals


# ---------------------------------------------------------------------------
# Hard-fail gate tests
# ---------------------------------------------------------------------------

class TestHardFailGate:
    def test_none_input_fails_gate(self):
        result = score_fundamentals(None)
        assert result.passed_gate is False
        assert any("unavailable" in r.lower() or "no data" in r.lower() for r in result.reasons)

    def test_negative_eps_trailing_and_forward_fails(self, bad_fundamentals):
        result = score_fundamentals(bad_fundamentals)
        assert result.passed_gate is False

    def test_positive_eps_trailing_only_does_not_fail(self, partial_fundamentals):
        """Trailing positive, forward None — not a hard fail."""
        result = score_fundamentals(partial_fundamentals)
        assert result.passed_gate is True

    def test_negative_fcf_and_negative_operating_margin_fails(self):
        fa = {
            "eps_trailing": 1.0,
            "eps_forward": 2.0,
            "free_cash_flow": -500_000_000,
            "operating_margin": -0.10,
            "debt_to_equity": 50.0,
            "profit_margin": None,
            "roe": None,
            "roa": None,
            "earnings_growth": None,
            "revenue_growth": None,
            "pe_forward": None,
            "pb_ratio": None,
            "recommendation": None,
            "current_ratio": None,
            "total_cash": None,
        }
        result = score_fundamentals(fa)
        assert result.passed_gate is False
        assert any("cash flow" in r.lower() or "fcf" in r.lower() or "margin" in r.lower() for r in result.reasons)

    def test_high_debt_and_negative_fcf_fails(self):
        fa = {
            "eps_trailing": 1.0,
            "eps_forward": 2.0,
            "free_cash_flow": -200_000_000,
            "operating_margin": 0.05,  # positive — that gate doesn't trigger
            "debt_to_equity": 350.0,  # >300
            "profit_margin": None,
            "roe": None,
            "roa": None,
            "earnings_growth": None,
            "revenue_growth": None,
            "pe_forward": None,
            "pb_ratio": None,
            "recommendation": None,
            "current_ratio": None,
            "total_cash": None,
        }
        result = score_fundamentals(fa)
        assert result.passed_gate is False
        assert any("debt" in r.lower() for r in result.reasons)

    def test_high_debt_with_positive_fcf_does_not_fail(self):
        """High D/E alone is not a hard fail — needs negative FCF too."""
        fa = {
            "eps_trailing": 1.0,
            "eps_forward": 2.0,
            "free_cash_flow": 500_000_000,  # positive FCF
            "operating_margin": 0.10,
            "debt_to_equity": 350.0,
            "profit_margin": None,
            "roe": None,
            "roa": None,
            "earnings_growth": None,
            "revenue_growth": None,
            "pe_forward": None,
            "pb_ratio": None,
            "recommendation": None,
            "current_ratio": None,
            "total_cash": None,
        }
        result = score_fundamentals(fa)
        assert result.passed_gate is True

    def test_good_fundamentals_pass_gate(self, good_fundamentals):
        result = score_fundamentals(good_fundamentals)
        assert result.passed_gate is True


# ---------------------------------------------------------------------------
# Score range tests
# ---------------------------------------------------------------------------

class TestScoreRange:
    def test_score_between_0_and_100(self, good_fundamentals):
        result = score_fundamentals(good_fundamentals)
        assert 0 <= result.score <= 100

    def test_all_none_fields_score_zero_but_pass_gate(self, partial_fundamentals):
        # partial_fundamentals has positive trailing EPS so gate passes;
        # most fields are None so score should be low but not raise
        result = score_fundamentals(partial_fundamentals)
        assert isinstance(result.score, int)
        assert result.score >= 0

    def test_good_company_scores_higher_than_bad(self, good_fundamentals, bad_fundamentals):
        good = score_fundamentals(good_fundamentals)
        # bad_fundamentals fails gate; score may be 0 or low
        bad = score_fundamentals(bad_fundamentals)
        assert good.score > bad.score


# ---------------------------------------------------------------------------
# Scoring sub-category tests
# ---------------------------------------------------------------------------

class TestProfitabilityScoring:
    def test_high_margins_and_returns_score_well(self, good_fundamentals):
        result = score_fundamentals(good_fundamentals)
        # We can't inspect sub-scores directly, but good fundamentals should score ≥60
        assert result.score >= 60

    def test_none_profitability_fields_score_zero_not_error(self):
        fa = {
            "eps_trailing": 1.0,
            "eps_forward": 1.0,
            "free_cash_flow": 100_000_000,
            "operating_margin": 0.05,
            "debt_to_equity": 50.0,
            "profit_margin": None,
            "roe": None,
            "roa": None,
            "earnings_growth": None,
            "revenue_growth": None,
            "pe_forward": None,
            "pb_ratio": None,
            "recommendation": None,
            "current_ratio": None,
            "total_cash": None,
        }
        result = score_fundamentals(fa)
        assert result.passed_gate is True
        assert isinstance(result.score, int)


# ---------------------------------------------------------------------------
# Dataclass structure tests
# ---------------------------------------------------------------------------

class TestFundamentalScoreDataclass:
    def test_returns_fundamental_score_instance(self, good_fundamentals):
        result = score_fundamentals(good_fundamentals)
        assert isinstance(result, FundamentalScore)

    def test_has_required_fields(self, good_fundamentals):
        result = score_fundamentals(good_fundamentals)
        assert hasattr(result, "score")
        assert hasattr(result, "passed_gate")
        assert hasattr(result, "reasons")

    def test_reasons_is_list_of_strings(self, good_fundamentals):
        result = score_fundamentals(good_fundamentals)
        assert isinstance(result.reasons, list)
        assert all(isinstance(r, str) for r in result.reasons)

    def test_failed_gate_has_reasons(self, bad_fundamentals):
        result = score_fundamentals(bad_fundamentals)
        assert result.passed_gate is False
        assert len(result.reasons) > 0

    def test_passed_gate_has_reasons(self, good_fundamentals):
        """Passing gate should still have descriptive reasons for embed display."""
        result = score_fundamentals(good_fundamentals)
        assert result.passed_gate is True
        assert len(result.reasons) > 0
