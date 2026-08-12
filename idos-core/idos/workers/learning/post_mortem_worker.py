from datetime import datetime
from typing import Any
from uuid import uuid4

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.learning.feedback import FeedbackCollector, FeedbackRecord
from idos.learning.hitrate import HitRateTracker
from idos.learning.loop import ContinuousImprovementLoop
from idos.learning.patterns import PatternLearner
from idos.learning.weights import WeightAdjuster
from idos.models.enums import OpportunityStatus
from idos.state.machine import OpportunityStateMachine
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

class PostMortemWorker(BaseWorker):
    """Generates post-mortem analysis after an opportunity is exited.

    Triggers: after EXITED status.
    Transitions: EXITED -> POST_MORTEM -> ARCHIVED.
    """
    name = "post_mortem_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.llm = config.get("llm_service") or LLMClient(
            provider=config.get("provider", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
            fallback_model=config.get("fallback_model", ""),
            fallback_providers=config.get("fallback_providers", []),
        )
        prompts_path = config.get("prompts_path", "")
        self.registry = PromptRegistry(prompts_path) if prompts_path else PromptRegistry()
        self.state_machine = OpportunityStateMachine()

        # Learning loop components
        self.feedback = FeedbackCollector()
        self.weights = WeightAdjuster(base_weights={
            "BusinessAssessmentEngine": 0.25,
            "ValuationAssessmentEngine": 0.20,
            "RecoveryAssessmentEngine": 0.15,
            "RiskAssessmentEngine": 0.10,
            "PortfolioAssessmentEngine": 0.10,
            "wyckoff": 0.10,
            "ResearchWorker": 0.10,
        })
        self.patterns = PatternLearner()
        self.hitrates = HitRateTracker()
        self.improvement_loop = ContinuousImprovementLoop(
            self.feedback, self.weights, self.patterns, self.hitrates,
        )

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        opp_id = context.get("opp_id", "")
        base_path = context.get("base_path", "")
        exit_reason = context.get("exit_reason", "unknown")
        if not ticker or not opp_id:
            msg = "Both ticker and opp_id are required"
            raise ValueError(msg)

        from pathlib import Path
        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        journal = JournalRepository(bp / "idos-journal")

        opp = sqlite.get_opportunity(opp_id)
        if not opp:
            msg = f"Opportunity {opp_id} not found"
            raise ValueError(msg)

        current_status = OpportunityStatus(opp["status"])
        if not self.state_machine.can_transition(current_status, OpportunityStatus.POST_MORTEM):
            return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                    "reason": f"Cannot run post-mortem from {current_status}"}

        decisions = self._load_decisions(ticker, opp_id, journal)
        assessments = self._load_assessments(ticker, opp_id, journal)
        position = journal.load_position(ticker)
        hypotheses = journal.load_hypotheses(ticker, opp_id)
        wyckoff_analyses = self._load_wyckoff_analyses(ticker, opp_id, journal)
        entry_snapshot = journal.load_entry_snapshot(ticker, opp_id)

        post_mortem = self._llm_post_mortem(ticker, decisions, assessments, position,
                                            exit_reason, wyckoff_analyses, hypotheses,
                                            entry_snapshot)

        pm_id = f"pm-{uuid4().hex[:8]}"
        pm_record = {
            "id": pm_id,
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": exit_reason,
            "analysis": post_mortem,
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }

        pm_path = journal.opportunity_path(ticker, opp_id) / "post_mortem"
        pm_path.mkdir(parents=True, exist_ok=True)
        import yaml
        with open(pm_path / f"{pm_id}.yml", "w", encoding="utf-8") as f:
            yaml.dump(pm_record, f, default_flow_style=False, allow_unicode=True)

        opp["status"] = OpportunityStatus.POST_MORTEM.value
        opp["updated_at"] = datetime.now(AR_TZ).isoformat()
        sqlite.save_opportunity(opp)
        sqlite.record_transition(opp_id, current_status.value, "POST_MORTEM",
                                 cause="post_mortem_generated", worker="post_mortem_worker")

        if self.state_machine.can_transition(OpportunityStatus.POST_MORTEM, OpportunityStatus.ARCHIVED):
            opp["status"] = OpportunityStatus.ARCHIVED.value
            opp["updated_at"] = datetime.now(AR_TZ).isoformat()
            sqlite.save_opportunity(opp)
            sqlite.record_transition(opp_id, "POST_MORTEM", "ARCHIVED",
                                     cause="post_mortem_approved", worker="post_mortem_worker")

        sqlite.log_event("post_mortem:completed", {
            "opp_id": opp_id, "ticker": ticker,
            "exit_reason": exit_reason,
            "pm_id": pm_id,
            "archived": True,
        })

        # Feed learning loop
        self._feed_learning_loop(ticker, opp_id, decisions, assessments, post_mortem, exit_reason, wyckoff_analyses)
        loop_result = self.improvement_loop.run()

        wyckoff_accuracy = post_mortem.get("wyckoff_accuracy", "no_evaluada")

        hypothesis_stats = self._hypothesis_stats(hypotheses)

        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "completed",
            "archived": True,
            "pm_id": pm_id,
            "exit_reason": exit_reason,
            "lessons": post_mortem.get("lessons_learned", []),
            "wyckoff_accuracy": wyckoff_accuracy,
            "wyckoff_lessons": post_mortem.get("wyckoff_lessons", []),
            "hypotheses": hypothesis_stats,
            "learning_loop": {
                "weights_adjusted": loop_result.weights_adjusted,
                "patterns_identified": loop_result.patterns_identified,
                "feedback_processed": loop_result.feedback_processed,
                "hit_rates_updated": loop_result.hit_rates_updated,
                "top_patterns": loop_result.top_patterns,
                "underperformers": loop_result.underperformers,
                "wyckoff_alerts": loop_result.wyckoff_alerts,
            },
        }

    def _hypothesis_stats(self, hypotheses: list[dict]) -> dict[str, Any]:
        if not hypotheses:
            return {"count": 0, "predictions_evaluated": 0, "predictions_met": 0}
        evaluated = 0
        met = 0
        for h in hypotheses:
            for p in h.get("predictions", []):
                if p.get("met") is not None:
                    evaluated += 1
                    if p.get("met"):
                        met += 1
        stats = {
            "count": len(hypotheses),
            "predictions_evaluated": evaluated,
            "predictions_met": met,
        }
        if evaluated:
            stats["predictions_met_pct"] = round(met / evaluated * 100, 1)
        return stats

    def _feed_learning_loop(self, ticker: str, opp_id: str,
                            decisions: list[dict], assessments: list[dict],
                            post_mortem: dict, exit_reason: str,
                            wyckoff_analyses: list[dict] | None = None):
        """Extract structured feedback from post-mortem and feed into learning loop."""
        thesis_correct = post_mortem.get("thesis_was_correct", False)
        outcome = "success" if thesis_correct else "failure"

        # Record feedback for each engine
        for a in assessments:
            engine = a.get("engine", "unknown")
            score = a.get("score", 0)
            rec = FeedbackRecord(
                ticker=ticker,
                prediction_id=f"{opp_id}-{engine}",
                predicted_direction="up" if score >= 50 else "down",
                actual_direction="up" if thesis_correct else "down",
                predicted_price=0,
                actual_price=0,
                outcome=outcome,
                engine=engine,
                analyst="post_mortem",
                notes=exit_reason,
            )
            self.feedback.record(rec)

        # Record Wyckoff feedback
        wyckoff_correct = post_mortem.get("wyckoff_phase_was_correct", False)
        wyckoff_outcome = "success" if wyckoff_correct else "failure"
        wyckoff_accuracy = post_mortem.get("wyckoff_accuracy", "no_evaluada")

        last_wyckoff = wyckoff_analyses[-1] if wyckoff_analyses else {}
        wyckoff_rec = FeedbackRecord(
            ticker=ticker,
            prediction_id=f"{opp_id}-wyckoff",
            predicted_direction=last_wyckoff.get("phase", "unknown"),
            actual_direction="up" if thesis_correct else "down",
            predicted_price=last_wyckoff.get("price_target", 0) or 0,
            actual_price=0,
            outcome=wyckoff_outcome,
            engine="wyckoff",
            analyst="post_mortem",
            notes=f"accuracy={wyckoff_accuracy}, phase={last_wyckoff.get('phase', '?')}",
        )
        self.feedback.record(wyckoff_rec)

        # Record pattern observation
        features = {
            "exit_reason": exit_reason,
            "conviction_at_entry": decisions[0].get("conviction_score", 50) if decisions else 50,
            "sector": assessments[0].get("sector", "unknown") if assessments else "unknown",
            "wyckoff_phase": last_wyckoff.get("phase", "unknown") if wyckoff_analyses else "none",
            "wyckoff_score": last_wyckoff.get("score", 0) if wyckoff_analyses else 0,
        }
        self.patterns.observe(ticker, features, outcome)

        # Update hit rates per engine
        for a in assessments:
            engine = a.get("engine", "unknown")
            key = f"engine:{engine}"
            if thesis_correct:
                self.hitrates.record_hit(key)
            else:
                self.hitrates.record_miss(key)

        key = "engine:wyckoff"
        if wyckoff_correct:
            self.hitrates.record_hit(key)
        else:
            self.hitrates.record_miss(key)

    def _load_decisions(self, ticker: str, opp_id: str, journal: JournalRepository) -> list[dict[str, Any]]:
        dec_path = journal.opportunity_path(ticker, opp_id) / "decisions"
        if not dec_path.exists():
            return []
        import yaml
        decisions = []
        for f in sorted(dec_path.glob("*.yml")):
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data:
                    decisions.append(data)
        return decisions

    def _load_assessments(self, ticker: str, opp_id: str, journal: JournalRepository) -> list[dict[str, Any]]:
        ass_path = journal.opportunity_path(ticker, opp_id) / "assessments"
        if not ass_path.exists():
            return []
        import yaml
        assessments = []
        for f in sorted(ass_path.glob("*.yml")):
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data:
                    assessments.append(data)
        return assessments

    def _load_wyckoff_analyses(self, ticker: str, opp_id: str, journal: JournalRepository) -> list[dict[str, Any]]:
        w_path = journal.opportunity_path(ticker, opp_id) / "wyckoff"
        if not w_path.exists():
            return []
        import yaml
        analyses = []
        for f in sorted(w_path.glob("*.yml")):
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data:
                    analyses.append(data)
        return analyses

    def _llm_post_mortem(self, ticker: str, decisions: list[dict],
                         assessments: list[dict], position: dict | None,
                         exit_reason: str,
                         wyckoff_analyses: list[dict] | None = None,
                         hypotheses: list[dict] | None = None,
                         entry_snapshot: dict | None = None) -> dict[str, Any]:
        prompt = (
            f"Genera un Post-Mortem de inversion para {ticker}.\n\n"
            f"Razon de salida: {exit_reason}\n\n"
        )

        # Snapshot del momento de entrada: tesis, fundamentales, catalizadores,
        # riesgos y dominios tal como estaban al momento de la compra.
        if entry_snapshot:
            thesis = entry_snapshot.get("thesis") or {}
            entry = entry_snapshot.get("entry") or {}
            prompt += "=== TESIS AL MOMENTO DE ENTRADA (snapshot) ===\n"
            prompt += f"- Tesis: {thesis.get('tesis_inversion') or 'N/D'}\n"
            prompt += f"- Resumen: {thesis.get('resumen_ejecutivo') or 'N/D'}\n"
            prompt += f"- Opinion de valoracion: {thesis.get('opinion_valoracion') or 'N/D'}\n"
            prompt += f"- Score DDD: {thesis.get('score_general') or 'N/D'}\n"
            prompt += (
                f"- Entrada: precio ${entry.get('entry_price') or '?'}, "
                f"fecha {entry.get('entry_date') or '?'}, "
                f"stop ${entry.get('stop_loss') or '?'}, "
                f"target ${entry.get('target_price') or '?'}\n"
            )
            catalysts = entry_snapshot.get("catalysts") or []
            if catalysts:
                prompt += "\nCatalizadores al momento de entrada:\n"
                for c in catalysts:
                    prompt += (f"- {c.get('descripcion', '?')} "
                               f"(impacto {c.get('impacto', '?')}, "
                               f"probabilidad {c.get('probabilidad_pct', '?')}%)\n")
            risks = entry_snapshot.get("risks") or []
            if risks:
                prompt += "\nRiesgos al momento de entrada:\n"
                for r in risks:
                    prompt += f"- {r.get('riesgo', '?')} ({r.get('probabilidad', '?')}/{r.get('impacto', '?')})\n"
            dominios = entry_snapshot.get("dominios") or {}
            if dominios:
                prompt += "\nDominios evaluados (rating):\n"
                for k, v in dominios.items():
                    rating = v.get("rating", "?") if isinstance(v, dict) else v
                    prompt += f"- {k}: {rating}\n"

        prompt += "\nDecisiones registradas:\n"
        for d in decisions:
            prompt += f"- {d.get('type','?')}: {d.get('rationale','')[:200]}\n"

        prompt += f"\nAssessments:\n"
        for a in assessments:
            prompt += f"- {a.get('engine','?')} score={a.get('score','?')}: {a.get('findings',[])}\n"

        if position:
            prompt += (
                f"\nPosición: entrada a ${position.get('avg_entry_price',0)}, "
                f"peso {position.get('weight_pct',0)}%\n"
            )

        if hypotheses:
            prompt += "\nHipótesis de inversión (árbol HMF):\n"
            for h in hypotheses:
                status = h.get("status", "?")
                statement = h.get("statement", "")
                prompt += f"- [{status}] {statement[:160]}\n"
                for fc in h.get("falsification", []):
                    if fc.get("triggered"):
                        prompt += f"  - FALSACIÓN disparada: {fc.get('condition', '')[:120]}\n"
                for p in h.get("predictions", []):
                    met = p.get("met")
                    if met is not None:
                        prompt += (f"  - Predicción {p.get('metric','?')}: "
                                   f"{'CUMPLIDA' if met else 'FALLIDA'} "
                                   f"(esperado {p.get('expected', p.get('expected_value',''))}, "
                                   f"real {p.get('actual', p.get('actual_value',''))})\n")

        # Wyckoff del momento de entrada (snapshot) o ultimo analisis como fallback.
        entry_wyckoff = (entry_snapshot or {}).get("technical") or {}
        if entry_wyckoff:
            last_w = entry_wyckoff
            eventos = []
            llm_resp = last_w.get("llm_response") or {}
            if not isinstance(llm_resp, dict):
                llm_resp = {}
            for e in (llm_resp.get("eventos_wyckoff_detectados") or []):
                if isinstance(e, dict):
                    eventos.append(f"{e.get('evento','?')}({e.get('confianza','?')})")
            pruebas = llm_resp.get("pruebas_compra") or {}
            pasan = pruebas.get("pruebas_pasan", "?")
            total_p = pruebas.get("total_pruebas", "?")
            prompt += (
                f"\nAnalisis Wyckoff al momento de entrada (snapshot):\n"
                f"- Fase: {last_w.get('wyckoff_phase') or last_w.get('phase', '?')}\n"
                f"- Score: {last_w.get('wyckoff_score') or last_w.get('score', '?')}/100\n"
                f"- Confianza: {last_w.get('wyckoff_confidence') or last_w.get('confidence', '?')}\n"
                f"- Eventos detectados: {', '.join(eventos) if eventos else 'ninguno'}\n"
                f"- Pruebas de compra: {pasan}/{total_p}\n"
                f"- Punto de entrada: {last_w.get('wyckoff_entry_point') or last_w.get('entry_point', '?')}\n"
                f"- Precio objetivo: {last_w.get('wyckoff_price_target') or last_w.get('price_target', '?')}\n"
                f"\nPreguntas para evaluar el analisis Wyckoff:\n"
                f"1. La fase detectada fue correcta dado el movimiento real del precio?\n"
                f"2. Los eventos Wyckoff (PS, SC, Spring, LPS, SOS, etc.) fueron validos?\n"
                f"3. El punto de entrada recomendado ({last_w.get('wyckoff_entry_point') or last_w.get('entry_point', '?')}) habria funcionado?\n"
                f"4. Las pruebas de compra que pasaron realmente predijeron el resultado?\n"
                f"5. Compara contra el analisis del cierre: el activo evoluciono como esperaba el analisis de entrada?\n"
            )
        elif wyckoff_analyses:
            last_w = wyckoff_analyses[-1]
            eventos = []
            llm_resp = last_w.get("llm_response") or {}
            if not isinstance(llm_resp, dict):
                llm_resp = {}
            for e in (llm_resp.get("eventos_wyckoff_detectados") or []):
                if isinstance(e, dict):
                    eventos.append(f"{e.get('evento','?')}({e.get('confianza','?')})")
            pruebas = llm_resp.get("pruebas_compra") or {}
            pasan = pruebas.get("pruebas_pasan", "?")
            total_p = pruebas.get("total_pruebas", "?")
            prompt += (
                f"\nAnalisis Wyckoff (ultimo disponible):\n"
                f"- Fase: {last_w.get('phase', '?')}\n"
                f"- Score: {last_w.get('score', '?')}/100\n"
                f"- Confianza: {last_w.get('confidence', '?')}\n"
                f"- Eventos detectados: {', '.join(eventos) if eventos else 'ninguno'}\n"
                f"- Pruebas de compra: {pasan}/{total_p}\n"
                f"- Punto de entrada: {last_w.get('entry_point', '?')}\n"
                f"- Precio objetivo: {last_w.get('price_target', '?')}\n"
            )

        prompt += (
            "\nResponde en JSON:\n"
            '{{"exit_analysis": "...", "thesis_was_correct": true|false, '
            '"what_went_wrong": ["..."], "what_went_right": ["..."], '
            '"lessons_learned": ["..."], '
            '"methodological_errors": ["..."], "biases_detected": ["..."], '
            '"would_invest_again": true|false, '
            '"wyckoff_accuracy": "correcta|parcial|incorrecta|no_aplica", '
            '"wyckoff_phase_was_correct": true|false, '
            '"wyckoff_lessons": ["..."], '
            '"hypothesis_evaluation": {"confirmation_bias": "...", '
            '"predictions_analyzed": true, '
            '"was_falsification_applied": true|false, '
            '"hypothesis_lessons": ["..."]}}}'
        )

        return self.llm.generate_structured(
            prompt=prompt,
            system_prompt=(
                "Eres un analista de learning & improvement para una Family Office. "
                "Se brutalmente honesto en la autopsia de la inversion. "
                "El objetivo es aprender, no justificar."
            ),
            temperature=0.3,
        )
