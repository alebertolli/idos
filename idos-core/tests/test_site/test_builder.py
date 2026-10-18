from pathlib import Path

import yaml

from idos.site.builder import SiteBuilder, write_site


def _builder() -> SiteBuilder:
    return SiteBuilder.__new__(SiteBuilder)


def _opp(opp_id: str, ticker: str, intrinsic: float | None) -> dict:
    return {
        "opp_id": opp_id,
        "ticker": ticker,
        "status": "FULL_POSITION",
        "intrinsic_value": intrinsic,
    }


def _position(ticker: str, opp_id: str, current_price: float | None) -> dict:
    return {"ticker": ticker, "opp_id": opp_id, "current_price": current_price}


def _alerts(opps: list[dict], positions: list[dict]) -> list[dict]:
    return _builder()._build_dashboard(opps, positions, [], [], [])["alerts"]


def _sections(opps: list[dict], watchlist: list[dict], universe_stats: dict = None) -> list[dict]:
    return _builder()._build_dashboard(opps, [], [], watchlist, [], universe_stats)["sections"]


def test_no_alert_when_price_below_intrinsic():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", 120.0)],
        [_position("AAA", "OPP-1", 100.0)],
    )
    assert alerts == []


def test_alert_when_price_above_intrinsic_by_opp_id():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", 100.0)],
        [_position("AAA", "OPP-1", 130.0)],
    )
    assert len(alerts) == 1
    a = alerts[0]
    assert a["severity"] == "warn"
    assert a["ticker"] == "AAA"
    assert "30.0% sobre el valor intrínseco (100.00)" in a["message"]


def test_falls_back_to_ticker_when_opp_id_missing():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", 50.0)],
        [_position("AAA", "OPP-NONE", 60.0)],
    )
    assert len(alerts) == 1
    assert alerts[0]["ticker"] == "AAA"


def test_no_alert_without_intrinsic_value():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", None)],
        [_position("AAA", "OPP-1", 130.0)],
    )
    assert alerts == []


def test_no_alert_without_price():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", 100.0)],
        [_position("AAA", "OPP-1", None)],
    )
    assert alerts == []


def test_discovery_shows_operable_count_from_universe_stats():
    universe_stats = {
        "operable_count": 267,
        "scout_passed": 57,
        "scout_rejected": 210,
        "finviz_count": 1874,
        "opportunities_created": 0,
    }
    sections = _sections([], [], universe_stats)
    discovery = next(s for s in sections if s["key"] == "discovery")
    assert discovery["count"] == 267


def test_research_shows_under_research_count_from_opps():
    universe_stats = {
        "operable_count": 267,
        "scout_passed": 57,
    }
    opps = [{"ticker": f"T{i}", "status": "UNDER_RESEARCH"} for i in range(57)]
    sections = _sections(opps, [], universe_stats)
    research = next(s for s in sections if s["key"] == "research")
    assert research["count"] == 57


def test_research_does_not_count_watchlist():
    universe_stats = {
        "operable_count": 267,
        "scout_passed": 57,
    }
    opps = [{"ticker": f"T{i}", "status": "WATCHLIST"} for i in range(57)]
    sections = _sections(opps, [], universe_stats)
    research = next(s for s in sections if s["key"] == "research")
    assert research["count"] == 0


def test_discovery_falls_back_to_zero_without_universe_stats():
    sections = _sections([], [], None)
    discovery = next(s for s in sections if s["key"] == "discovery")
    assert discovery["count"] == 0


def test_research_falls_back_to_funnel_count_without_universe_stats():
    opp = _opp("OPP-1", "AAA", 100.0)
    opp["status"] = "UNDER_RESEARCH"
    sections = _sections([opp], [], None)
    research = next(s for s in sections if s["key"] == "research")
    assert research["count"] == 1


