from dataclasses import dataclass, field
from typing import Any, Callable
from idos.models.knowledge import Rule


@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    details: str = ""


RuleFn = Callable[[dict[str, Any]], RuleResult]


class RulesEngine:
    def __init__(self):
        self._rules: list[Rule] = []
        self._rule_fns: dict[str, RuleFn] = {}

    def register_rule(self, rule: Rule, fn: RuleFn | None = None):
        self._rules.append(rule)
        if fn:
            self._rule_fns[rule.id] = fn

    def evaluate(self, rule_id: str, context: dict[str, Any]) -> RuleResult:
        fn = self._rule_fns.get(rule_id)
        if fn:
            return fn(context)
        return RuleResult(rule_id=rule_id, passed=True, details="No evaluator registered")

    def evaluate_all(self, context: dict[str, Any]) -> list[RuleResult]:
        results = []
        for rule in self._rules:
            if rule.active:
                results.append(self.evaluate(rule.id, context))
        return results

    def evaluate_active(self, context: dict[str, Any]) -> list[RuleResult]:
        return [r for r in self.evaluate_all(context) if r.passed]

    def clear(self):
        self._rules.clear()
        self._rule_fns.clear()
