from idos.models.knowledge import Rule
from idos.rules.engine import RulesEngine, RuleFn, RuleResult


def evaluate_business_quality(context: dict[str, Any]) -> RuleResult:
    score = context.get("assessments", {}).get("business_quality", 0)
    return RuleResult("RULE-001", score >= 70, f"Business quality: {score}/100")


def evaluate_valuation(context: dict[str, Any]) -> RuleResult:
    score = context.get("assessments", {}).get("valuation", 0)
    return RuleResult("RULE-002", score >= 60, f"Valuation: {score}/100")


def evaluate_rerating(context: dict[str, Any]) -> RuleResult:
    score = context.get("assessments", {}).get("rerating", 0)
    return RuleResult("RULE-003", score >= 60, f"Rerating probability: {score}/100")


def evaluate_risk(context: dict[str, Any]) -> RuleResult:
    score = context.get("assessments", {}).get("risk", 0)
    return RuleResult("RULE-004", score >= 50, f"Risk score: {score}/100")


def evaluate_conviction(context: dict[str, Any]) -> RuleResult:
    conv = context.get("conviction", {}).get("overall", 0)
    return RuleResult("RULE-005", conv >= 65, f"Conviction: {conv}/100")


def evaluate_position_weight(context: dict[str, Any]) -> RuleResult:
    port = context.get("portfolio", {})
    current = port.get("position_weight", 0)
    new = port.get("new_position_weight", 0)
    total = current + new
    return RuleResult("RULE-006", total <= 3.0, f"Position weight: {total:.1f}% (max 3%)")


def evaluate_sector_exposure(context: dict[str, Any]) -> RuleResult:
    port = context.get("portfolio", {})
    current = port.get("sector_exposure", 0)
    new = port.get("new_sector_exposure", 0)
    total = current + new
    return RuleResult("RULE-007", total <= 25.0, f"Sector exposure: {total:.1f}% (max 25%)")


def evaluate_asymmetry(context: dict[str, Any]) -> RuleResult:
    asym = context.get("opportunity", {}).get("asymmetry_ratio", 0)
    return RuleResult("RULE-008", asym >= 3.0, f"Asymmetry ratio: {asym:.1f} (min 3.0)")


DEFAULT_RULES = [
    (Rule(id="RULE-001", description="Minimum business quality score for entry",
          priority=100, condition="assessments.business_quality >= 70", action="PASS"),
     evaluate_business_quality),
    (Rule(id="RULE-002", description="Minimum valuation score for entry",
          priority=90, condition="assessments.valuation >= 60", action="PASS"),
     evaluate_valuation),
    (Rule(id="RULE-003", description="Minimum rerating probability score",
          priority=80, condition="assessments.rerating >= 60", action="PASS"),
     evaluate_rerating),
    (Rule(id="RULE-004", description="Maximum risk score allowed",
          priority=100, condition="assessments.risk >= 50", action="PASS"),
     evaluate_risk),
    (Rule(id="RULE-005", description="Minimum overall conviction for entry",
          priority=95, condition="conviction.overall >= 65", action="PASS"),
     evaluate_conviction),
    (Rule(id="RULE-006", description="Maximum portfolio weight per position",
          priority=100, condition="portfolio.position_weight + portfolio.new_position_weight <= 3.0", action="BLOCK"),
     evaluate_position_weight),
    (Rule(id="RULE-007", description="Maximum sector exposure",
          priority=90, condition="portfolio.sector_exposure + portfolio.new_sector_exposure <= 25.0", action="BLOCK"),
     evaluate_sector_exposure),
    (Rule(id="RULE-008", description="Minimum asymmetry ratio 3:1",
          priority=100, condition="opportunity.asymmetry_ratio >= 3.0", action="PASS"),
     evaluate_asymmetry),
]


def register_default_rules(engine: RulesEngine):
    for rule, fn in DEFAULT_RULES:
        engine.register_rule(rule, fn)