def test_universe_stats_included_in_dashboard_return():
    universe_stats = {"operable_count": 267, "scout_passed": 57}
    result = _builder()._build_dashboard([], [], [], [], [], universe_stats)
    assert result["universe_stats"] == universe_stats


def test_universe_stats_empty_without_stats():
    result = _builder()._build_dashboard([], [], [], [], [], None)
    assert result["universe_stats"] == {}


def test_dashboard_exposes_ide_without_portfolio_metrics():
    opps = [{
        "ticker": "AAA", "status": "UNDER_RESEARCH",
        "scores": {"RiskAssessmentEngine": 70, "BusinessAssessmentEngine": 80},
        "conviction_overall": 75,
    }]
    result = _builder()._build_dashboard(opps, [], [], [], [])
    assert result["ide"]["engine_averages"]["RiskAssessmentEngine"] == 70
    assert result["ide"]["conviction_average"] == 75
    assert "portfolio" not in result
    assert all(section["key"] != "portfolio" for section in result["sections"])


def test_public_build_omits_paper_positions(tmp_path: Path, monkeypatch):
    position_marker = "FAMILY_POSITION_SECRET_9876"
    private_fit_marker = "FAMILY_PORTFOLIO_FIT_SECRET_4321"
    private = tmp_path / "idos-journal" / "paper" / "positions"
    private.mkdir(parents=True)
    (private / f"{position_marker}.yml").write_text(
        f"ticker: {position_marker}\nquantity: 100\nentry_price: 12\n", encoding="utf-8"
    )
    held = tmp_path / "idos-journal" / "companies" / "PRIVATE" / "case_file" / "opportunities" / "OPP-PRIVATE"
    held.mkdir(parents=True)
    (held / "opportunity.yml").write_text("id: OPP-PRIVATE\nticker: PRIVATE\nstatus: FULL_POSITION\n", encoding="utf-8")
    research = tmp_path / "idos-journal" / "companies" / "AAA" / "case_file" / "opportunities" / "OPP-AAA"
    research.mkdir(parents=True)
    (research / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-AAA",
        "ticker": "AAA",
        "status": "UNDER_RESEARCH",
        "strategy_id": "COMPOUNDER",
        "conviction": {
            "overall": 95,
            "confidence": "HIGH",
            "trend": "IMPROVING",
            "scores": {"PortfolioAssessmentEngine": 97},
        },
    }), encoding="utf-8")
    (research / "decision_proposal.yml").write_text(yaml.safe_dump({
        "recommendation": "BLOCKED",
        "rules_failed": ["RULE-010"],
        "assessments": {
            "PortfolioAssessmentEngine": {
                "score": 97,
                "confidence": "HIGH",
                "recommendation": "EXCELLENT_FIT",
                "findings": [{"type": "POSITIVE", "detail": private_fit_marker}],
                "risks": [],
            },
        },
    }), encoding="utf-8")
    (research / "ddd_report.yml").write_text(yaml.safe_dump({
        "research_status": "COMPLETED",
        "score_general": 78,
        "opinion_valoracion": "infravalorado",
        "error_mercado": {
            "conclusion_error_valoracion": "SI",
            "consenso_actual": "Market consensus summary",
            "hipotesis_contraria": "Contrarian view",
            "razonamiento": "Reasoning text",
            "catalizador_cambio": {"descripcion": "2025 production milestone"},
        },
        "dominio_catalizadores": [{
            "descripcion": "Production target for 2025",
            "horizonte": "medium",
            "impacto": "high",
            "probabilidad_pct": 75,
        }],
        "calidad_evidencia": {"hechos_reportados": [{
            "statement": "Revenue grew 12%",
            "period": "FY2025",
            "unit": "%",
            "sources": [{"title": "Annual report", "url": "https://example.com/report", "source_date": "2026-03-01"}],
        }]},
    }), encoding="utf-8")
    monkeypatch.setattr(SiteBuilder, "_market_price", lambda _self, _ticker: {"price": None, "date": None})
    site = SiteBuilder(tmp_path).build()
    public_opp = next(o for o in site.opportunities if o["ticker"] == "AAA")
    assert public_opp["ddd"]["evidence_gate_blocked"] is True
    assert site.positions == []
    assert site.ledger == []
    assert site.portfolio == {}
    assert "SECRET" not in str(site)
    assert "PRIVATE" not in str(site)
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "learning.html").write_text("old post mortem", encoding="utf-8")
    output = write_site(tmp_path, tmp_path / "site")
    published_artifacts = "\n".join(
        path.read_text(encoding="utf-8")
        for path in output.rglob("*")
        if path.is_file()
    )
    assert position_marker not in str(site)
    assert private_fit_marker not in str(site)
    assert position_marker not in published_artifacts
    assert private_fit_marker not in published_artifacts
    assert "PRIVATE" not in published_artifacts
    assert not (output / "learning.html").exists()
    script = (output / "assets" / "app.js").read_text(encoding="utf-8")
    assert "['portfolio','Portfolio']" not in script
    assert "Decisión pendiente de revisión humana" in script
    assert "no se calcula en Pages" in script
    assert "Annual report" in published_artifacts
    assert "https://example.com/report" in published_artifacts
    assert "Revenue grew 12%" in published_artifacts
    assert "evidence_gate_blocked" in published_artifacts
    assert "Evidencia pendiente: no usar este análisis ni sus catalizadores para decidir." in published_artifacts
    assert "Score DDD y opinión de valoración omitidos" in published_artifacts
    assert "Análisis DDD · hipótesis pendiente de validación" in published_artifacts
    assert "Catalizadores · pendientes de validación" in published_artifacts
    assert "Hipótesis de mercado · no validada" in published_artifacts
    assert "Consenso supuesto · no validado" in published_artifacts
    assert "catalizador_cambio?.descripcion && !d.evidence_gate_blocked" in published_artifacts
    assert "Dominios DDD · análisis no validado" in published_artifacts


