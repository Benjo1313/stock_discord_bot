"""Fundamental quality scoring and gate for the three-layer signal architecture.

Layer 1 of the composite signal:
  - Hard-fail gate: AND-condition rejections for clearly distressed companies
  - Scoring: 0-100 across four sub-categories (each 0-25)
    profitability | growth | financial health | valuation
"""
from dataclasses import dataclass, field


@dataclass
class FundamentalScore:
    score: int          # 0-100
    passed_gate: bool
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Hard-fail gate conditions (AND logic — all conditions in a group must be
# true to trigger a fail, so partial weakness does not block turnaround plays)
# ---------------------------------------------------------------------------

def _check_hard_fails(fa: dict) -> list[str]:
    """Return a list of hard-fail reasons (empty = gate passed)."""
    fails = []

    eps_trail = fa.get("eps_trailing")
    eps_fwd = fa.get("eps_forward")
    if _is_negative(eps_trail) and _is_negative(eps_fwd):
        fails.append("Negative EPS (trailing and forward) — company not yet profitable")

    fcf = fa.get("free_cash_flow")
    op_margin = fa.get("operating_margin")
    if _is_negative(fcf) and _is_negative(op_margin):
        fails.append("Negative FCF and negative operating margin — burning cash with no operating profit")

    de = fa.get("debt_to_equity")
    if de is not None and de > 300 and _is_negative(fcf):
        fails.append(f"Extreme debt (D/E {de:.0f}%) with negative FCF — high insolvency risk")

    return fails


# ---------------------------------------------------------------------------
# Sub-category scoring (each 0-25)
# ---------------------------------------------------------------------------

def _score_profitability(fa: dict) -> tuple[int, list[str]]:
    """Profit margin, operating margin, ROE, ROA."""
    score = 0
    reasons = []

    profit_margin = fa.get("profit_margin")
    if profit_margin is not None:
        if profit_margin >= 0.20:
            score += 7
            reasons.append(f"Profit margin {profit_margin:.0%} (strong)")
        elif profit_margin >= 0.10:
            score += 4
            reasons.append(f"Profit margin {profit_margin:.0%} (healthy)")
        elif profit_margin >= 0:
            score += 1
            reasons.append(f"Profit margin {profit_margin:.0%} (thin)")
        else:
            reasons.append(f"Profit margin {profit_margin:.0%} (negative)")

    op_margin = fa.get("operating_margin")
    if op_margin is not None:
        if op_margin >= 0.25:
            score += 6
            reasons.append(f"Operating margin {op_margin:.0%} (excellent)")
        elif op_margin >= 0.15:
            score += 4
            reasons.append(f"Operating margin {op_margin:.0%} (good)")
        elif op_margin >= 0:
            score += 1
            reasons.append(f"Operating margin {op_margin:.0%} (thin)")

    roe = fa.get("roe")
    if roe is not None:
        if roe >= 0.20:
            score += 6
            reasons.append(f"ROE {roe:.0%} (excellent)")
        elif roe >= 0.10:
            score += 3
            reasons.append(f"ROE {roe:.0%} (good)")
        elif roe >= 0:
            score += 1

    roa = fa.get("roa")
    if roa is not None:
        if roa >= 0.10:
            score += 6
            reasons.append(f"ROA {roa:.0%} (strong)")
        elif roa >= 0.05:
            score += 3
            reasons.append(f"ROA {roa:.0%} (solid)")
        elif roa >= 0:
            score += 1

    return min(score, 25), reasons


def _score_growth(fa: dict) -> tuple[int, list[str]]:
    """Revenue growth, earnings growth, forward vs trailing EPS."""
    score = 0
    reasons = []

    rev_growth = fa.get("revenue_growth")
    if rev_growth is not None:
        if rev_growth >= 0.20:
            score += 9
            reasons.append(f"Revenue growth {rev_growth:.0%} (high growth)")
        elif rev_growth >= 0.10:
            score += 6
            reasons.append(f"Revenue growth {rev_growth:.0%} (solid)")
        elif rev_growth >= 0:
            score += 2
            reasons.append(f"Revenue growth {rev_growth:.0%} (flat)")
        else:
            reasons.append(f"Revenue growth {rev_growth:.0%} (declining)")

    earn_growth = fa.get("earnings_growth")
    if earn_growth is not None:
        if earn_growth >= 0.20:
            score += 9
            reasons.append(f"Earnings growth {earn_growth:.0%} (strong)")
        elif earn_growth >= 0.10:
            score += 6
            reasons.append(f"Earnings growth {earn_growth:.0%} (solid)")
        elif earn_growth >= 0:
            score += 2

    eps_trail = fa.get("eps_trailing")
    eps_fwd = fa.get("eps_forward")
    if eps_trail is not None and eps_fwd is not None and eps_trail > 0:
        if eps_fwd > eps_trail:
            score += 7
            reasons.append(f"Forward EPS ${eps_fwd:.2f} > trailing ${eps_trail:.2f} (growth expected)")
        elif eps_fwd >= eps_trail * 0.95:
            score += 3

    return min(score, 25), reasons


def _score_financial_health(fa: dict) -> tuple[int, list[str]]:
    """Debt/equity, current ratio, FCF, cash position."""
    score = 0
    reasons = []

    de = fa.get("debt_to_equity")
    if de is not None:
        if de < 50:
            score += 7
            reasons.append(f"D/E {de:.0f}% (very low debt)")
        elif de < 100:
            score += 5
            reasons.append(f"D/E {de:.0f}% (manageable debt)")
        elif de < 200:
            score += 2
            reasons.append(f"D/E {de:.0f}% (moderate debt)")
        else:
            reasons.append(f"D/E {de:.0f}% (high leverage)")

    current_ratio = fa.get("current_ratio")
    if current_ratio is not None:
        if current_ratio >= 2.0:
            score += 6
            reasons.append(f"Current ratio {current_ratio:.1f}x (strong liquidity)")
        elif current_ratio >= 1.5:
            score += 4
            reasons.append(f"Current ratio {current_ratio:.1f}x (good liquidity)")
        elif current_ratio >= 1.0:
            score += 2
            reasons.append(f"Current ratio {current_ratio:.1f}x (adequate)")

    fcf = fa.get("free_cash_flow")
    if fcf is not None:
        if fcf > 1_000_000_000:
            score += 7
            reasons.append(f"FCF ${fcf/1e9:.1f}B (strong cash generation)")
        elif fcf > 0:
            score += 4
            reasons.append(f"FCF ${fcf/1e6:.0f}M (positive)")
        else:
            reasons.append(f"FCF ${fcf/1e6:.0f}M (negative)")

    total_cash = fa.get("total_cash")
    if total_cash is not None and total_cash > 0:
        score += 5
        reasons.append(f"Cash ${total_cash/1e9:.1f}B")

    return min(score, 25), reasons


def _score_valuation(fa: dict) -> tuple[int, list[str]]:
    """Forward P/E, P/B, analyst consensus."""
    score = 0
    reasons = []

    pe_fwd = fa.get("pe_forward")
    if pe_fwd is not None and pe_fwd > 0:
        if pe_fwd < 15:
            score += 10
            reasons.append(f"Forward P/E {pe_fwd:.1f}x (attractive valuation)")
        elif pe_fwd < 25:
            score += 6
            reasons.append(f"Forward P/E {pe_fwd:.1f}x (reasonable)")
        elif pe_fwd < 40:
            score += 2
            reasons.append(f"Forward P/E {pe_fwd:.1f}x (elevated)")
        else:
            reasons.append(f"Forward P/E {pe_fwd:.1f}x (expensive)")

    pb = fa.get("pb_ratio")
    if pb is not None and pb > 0:
        if pb < 2:
            score += 8
            reasons.append(f"P/B {pb:.1f}x (below-book value)")
        elif pb < 4:
            score += 4
            reasons.append(f"P/B {pb:.1f}x (fair)")

    rec = fa.get("recommendation")
    if rec in ("strong_buy", "buy"):
        score += 7
        reasons.append(f"Analyst consensus: {rec.replace('_', ' ').title()}")
    elif rec in ("hold",):
        score += 3
        reasons.append("Analyst consensus: Hold")

    return min(score, 25), reasons


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_fundamentals(fa: dict | None) -> FundamentalScore:
    """Score a fundamentals dict returned by get_fundamentals().

    Returns a FundamentalScore with:
      - score: 0-100 composite
      - passed_gate: False if hard-fail conditions are met
      - reasons: human-readable strings for Discord embed display
    """
    if fa is None:
        return FundamentalScore(
            score=0,
            passed_gate=False,
            reasons=["Fundamentals data unavailable — cannot verify company quality"],
        )

    hard_fails = _check_hard_fails(fa)
    if hard_fails:
        return FundamentalScore(score=0, passed_gate=False, reasons=hard_fails)

    all_reasons: list[str] = []

    prof_score, prof_reasons = _score_profitability(fa)
    growth_score, growth_reasons = _score_growth(fa)
    health_score, health_reasons = _score_financial_health(fa)
    val_score, val_reasons = _score_valuation(fa)

    all_reasons.extend(prof_reasons)
    all_reasons.extend(growth_reasons)
    all_reasons.extend(health_reasons)
    all_reasons.extend(val_reasons)

    total = prof_score + growth_score + health_score + val_score

    if not all_reasons:
        all_reasons.append("Limited fundamental data available")

    return FundamentalScore(score=total, passed_gate=True, reasons=all_reasons)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_negative(val) -> bool:
    return val is not None and val < 0
