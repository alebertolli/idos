import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.data.journal import JournalRepository
from idos.data.knowledge import KnowledgeRepository
from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
from idos.state.machine import OpportunityStateMachine
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

class ResearchWorker(BaseWorker):
    """Orchestrates the full research pipeline: DDD -> AOIF -> Hypothesis.

    Triggers: manual (CLI) or automatic when an opportunity is promoted from WATCHLIST.
    Transitions: WATCHLIST -> UNDER_DEEP_DD
    """
    name = "research_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.llm = LLMClient(
            provider=config.get("provider", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
            fallback_model=config.get("fallback_model", ""),
            fallback_providers=config.get("fallback_providers", []),
        )
        prompts_path = config.get("prompts_path", "")
        self.registry = PromptRegistry(prompts_path) if prompts_path else PromptRegistry()
        self.state_machine = OpportunityStateMachine()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        opp_id = context.get("opp_id", "")
        base_path = context.get("base_path", "")
        force_reprocess = context.get("force_reprocess", False)
        event_type = context.get("event_type", "manual")
        if not ticker or not opp_id:
            msg = "Both ticker and opp_id are required"
            raise ValueError(msg)

        from pathlib import Path
        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        knowledge = KnowledgeRepository(bp / "idos-knowledge")
        journal = JournalRepository(bp / "idos-journal")

        opp = sqlite.get_opportunity(opp_id)
        if not opp:
            msg = f"Opportunity {opp_id} not found"
            raise ValueError(msg)

        current_status = OpportunityStatus(opp["status"])
        if not force_reprocess:
            if not self.state_machine.can_transition(current_status, OpportunityStatus.UNDER_DEEP_DD):
                return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                        "reason": f"Cannot transition from {current_status} to UNDER_DEEP_DD"}
        else:
            print(f"[FORCE] Reprocessing {ticker} ({opp_id}) from {current_status}, event={event_type}")

        company = knowledge.load_company(ticker) or {}
        financial_data = self._load_financial_data(ticker, sqlite)
        if not company.get("sector"):
            company = self._enrich_company_info(ticker, company, knowledge)

        ddd_result = self._run_prompt("ddd", ticker, {
            "ticker": ticker,
            "name": company.get("name", ticker),
            "sector": company.get("sector", ""),
            "business_model": company.get("business_model", ""),
            "products": company.get("products", ""),
            "geography": company.get("geography", ""),
            "moat_description": company.get("moat_description", ""),
            "revenue": financial_data.get("revenue_ttm", 0),
            "revenue_growth": financial_data.get("revenue_growth_pct", 0),
            "operating_margin": financial_data.get("operating_margin_pct", 0),
            "roic": financial_data.get("roic_pct", 0),
            "excess_return_roic_wacc": financial_data.get("excess_return_roic_wacc", 0),
            "fcf_adjusted": financial_data.get("fcf_adjusted", 0),
            "debt_to_equity": financial_data.get("debt_equity_ratio", 0),
            "debt_maturity_profile": financial_data.get("debt_maturity_profile", "N/A"),
            "interest_coverage_ratio": financial_data.get("interest_coverage_ratio", 0),
            "ceo_tenure": financial_data.get("ceo_tenure", 0),
            "insider_ownership": financial_data.get("insider_ownership", 0),
            "capital_allocation": financial_data.get("capital_allocation", "N/A"),
            "recent_events": financial_data.get("recent_events", company.get("business_model", "")[:500]),
        })

        classification = ddd_result.get("clasificacion_oportunidad", {})
        market_error = ddd_result.get("error_mercado", {})
        thesis = ddd_result.get("tesis_inversion", "")
        score = ddd_result.get("score_general", 50)

        ddd_empty = not any(ddd_result.get(k) for k in ["clasificacion_oportunidad", "tesis_inversion", "dominio_riesgos", "dominio_business_quality"])
        if ddd_empty:
            print(f"[WARN] {ticker}: DDD del LLM vacío — score={score}, clasificacion={classification}, error={ddd_result.get('error','')}")
        elif not ddd_empty and score == 50 and not classification and not thesis:
            print(f"[WARN] {ticker}: DDD con valores por defecto (score=50) — LLM no generó análisis real, error={ddd_result.get('error','')}")

        ddd_report = {
            "ticker": ticker,
            "opp_id": opp_id,
            "version": "3.0",
            "generated_at": datetime.now(AR_TZ).isoformat(),
            "clasificacion_oportunidad": classification,
            "error_mercado": market_error,
            "tesis_inversion": thesis,
            "score_general": score,
            "dominio_riesgos": ddd_result.get("dominio_riesgos", []),
            "dominio_catalizadores": ddd_result.get("dominio_catalizadores", []),
            "dominio_business_quality": ddd_result.get("dominio_business_quality", {}),
            "dominio_financial_health": ddd_result.get("dominio_financial_health", {}),
            "dominio_management": ddd_result.get("dominio_management", {}),
            "dominio_growth": ddd_result.get("dominio_growth", {}),
            "dominio_esg_supply_chain": ddd_result.get("dominio_esg_supply_chain", {}),
            "opinion_valoracion": ddd_result.get("opinion_valoracion", ""),
            "resumen_ejecutivo": ddd_result.get("resumen_ejecutivo", ""),
            "calidad_evidencia": ddd_result.get("calidad_evidencia", {}),
            "prompt_inputs": {
                "ticker": ticker,
                "name": company.get("name", ticker),
                "sector": company.get("sector", ""),
                "business_model": company.get("business_model", ""),
                "products": company.get("products", ""),
                "revenue": financial_data.get("revenue_ttm", 0),
                "revenue_growth": financial_data.get("revenue_growth_pct", 0),
                "operating_margin": financial_data.get("operating_margin_pct", 0),
                "roic": financial_data.get("roic_pct", 0),
                "fcf_adjusted": financial_data.get("fcf_adjusted", 0),
                "debt_to_equity": financial_data.get("debt_equity_ratio", 0),
                "pe_ratio": financial_data.get("pe_ratio", 0),
                "ceo_tenure": financial_data.get("ceo_tenure", 0),
                "insider_ownership": financial_data.get("insider_ownership", 0),
            },
        }
        report_path = bp / "idos-journal" / "companies" / ticker / "case_file" / "opportunities" / opp_id / "ddd_report.yml"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        import yaml as yaml_lib
        with open(report_path, "w", encoding="utf-8") as f:
            yaml_lib.dump(ddd_report, f, default_flow_style=False, allow_unicode=True)

        time.sleep(15)
        hypothesis_result = self._run_prompt("hypothesis", ticker, {
            "ticker": ticker,
            "name": company.get("name", ticker),
            "sector": company.get("sector", ""),
            "thesis_statement": thesis,
            "key_drivers": market_error.get("hipotesis_contraria", ""),
            "recent_events": financial_data.get("recent_events", ""),
        })

        time.sleep(15)
        aoif_result = self._run_prompt("aoif", ticker, {
            "ticker": ticker,
            "name": company.get("name", ticker),
            "company_data": f"Sector: {company.get('sector', '')}\nBusiness: {company.get('business_model', '')}",
            "roic": financial_data.get("roic_pct", 0),
            "operating_margin": financial_data.get("operating_margin_pct", 0),
            "revenue_growth": financial_data.get("revenue_growth_pct", 0),
            "pe_ratio": financial_data.get("pe_ratio", 0),
            "ev_ebitda": financial_data.get("ev_ebitda", 0),
            "fcf_yield": financial_data.get("fcf_yield", 0),
        })

        self._build_knowledge_base(ticker, opp_id, company, financial_data, ddd_result, aoif_result, thesis, knowledge)

        assessment_id = f"ass-{uuid4().hex[:8]}"
        assessment = {
            "id": assessment_id,
            "engine": "ResearchWorker",
            "version": "3.0",
            "status": "COMPLETED",
            "score": score,
            "confidence": "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW",
            "findings": [
                f"Classification: {classification.get('categoria', 'unknown')}",
                f"Market error: {market_error.get('conclusion_error_valoracion', 'N/A')}",
                f"Thesis: {thesis[:200]}",
            ],
            "risks": ddd_result.get("dominio_riesgos", []),
            "recommendation": "REVIEW",
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }
        journal.save_assessment(ticker, opp_id, assessment)

        hypotheses = hypothesis_result.get("hipotesis", [])
        case_file = journal.load_case_file(ticker) or {
            "ticker": ticker,
            "company_name": company.get("name", ticker),
            "created_at": datetime.now(AR_TZ).isoformat(),
            "opportunities": [],
        }
        case_file.setdefault("opportunities", [])
        if opp_id not in case_file["opportunities"]:
            case_file["opportunities"].append(opp_id)
        case_file["last_updated"] = datetime.now(AR_TZ).isoformat()
        journal.save_case_file(ticker, case_file)

        opp["updated_at"] = datetime.now(AR_TZ).isoformat()
        sqlite.save_opportunity(opp)

        if not force_reprocess:
            opp["status"] = OpportunityStatus.UNDER_DEEP_DD.value
            sqlite.save_opportunity(opp)
            sqlite.record_transition(opp_id, current_status.value, "UNDER_DEEP_DD",
                                     cause="research_completed", worker="research_worker")
            event_data = {
                "opp_id": opp_id, "ticker": ticker,
                "score": score, "hypotheses": len(hypotheses),
                "classification": classification.get("categoria"),
            }
            event_data["ddd_empty"] = ddd_empty
            sqlite.log_event("research:completed", event_data)
            journal.log_event("research:completed", event_data, source="research_worker")
        else:
            event_data = {
                "opp_id": opp_id, "ticker": ticker,
                "score": score, "hypotheses": len(hypotheses),
                "classification": classification.get("categoria"),
                "event_type": event_type,
                "original_status": current_status.value,
            }
            event_data["ddd_empty"] = ddd_empty
            sqlite.log_event("research:force_reprocess", event_data)
            journal.log_event("research:force_reprocess", event_data, source="research_worker")

        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "completed",
            "score": score,
            "classification": classification.get("categoria"),
            "market_error_conclusion": market_error.get("conclusion_error_valoracion"),
            "hypotheses_count": len(hypotheses),
            "assessment_id": assessment_id,
            "ddd_empty": ddd_empty,
        }

    def _build_knowledge_base(
        self,
        ticker: str,
        opp_id: str,
        company: dict[str, Any],
        financial_data: dict[str, Any],
        ddd_result: dict[str, Any],
        aoif_result: dict[str, Any],
        thesis: str,
        knowledge: Any,
    ):
        from idos.research.wiki import WikiBuilder
        from idos.knowledge.wiki import AtomicWiki, WikiSection, WikiMetadata
        from idos.knowledge.lifecycle import KnowledgeLifecycle, KnowledgeObject, KnowledgeStatus
        from idos.knowledge.contradiction import ContradictionDetector
        from idos.knowledge.claims import ClaimStore, Claim, EvidenceCategory

        products = company.get("products") or []
        if isinstance(products, str):
            products = [p.strip() for p in products.split(",") if p.strip()]

        wiki_data = {
            "knowledge_base": {
                "static": {
                    "business_model": company.get("business_model", ""),
                    "products": products,
                    "moat_description": company.get("moat_description", ""),
                    "management_history": company.get("management_history", ""),
                },
                "dynamic": {
                    "metrics": {
                        "roic": financial_data.get("roic_pct", 0),
                        "operating_margin": financial_data.get("operating_margin_pct", 0),
                        "revenue_growth": financial_data.get("revenue_growth_pct", 0),
                        "fcf_yield": financial_data.get("fcf_yield", 0),
                        "debt_to_equity": financial_data.get("debt_equity_ratio", 0),
                        "pe_ratio": financial_data.get("pe_ratio", 0),
                        "ev_ebitda": financial_data.get("ev_ebitda", 0),
                    }
                }
            },
            "competitors": company.get("competitors", []),
            "catalysts": ddd_result.get("dominio_catalizadores", []),
            "thesis": thesis,
        }
        wiki_builder = WikiBuilder()
        wiki_sections = wiki_builder.build(ticker, wiki_data)
        wiki_md = wiki_builder.render_markdown(wiki_sections)

        wiki_template = self.registry.get("wiki", category="research")
        if wiki_template:
            existing = knowledge.get_wiki_text(ticker) or wiki_md
            formatted = wiki_template.format(
                ticker=ticker,
                name=company.get("name", ticker),
                ddd_output=str(ddd_result),
                aoif_output=str(aoif_result),
                evidence_chain=f"DDD: {str(ddd_result)[:1500]}\n\nAOIF: {str(aoif_result)[:1500]}",
                existing_wiki=existing,
            )
            wiki_system = self.registry.get_system("wiki", category="research") or ""
            llm_resp = self.llm.generate(
                prompt=formatted,
                system_prompt=wiki_system,
                temperature=0.1,
                max_tokens=4096,
            )
            if llm_resp.success and len(getattr(llm_resp, "content", "")) > 100:
                wiki_md = llm_resp.content

        knowledge.save_wiki(ticker, wiki_md)

        atomic = AtomicWiki(knowledge.base)
        monolith_path = knowledge.knowledge_base_path(ticker) / "static" / "wiki.md"
        if monolith_path.exists():
            atomic.migrate_from_monolith(ticker, monolith_path)

        lifecycle = KnowledgeLifecycle()
        contradiction_detector = ContradictionDetector()
        claim_store = ClaimStore(str(knowledge.base))

        for section in atomic.all_sections(ticker):
            obj = KnowledgeObject(
                object_id=f"wiki-{ticker}-{section.name}",
                object_type="wiki_section",
                ticker=ticker,
                content={"section": section.name, "content": section.content[:500]},
                status=KnowledgeStatus.CREATED,
                confidence=section.metadata.confidence,
            )
            lifecycle.register(obj)
            lifecycle.verify(obj.object_id)
            lifecycle.publish(obj.object_id)

        dd_claims = ddd_result.get("calidad_evidencia", {}).get("hechos_verificados", [])
        for i, fact in enumerate(dd_claims):
            claim = Claim(
                claim_id=f"CLAIM-{ticker}-DDD-{i+1}",
                statement=fact,
                confidence=0.85,
                category=EvidenceCategory.FACT,
                tags=["ddd", ticker],
            )
            claim_store.put(claim)
            contradiction = contradiction_detector.evaluate(
                ticker=ticker,
                claim_statement=fact,
                new_evidence=wiki_md[:2000],
                source=f"DDD {opp_id}",
            )
            if contradiction:
                print(f"[KB] {ticker}: Contradicción: {contradiction.claim_statement} vs {contradiction.conflicting_evidence[:100]}")

        unresolved = contradiction_detector.unresolved()
        if unresolved:
            print(f"[KB] {ticker}: {len(unresolved)} contradicciones sin resolver registradas")

        registered = lifecycle.count()
        if registered:
            print(f"[KB] {ticker}: {registered} secciones wiki registradas en KnowledgeLifecycle")

    def _load_financial_data(self, ticker: str, sqlite: SQLiteStore) -> dict[str, Any]:
        data: dict[str, Any] = {}
        try:
            for row in sqlite.conn.execute(
                "SELECT data_json FROM events_log WHERE event_type LIKE ? AND data_json LIKE ? ORDER BY timestamp DESC LIMIT 1",
                (f"%{ticker}%", f"%{ticker}%"),
            ):
                import json
                try:
                    data = json.loads(row[0])
                except (json.JSONDecodeError, IndexError):
                    pass
        except Exception:
            pass
        if data:
            self._warn_missing_financial(ticker, data, "SQLite")
            return data
        from pathlib import Path
        import json
        for cache_path in [
            Path.cwd() / "cache" / f"{ticker}_financial.json",
            Path.cwd() / "cache" / f"{ticker}.json",
        ]:
            if cache_path.exists():
                try:
                    raw = json.loads(cache_path.read_text(encoding="utf-8"))
                    if raw:
                        if "merged_data" in raw:
                            raw = raw["merged_data"]
                        raw = self._normalize_decimal_pcts(raw)
                        raw = self._enrich_roic(raw)
                        self._warn_missing_financial(ticker, raw, "cache")
                        return raw
                except Exception:
                    pass
        try:
            from idos.workers.data.stockanalysis import StockAnalysisWorker
            sa = StockAnalysisWorker()
            result = sa.run({"ticker": ticker})
            if result:
                cache_dir = Path.cwd() / "cache"
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / f"{ticker}.json").write_text(
                    json.dumps(result, default=str, indent=2), encoding="utf-8"
                )
                result = self._normalize_decimal_pcts(result)
                result = self._enrich_roic(result)
                self._warn_missing_financial(ticker, result, "stockanalysis live")
                return result
        except Exception:
            pass
        self._warn_missing_financial(ticker, {}, "ninguna")
        return data

    @staticmethod
    def _normalize_decimal_pcts(data: dict[str, Any]) -> dict[str, Any]:
        _aliases = {"pe_ratio_ttm": "pe_ratio", "peg_ratio_ttm": "peg_ratio"}
        for src, dst in _aliases.items():
            if src in data and (dst not in data or data[dst] is None):
                data[dst] = data[src]
        _coerce_keys = {"pe_ratio", "pe_historical_avg", "ev_ebitda", "sector_avg_ev_ebitda",
            "debt_equity_ratio", "volatility_90d", "current_ratio", "relative_strength",
            "short_interest_pct", "analyst_consensus", "ceo_tenure", "insider_ownership",
            "target_price", "recurring_revenue_pct", "fcf_yield",
            "roic_pct", "roe_pct", "roa_pct", "revenue_growth_pct",
            "operating_margin_pct", "gross_margin_pct", "net_margin_pct",
            "fcf_yield_pct", "eps_growth", "fcf_growth", "revenue_growth",
            "operating_margin", "roic", "interest_coverage_ratio"}
        for k in _coerce_keys:
            v = data.get(k)
            if isinstance(v, str):
                try:
                    data[k] = float(v)
                except (ValueError, TypeError):
                    data[k] = 0
            elif v is None:
                data[k] = 0
            elif not isinstance(v, (int, float)):
                data[k] = 0
        _pct_keys = {"roic_pct", "roe_pct", "roa_pct", "revenue_growth_pct",
                     "operating_margin_pct", "gross_margin_pct", "net_margin_pct",
                     "fcf_yield_pct", "eps_growth", "fcf_growth"}
        vals = [data[k] for k in _pct_keys if isinstance(data.get(k), (int, float))]
        is_yahoo_format = (sum(abs(v) for v in vals) / len(vals)) < 5 if vals else True
        for k in _pct_keys:
            v = data.get(k)
            if isinstance(v, (int, float)) and is_yahoo_format:
                data[k] = v * 100
        de = data.get("debt_equity_ratio")
        if isinstance(de, (int, float)):
            if de > 1:
                data["debt_equity_ratio"] = de / 100
        return data

    @staticmethod
    def _enrich_roic(data: dict[str, Any]) -> dict[str, Any]:
        roic = data.get("roic_pct")
        if roic is not None and roic != 0:
            return data
        roe = data.get("roe_pct")
        de = data.get("debt_equity_ratio")
        if roe and isinstance(de, (int, float)):
            data["roic_pct"] = round(roe / (1 + de), 2)
        return data

    @staticmethod
    def _enrich_company_info(ticker: str, company: dict[str, Any], knowledge: Any) -> dict[str, Any]:
        if company.get("sector"):
            return company
        try:
            import yfinance as yf
            tk = yf.Ticker(ticker)
            info = tk.info or {}
            resolved = (info.get("symbol") or ticker).upper().strip()
            if resolved != ticker:
                print(f"[WARN] {ticker}: yfinance resolved to {resolved}, skipping enrich")
                return company
            changed = False
            for k, src in [("sector", "sector"), ("industry", "industry"),
                           ("business_model", "longBusinessSummary")]:
                if not company.get(k) and info.get(src):
                    company[k] = info[src]
                    changed = True
            if not company.get("name") and info.get("longName"):
                company["name"] = info["longName"]
                changed = True
            if changed:
                try:
                    knowledge.save_company(ticker, company)
                    print(f"[INFO] {ticker}: company info enriched from YahooFinance")
                except Exception:
                    pass
        except Exception as e:
            print(f"[WARN] {ticker}: no se pudo enriquecer info corporativa: {e}")
        return company

    @staticmethod
    def _warn_missing_financial(ticker: str, data: dict[str, Any], source: str):
        _critical = ["roic_pct", "operating_margin_pct", "revenue_growth_pct", "pe_ratio", "debt_equity_ratio"]
        for key in _critical:
            val = data.get(key)
            if val is None or val == 0:
                print(f"[WARN] {ticker}: {key} es 0 o None (fuente: {source})")
            elif key in ("pe_ratio", "debt_equity_ratio") and val < 0:
                print(f"[WARN] {ticker}: {key}={val} es negativo (fuente: {source})")
        if not data:
            print(f"[WARN] {ticker}: No hay datos financieros — DDD se generará sin fundamentos")

    def _run_prompt(self, prompt_name: str, ticker: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        template = self.registry.get(prompt_name, category="research")
        if not template:
            return {}
        system = self.registry.get_system(prompt_name, category="research") or ""
        formatted = template.format(**kwargs) if isinstance(template, str) else template
        result = self.llm.generate_structured(
            prompt=formatted,
            system_prompt=system,
            temperature=0.1,
        )
        return result