def test_public_opportunity_explains_unknown_risk_and_omits_private_portfolio_fit(tmp_path: Path):
    opp_dir = tmp_path / "OPP-RISK-UNKNOWN"
    opp_dir.mkdir()
    (opp_dir / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-RISK-UNKNOWN",
        "status": "UNDER_RESEARCH",
        "strategy_id": "COMPOUNDER",
        "conviction": {
            "overall": 62,
            "confidence": "HIGH",
            "trend": "IMPROVING",
            "scores": {"RiskAssessmentEngine": 0, "PortfolioAssessmentEngine": 91},
        },
    }), encoding="utf-8")
    (opp_dir / "decision_proposal.yml").write_text(yaml.safe_dump({
        "assessments": {
            "RiskAssessmentEngine": {
                "score": 0,
                "confidence": "LOW",
                "recommendation": "INSUFFICIENT_DATA",
                "findings": [],
                "risks": [{"type": "DATA_QUALITY", "metric": "current_ratio", "detail": "current_ratio is UNKNOWN"}],
            },
            "PortfolioAssessmentEngine": {
                "score": 91,
                "confidence": "HIGH",
                "recommendation": "EXCELLENT_FIT",
                "findings": [{"type": "POSITIVE", "detail": "PRIVATE-HOLDING-DETAIL"}],
                "risks": [],
            },
        },
    }), encoding="utf-8")

    builder = _builder()
    builder._market_price = lambda ticker: {"price": None, "date": None}
    result = builder._load_opportunity("AAA", opp_dir)

    assert result["scores"]["RiskAssessmentEngine"] == 0
    assert "PortfolioAssessmentEngine" not in result["scores"]
    assert result["conviction_overall"] is None
    assert result["confidence"] is None
    assert result["trend"] is None
    assert result["risk_assessment"]["recommendation"] == "INSUFFICIENT_DATA"
    assert result["risk_assessment"]["risks"][0]["metric"] == "current_ratio"
    assert "PRIVATE-HOLDING-DETAIL" not in str(result)


def test_dashboard_hides_stale_price_and_intrinsic_when_valuation_inputs_are_missing(tmp_path: Path):
    opp_dir = tmp_path / "OPP-STALE-VALUATION"
    opp_dir.mkdir()
    (opp_dir / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-STALE-VALUATION",
        "status": "UNDER_RESEARCH",
        "current_price": 71.95,
        "intrinsic_value": 91.79,
    }), encoding="utf-8")
    (opp_dir / "decision_proposal.yml").write_text(yaml.safe_dump({
        "assessments": {
            "ValuationAssessmentEngine": {
                "score": 50,
                "risks": [{
                    "type": "DATA_QUALITY",
                    "detail": "Current price and analyst target are required for valuation",
                }],
                "findings": [],
            }
        }
    }), encoding="utf-8")

    builder = _builder()
    builder._market_price = lambda _ticker: {"price": 72.10, "date": "2026-10-16"}
    result = builder._load_opportunity("VIST", opp_dir)

    assert result["current_price"] is None
    assert result["intrinsic_value"] is None
    assert result["upside_pct"] is None
    assert result["price_date"] is None



def test_failed_ddd_is_visible_as_high_dashboard_alert(tmp_path: Path):
    opp_dir = tmp_path / "OPP-RACE-FAILED"
    opp_dir.mkdir()
    (opp_dir / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-RACE-FAILED",
        "status": "UNDER_RESEARCH",
        "ticker": "RACE",
    }), encoding="utf-8")
    (opp_dir / "ddd_report.yml").write_text(yaml.safe_dump({
        "research_status": "FAILED",
        "research_error": "El análisis DDD devolvió una respuesta vacía o incompleta.",
    }), encoding="utf-8")

    builder = _builder()
    builder._market_price = lambda ticker: {"price": None, "date": None}
    opportunity = builder._load_opportunity("RACE", opp_dir)
    dashboard = builder._build_dashboard([opportunity], [], [], [], [])

    assert opportunity["ddd"]["research_status"] == "FAILED"
    assert any(
        alert["severity"] == "high"
        and alert["ticker"] == "RACE"
        and "assessment detenido" in alert["message"]
        for alert in dashboard["alerts"]
    )


def test_systematic_opportunity_uses_signal_without_fake_conviction_or_valuation(tmp_path: Path):
    opp_dir = tmp_path / "OPP-MOM-XLE"
    opp_dir.mkdir()
    (opp_dir / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-MOM-XLE",
        "status": "UNDER_RESEARCH",
        "strategy_id": "MOMENTUM_ETF",
        "thesis_type": "SYSTEMATIC",
        "current_price": 0,
        "intrinsic_value": 0,
        "conviction": {"overall": 0},
        "signal": {"momentum": 2.53, "as_of_date": "2026-10-01"},
    }), encoding="utf-8")
    (opp_dir / "decision_proposal.yml").write_text(yaml.safe_dump({
        "decision": "WAIT",
        "status": "PENDING_HUMAN_REVIEW",
        "reason": "Risk budget requires private portfolio review",
    }), encoding="utf-8")
    (opp_dir / "ddd_report.yml").write_text(yaml.safe_dump({"score_general": 94}), encoding="utf-8")

    builder = _builder()
    builder._market_price = lambda ticker: {"price": None, "date": None}
    result = builder._load_opportunity("XLE", opp_dir)

    assert result["conviction_overall"] is None
    assert result["current_price"] is None
    assert result["intrinsic_value"] is None
    assert result["signal"]["momentum"] == 2.53
    assert result["proposal"]["decision"] == "WAIT"
    assert result["proposal"]["reason"] == "Risk budget requires private portfolio review"
    assert result["ddd"]["score_general"] == 94
    assert result["ddd"]["evidence_gate_blocked"] is False
