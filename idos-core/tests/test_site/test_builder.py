from pathlib import Path

import pytest

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


def test_dashboard_alert_identity_is_stable_deduplicated_and_resolved_from_current_state():
    stale_opportunity = {
        **_opp("OPP-1", "AAA", 100.0),
        "is_stale": True,
        "stale_days": 31,
    }
    first = _alerts([stale_opportunity, stale_opportunity.copy()], [])

    assert len(first) == 1
    alert_id = first[0]["id"]
    assert alert_id == "research_stale:AAA:OPP-1"
    assert first[0]["type"] == "research_stale"
    assert first[0]["status"] == "ACTIVE"
    assert "31d" in first[0]["message"]

    updated_opportunity = {**stale_opportunity, "stale_days": 40}
    updated = _alerts([updated_opportunity], [])
    assert updated[0]["id"] == alert_id
    assert "40d" in updated[0]["message"]

    resolved_opportunity = {**updated_opportunity, "is_stale": False}
    assert _alerts([resolved_opportunity], []) == []


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


def test_pipeline_results_use_generic_candidate_metrics_and_keep_legacy_read_compatibility(tmp_path: Path):
    import json

    builder = _builder()
    builder.base = tmp_path
    (tmp_path / "cache").mkdir()
    results = tmp_path / "cache" / "pipeline_results.json"
    results.write_text(json.dumps({"output": {
        "candidate_count": 2,
        "candidate_source": "idos-config/universe/operable.yml",
        "finviz_count": 999,
        "operable_count": 2,
    }}), encoding="utf-8")

    stats = builder._load_universe_stats()

    assert stats["candidate_count"] == 2
    assert stats["candidate_source"] == "idos-config/universe/operable.yml"

    results.write_text(json.dumps({"output": {"finviz_count": 5}}), encoding="utf-8")
    assert builder._load_universe_stats()["candidate_count"] == 5


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


def test_public_build_omits_paper_positions(tmp_path: Path):
    private = tmp_path / "idos-journal" / "paper" / "positions"
    private.mkdir(parents=True)
    (private / "SECRET.yml").write_text("ticker: SECRET\nquantity: 100\nentry_price: 12\n", encoding="utf-8")
    held = tmp_path / "idos-journal" / "companies" / "PRIVATE" / "case_file" / "opportunities" / "OPP-PRIVATE"
    held.mkdir(parents=True)
    (held / "opportunity.yml").write_text("id: OPP-PRIVATE\nticker: PRIVATE\nstatus: FULL_POSITION\n", encoding="utf-8")
    site = SiteBuilder(tmp_path).build()
    assert site.positions == []
    assert site.ledger == []
    assert site.portfolio == {}
    assert "SECRET" not in str(site)
    assert "PRIVATE" not in str(site)
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "learning.html").write_text("old post mortem", encoding="utf-8")
    output = write_site(tmp_path, tmp_path / "site")
    assert "SECRET" not in (output / "data.json").read_text(encoding="utf-8")
    assert "PRIVATE" not in (output / "data.json").read_text(encoding="utf-8")
    assert not (output / "learning.html").exists()
    script = (output / "assets" / "app.js").read_text(encoding="utf-8")
    assert "['portfolio','Portfolio']" not in script
    assert "Decisión pendiente de revisión humana" in script


def _write_ddd_case(tmp_path: Path, review: dict | None) -> None:
    import yaml

    opp = tmp_path / "idos-journal" / "companies" / "VIST" / "case_file" / "opportunities" / "OPP-1"
    opp.mkdir(parents=True)
    (opp / "opportunity.yml").write_text(
        "id: OPP-1\nticker: VIST\nstatus: UNDER_RESEARCH\n",
        encoding="utf-8",
    )
    report = {
        "resumen_ejecutivo": "Tesis antigua sin validar",
        "tesis_inversion": "Afirmación que requiere revisión",
        "score_general": 81,
        "dominio_business_quality": {"rating": "fuerte", "analisis": "Afirmación sin fuente"},
        "evidence_review": review or {},
    }
    (opp / "ddd_report.yml").write_text(yaml.safe_dump(report, allow_unicode=True), encoding="utf-8")
    (opp / "hypotheses.yml").write_text(yaml.safe_dump({"hypotheses": [{
        "id": "H1-OPP-1",
        "statement": "El crecimiento de ingresos superará 8%.",
        "rationale": "La renovación de producto sostiene la demanda.",
        "horizon": "medio",
        "review_trigger": "Abandonar la hipótesis si el crecimiento cae debajo de 3%.",
        "predictions": [{
            "metric": "revenue_growth",
            "prediction": "Ingresos crecerán 8% para FY2027.",
            "expected": 8,
            "unit": "%",
            "deadline": "2027-09-30",
        }],
        "falsification_conditions": ["El crecimiento queda debajo de 3% en FY2027."],
    }]}, allow_unicode=True), encoding="utf-8")
    (opp / "decision_proposal.yml").write_text(yaml.safe_dump({
        "financial_data_quality": {
            "status": "partial",
            "core_metric_coverage": "5/5",
            "source": "provider-x",
            "as_of_date": None,
            "as_of_date_source": None,
            "missing_provenance": ["as_of_date"],
            "conflicting_core_metrics": ["revenue_growth_pct"],
            "unreconciled_core_metrics": ["revenue_growth_pct"],
        },
        "rules_passed": ["RULE-008"],
        "rules_details": {"RULE-008": "B/R 6.8:1 ✅ (upside 10.9% / downside 1.6%)"},
    }, allow_unicode=True), encoding="utf-8")


def test_public_site_exposes_unreviewed_ddd_and_hypotheses_as_provisional(tmp_path: Path):
    _write_ddd_case(tmp_path, review=None)

    data = SiteBuilder(tmp_path).build()
    opp = next(o for o in data.opportunities if o["ticker"] == "VIST")

    assert opp["ddd"]["evidence_review"]["status"] == "pending_manager_review"
    assert opp["ddd"]["resumen_ejecutivo"] == "Tesis antigua sin validar"
    assert opp["ddd"]["tesis_inversion"] == "Afirmación que requiere revisión"
    assert data.positions == []
    assert data.portfolio == {}
    assert opp["ddd"]["score_general"] == 81
    assert opp["ddd"]["dominios"][0]["analisis"] == "Afirmación sin fuente"
    assert opp["ddd"]["hipotesis"][0]["predictions"][0]["expected"] == 8
    assert opp["ddd"]["hipotesis"][0]["predictions"][0]["prediction"] == "Ingresos crecerán 8% para FY2027."
    assert opp["ddd"]["financial_data_quality"]["status"] == "partial"
    assert opp["proposal"]["rules_details"]["RULE-008"].startswith("B/R 6.8:1")

    output = write_site(tmp_path, tmp_path / "site-output")
    payload = (output / "data.json").read_text(encoding="utf-8")
    app = (output / "assets" / "app.js").read_text(encoding="utf-8")
    assert "Tesis antigua sin validar" in payload
    assert "Afirmación que requiere revisión" in payload
    assert "El crecimiento de ingresos superará 8%." in payload
    assert "Ingresos crecerán 8% para FY2027." in payload
    assert "Informe pendiente de validación del gestor" in app
    assert "Tesis de inversión (provisional)" in app
    assert "Calidad de datos financieros" in app
    assert "Fecha de corte" in app
    assert "dq.as_of_date_source" in app
    assert "Conflictos entre fuentes" in app
    assert "Periodos sin reconciliar" in app
    assert "Cuándo abandonarla" in app
    assert "Asimetría del modelo (RULE-008" in app
    assert "Métrica provisional del motor" in app
    assert "Detalles de reglas" in app


def test_public_site_displays_unassessed_portfolio_recommendation(tmp_path: Path):
    import json
    import yaml

    _write_ddd_case(tmp_path, review=None)
    proposal_path = (
        tmp_path / "idos-journal" / "companies" / "VIST" / "case_file"
        / "opportunities" / "OPP-1" / "decision_proposal.yml"
    )
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    proposal["assessments"] = {
        "PortfolioAssessmentEngine": {
            "score": 50,
            "recommendation": "NOT_ASSESSED",
            "findings": [{
                "type": "PENDING",
                "detail": "Private family portfolio source is not connected; portfolio fit is not assessed",
            }],
        }
    }
    proposal_path.write_text(yaml.safe_dump(proposal, allow_unicode=True), encoding="utf-8")

    output = write_site(tmp_path, tmp_path / "site-output")
    payload = json.loads((output / "data.json").read_text(encoding="utf-8"))
    app = (output / "assets" / "app.js").read_text(encoding="utf-8")
    opportunity = next(item for item in payload["opportunities"] if item["ticker"] == "VIST")

    assert opportunity["assessment_recommendations"]["PortfolioAssessmentEngine"] == "NOT_ASSESSED"
    assert opportunity["findings"]["PortfolioAssessmentEngine"] == [
        "Private family portfolio source is not connected; portfolio fit is not assessed"
    ]
    assert "<th>Assessment</th>" in app
    assert "assessment_recommendations" in app


def test_public_site_shows_next_thesis_review_and_alerts_when_overdue(tmp_path: Path):
    from datetime import datetime, timedelta
    import json

    import yaml

    from idos.timezone import AR_TZ

    _write_ddd_case(tmp_path, review=None)
    opp_path = tmp_path / "idos-journal/companies/VIST/case_file/opportunities/OPP-1/opportunity.yml"
    opp = yaml.safe_load(opp_path.read_text(encoding="utf-8"))
    now = datetime.now(AR_TZ)
    opp["last_research_at"] = (now - timedelta(days=31)).isoformat()
    opp["strategy_id"] = "COMPOUNDER"
    opp_path.write_text(yaml.safe_dump(opp, allow_unicode=True), encoding="utf-8")

    data = SiteBuilder(tmp_path).build()
    opportunity = next(o for o in data.opportunities if o["ticker"] == "VIST")
    alerts = data.dashboard["alerts"]
    output = write_site(tmp_path, tmp_path / "site-output")
    payload = json.loads((output / "data.json").read_text(encoding="utf-8"))
    app = (output / "assets" / "app.js").read_text(encoding="utf-8")

    assert opportunity["thesis_review_interval_days"] == 30
    assert opportunity["thesis_review_status"] == "due"
    expected_next = (datetime.fromisoformat(opp["last_research_at"]) + timedelta(days=30)).isoformat()
    assert opportunity["next_thesis_review_at"] == expected_next
    assert any("Revisión de tesis vencida" in alert["message"] for alert in alerts)
    due_alert = next(alert for alert in alerts if alert["type"] == "thesis_review_due")
    assert due_alert["id"] == "thesis_review_due:VIST:OPP-1"
    assert due_alert["status"] == "ACTIVE"
    assert any(alert["id"] == due_alert["id"] for alert in payload["dashboard"]["alerts"])
    assert "próxima revisión de tesis" in app

    opp["last_research_at"] = now.isoformat()
    opp_path.write_text(yaml.safe_dump(opp, allow_unicode=True), encoding="utf-8")
    refreshed = SiteBuilder(tmp_path).build()
    assert not any(
        alert["type"] in {"research_stale", "thesis_review_due"}
        for alert in refreshed.dashboard["alerts"]
    )


@pytest.mark.parametrize(
    ("opportunity_fields", "expected_state", "expected_label"),
    [
        ({"thesis_active": True, "research_age_days": 10}, "CURRENT", "Vigente"),
        ({"thesis_active": True, "research_age_days": 31}, "REVIEW_DUE", "Revisión vencida"),
        ({"thesis_active": False, "research_age_days": 10}, "INVALIDATED", "Invalidada"),
        (None, "UNLINKED", "Sin vínculo"),
        ({
            "thesis_active": True,
            "research_age_days": 10,
            "research_profile": "systematic",
        }, "NOT_APPLICABLE", "No aplica"),
    ],
)
def test_buylist_discloses_thesis_state_and_blocks_noncurrent_recommendations(
    tmp_path: Path,
    opportunity_fields: dict | None,
    expected_state: str,
    expected_label: str,
):
    from datetime import datetime, timedelta

    import yaml

    from idos.timezone import AR_TZ

    if opportunity_fields is not None:
        opp_dir = (
            tmp_path / "idos-journal" / "companies" / "VIST" / "case_file"
            / "opportunities" / "OPP-1"
        )
        opp_dir.mkdir(parents=True)
        now = datetime.now(AR_TZ)
        opportunity = {
            "id": "OPP-1",
            "ticker": "VIST",
            "status": "APPROVED",
            "strategy_id": opportunity_fields.get("strategy_id", "COMPOUNDER"),
            "research_profile": opportunity_fields.get("research_profile", "strategic"),
            "created_at": (now - timedelta(days=40)).isoformat(),
            "last_research_at": (
                now - timedelta(days=opportunity_fields["research_age_days"])
            ).isoformat(),
            "thesis_active": opportunity_fields["thesis_active"],
        }
        if not opportunity_fields["thesis_active"]:
            opportunity["thesis_invalidated_reason"] = "Falsación registrada"
        (opp_dir / "opportunity.yml").write_text(
            yaml.safe_dump(opportunity, allow_unicode=True), encoding="utf-8"
        )
    buylist_path = tmp_path / "idos-journal" / "portfolio" / "buylist.yml"
    buylist_path.parent.mkdir(parents=True, exist_ok=True)
    buylist_path.write_text(yaml.safe_dump({"entries": [{
        "ticker": "VIST",
        "opp_id": "OPP-1",
        "target_price": 100,
        "buy_zone_top": 80,
    }]}), encoding="utf-8")

    site = SiteBuilder(tmp_path).build()
    entry = site.buylist[0]
    output = write_site(tmp_path, tmp_path / "site-output")
    app = (output / "assets" / "app.js").read_text(encoding="utf-8")

    assert entry["recommendation_state"] == expected_state
    if opportunity_fields is not None:
        assert entry["thesis_active"] is opportunity_fields["thesis_active"]
    else:
        assert entry["recommendation_state"] == "UNLINKED"
    assert expected_label in app
    assert "thesisState!=='CURRENT'" in app
    if expected_state == "REVIEW_DUE":
        assert entry["thesis_review_status"] == "due"
    if expected_state == "INVALIDATED":
        assert entry["thesis_invalidated_reason"] == "Falsación registrada"


def test_buylist_includes_strategy_and_signal_from_linked_opportunity(tmp_path: Path):
    import yaml

    opportunity_dir = (
        tmp_path / "idos-journal" / "companies" / "VIST" / "case_file"
        / "opportunities" / "OPP-MOM-VIST"
    )
    opportunity_dir.mkdir(parents=True)
    (opportunity_dir / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-MOM-VIST",
        "ticker": "VIST",
        "status": "APPROVED",
        "strategy_id": "MOMENTUM_ETF",
        "entry_policy": "SIGNAL_REBALANCE",
        "signal": {"signal_type": "momentum", "score": 1.2, "as_of_date": "2026-10-15"},
    }), encoding="utf-8")
    buylist_path = tmp_path / "idos-journal" / "portfolio" / "buylist.yml"
    buylist_path.parent.mkdir(parents=True)
    buylist_path.write_text(yaml.safe_dump({"entries": [{
        "ticker": "VIST", "opp_id": "OPP-MOM-VIST",
    }]}), encoding="utf-8")

    site = SiteBuilder(tmp_path).build()
    entry = site.buylist[0]
    output = write_site(tmp_path, tmp_path / "site-output")
    import json

    app = (output / "assets" / "app.js").read_text(encoding="utf-8")
    data = json.loads((output / "data.json").read_text(encoding="utf-8"))

    assert entry["strategy_id"] == "MOMENTUM_ETF"
    assert entry["entry_policy"] == "SIGNAL_REBALANCE"
    assert entry["strategy_signal"]["score"] == 1.2
    assert data["buylist"][0]["strategy_id"] == "MOMENTUM_ETF"
    assert data["buylist"][0]["entry_policy"] == "SIGNAL_REBALANCE"
    assert data["buylist"][0]["strategy_signal"]["score"] == 1.2
    assert "label:'Estrategia'" in app
    assert "strategy_signal.score" in app

def test_buylist_ignores_generic_signal_for_valuation_strategy(tmp_path: Path):
    import yaml

    opportunity_dir = (
        tmp_path / "idos-journal" / "companies" / "VIST" / "case_file"
        / "opportunities" / "OPP-C-VIST"
    )
    opportunity_dir.mkdir(parents=True)
    (opportunity_dir / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-C-VIST",
        "ticker": "VIST",
        "status": "APPROVED",
        "strategy_id": "COMPOUNDER",
        "entry_policy": "VALUATION_ZONE",
        "signal": {"technical_score": 71},
    }), encoding="utf-8")
    buylist_path = tmp_path / "idos-journal" / "portfolio" / "buylist.yml"
    buylist_path.parent.mkdir(parents=True)
    buylist_path.write_text(yaml.safe_dump({"entries": [{
        "ticker": "VIST", "opp_id": "OPP-C-VIST",
    }]}), encoding="utf-8")

    entry = SiteBuilder(tmp_path).build().buylist[0]

    assert entry["strategy_id"] == "COMPOUNDER"
    assert entry["entry_policy"] == "VALUATION_ZONE"
    assert entry["strategy_signal"] is None

def test_public_site_exposes_ddd_only_after_attributable_manager_approval(tmp_path: Path):
    _write_ddd_case(tmp_path, {
        "status": "manager_approved",
        "reviewed_by": "investment-manager",
        "reviewed_at": "2026-10-18T12:00:00-03:00",
    })

    data = SiteBuilder(tmp_path).build()
    opp = next(o for o in data.opportunities if o["ticker"] == "VIST")

    assert opp["ddd"]["evidence_review"]["status"] == "manager_approved"
    assert opp["ddd"]["resumen_ejecutivo"] == "Tesis antigua sin validar"
    assert opp["ddd"]["dominios"][0]["analisis"] == "Afirmación sin fuente"
    output = write_site(tmp_path, tmp_path / "site-output")
    payload = (output / "data.json").read_text(encoding="utf-8")
    assert '"reviewed_by"' not in payload
    assert "investment-manager" not in payload
    assert "2026-10-18T12:00:00-03:00" in payload


def test_public_site_does_not_accept_approval_without_reviewer_and_date(tmp_path: Path):
    _write_ddd_case(tmp_path, {"status": "manager_approved", "reviewed_by": "", "reviewed_at": "not-a-date"})

    data = SiteBuilder(tmp_path).build()
    opp = next(o for o in data.opportunities if o["ticker"] == "VIST")

    assert opp["ddd"]["evidence_review"]["status"] == "pending_manager_review"
    assert opp["ddd"]["resumen_ejecutivo"] == "Tesis antigua sin validar"


def test_public_site_shows_scenarios_with_sources_and_manager_review_hash(tmp_path: Path):
    import yaml
    from idos.decision.scenarios import scenario_fingerprint

    _write_ddd_case(tmp_path, review=None)
    opp_dir = tmp_path / "idos-journal/companies/VIST/case_file/opportunities/OPP-1"
    report_path = opp_dir / "ddd_report.yml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    report["scenario_analysis"] = {
        "schema_version": "bear_base_bull_v1",
        "as_of_date": "2026-10-19",
        "horizon_date": "2027-10-19",
        "currency": "USD",
        "scenarios": [
            {"id": "BEAR", "probability_pct": 25, "target_price": 80, "sources": [{"name": "Filing", "url": "https://example.com/bear", "as_of_date": "2026-10-18"}]},
            {"id": "BASE", "probability_pct": 50, "target_price": 110, "sources": [{"name": "Filing", "url": "https://example.com/base", "as_of_date": "2026-10-18"}]},
            {"id": "BULL", "probability_pct": 25, "target_price": 150, "sources": [{"name": "Filing", "url": "https://example.com/bull", "as_of_date": "2026-10-18"}]},
        ],
    }
    report["scenario_validation"] = {"status": "valid_pending_manager_review", "errors": []}
    report_path.write_text(yaml.safe_dump(report, allow_unicode=True), encoding="utf-8")

    data = SiteBuilder(tmp_path).build()
    opp = next(o for o in data.opportunities if o["ticker"] == "VIST")
    assert opp["ddd"]["scenario_analysis"]["scenarios"][0]["id"] == "BEAR"
    assert opp["ddd"]["scenario_review"]["status"] == "pending_manager_review"
    assert opp["ddd"]["scenario_review"]["scenario_hash"] == scenario_fingerprint(report["scenario_analysis"])

    output = write_site(tmp_path, tmp_path / "site-output")
    app = (output / "assets" / "app.js").read_text(encoding="utf-8")
    payload = (output / "data.json").read_text(encoding="utf-8")
    assert "Escenarios Bear / Base / Bull" in app
    assert "aprobación del gestor" in app
    assert "abre cada fuente y verifica que exista" in app
    assert "confirmación explícita de fuentes verificadas" in app
    assert "https://example.com/bear" in payload


def test_public_site_does_not_present_automated_board_resolution_as_human_approval(tmp_path: Path):
    import yaml

    _write_ddd_case(tmp_path, review=None)
    opp_dir = tmp_path / "idos-journal/companies/VIST/case_file/opportunities/OPP-1"
    (opp_dir / "board_resolution.yml").write_text(yaml.safe_dump({
        "approved": True,
        "decision_type": "BUY",
        "decision_id": "DEC-LEGACY",
        "author": "board",
        "resolved_at": "2026-10-18T12:00:00-03:00",
    }), encoding="utf-8")

    opp = next(o for o in SiteBuilder(tmp_path).build().opportunities if o["ticker"] == "VIST")
    assert opp["decision"]["approved"] is False
    assert opp["decision"]["decision_id"] is None


def test_public_site_keeps_deterministic_systematic_report_separate_from_fundamental_review(tmp_path: Path):
    import yaml

    _write_ddd_case(tmp_path, review=None)
    opportunity_path = tmp_path / "idos-journal" / "companies" / "VIST" / "case_file" / "opportunities" / "OPP-1" / "opportunity.yml"
    opportunity = yaml.safe_load(opportunity_path.read_text(encoding="utf-8"))
    opportunity["strategy_id"] = "MOMENTUM_ETF"
    opportunity["research_profile"] = "systematic"
    opportunity["entry_policy"] = "SIGNAL_REBALANCE"
    opportunity["signal"] = {"score": 71}
    opportunity_path.write_text(yaml.safe_dump(opportunity, allow_unicode=True), encoding="utf-8")
    report_path = tmp_path / "idos-journal" / "companies" / "VIST" / "case_file" / "opportunities" / "OPP-1" / "ddd_report.yml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    report["resumen_ejecutivo"] = "Momentum mensual normalizado con score 71"
    report["tesis_inversion"] = ""
    report["dominio_business_quality"] = {"rating": "no_aplica", "analisis": "No es criterio de la señal"}
    report["strategy_context"] = {"strategy_id": "MOMENTUM_ETF", "signal": {"score": 71}, "report_method_version": "systematic_signal_v2"}
    report_path.write_text(yaml.safe_dump(report, allow_unicode=True), encoding="utf-8")

    data = SiteBuilder(tmp_path).build()
    opp = next(o for o in data.opportunities if o["ticker"] == "VIST")

    assert opp["ddd"]["evidence_review"]["status"] == "systematic_report"
    assert opp["ddd"]["resumen_ejecutivo"] == "Momentum mensual normalizado con score 71"
    assert opp["ddd"]["score_general"] == 81
    assert opp["ddd"]["tesis_inversion"] == ""
    assert opp["intrinsic_value"] is None
    assert opp["upside_pct"] is None
    assert opp["valuation_status"] == "NOT_APPLICABLE"
    assert opp["conviction_overall"] is None
    # Older generated reports can contain synthetic volatility/probabilities.
    # Preserve their journals but require regeneration before public display.
    del report["strategy_context"]["report_method_version"]
    report_path.write_text(yaml.safe_dump(report), encoding="utf-8")
    legacy = next(o for o in SiteBuilder(tmp_path).build().opportunities if o["ticker"] == "VIST")
    assert legacy["ddd"]["evidence_review"]["status"] == "systematic_report_refresh_required"
    assert legacy["ddd"]["resumen_ejecutivo"] is None


def test_public_site_does_not_treat_forged_fundamental_context_as_systematic(tmp_path: Path):
    import yaml

    _write_ddd_case(tmp_path, review=None)
    opportunity_path = tmp_path / "idos-journal" / "companies" / "VIST" / "case_file" / "opportunities" / "OPP-1" / "opportunity.yml"
    opportunity = yaml.safe_load(opportunity_path.read_text(encoding="utf-8"))
    opportunity.update({
        "strategy_id": "COMPOUNDER",
        "research_profile": "strategic",
        "entry_policy": "VALUATION_ZONE",
        "signal": {},
    })
    opportunity_path.write_text(yaml.safe_dump(opportunity, allow_unicode=True), encoding="utf-8")
    report_path = tmp_path / "idos-journal" / "companies" / "VIST" / "case_file" / "opportunities" / "OPP-1" / "ddd_report.yml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    report["strategy_context"] = {"strategy_id": "COMPOUNDER", "signal": {"score": 99}}
    report_path.write_text(yaml.safe_dump(report, allow_unicode=True), encoding="utf-8")

    data = SiteBuilder(tmp_path).build()
    opp = next(o for o in data.opportunities if o["ticker"] == "VIST")

    assert opp["ddd"]["evidence_review"]["status"] == "pending_manager_review"
    assert opp["ddd"]["resumen_ejecutivo"] == "Tesis antigua sin validar"
    assert opp["ddd"]["tesis_inversion"] == "Afirmación que requiere revisión"
    assert opp["ddd"]["score_general"] == 81


def test_strategy_signal_reports_expose_run_scope_and_latest_generated_report(tmp_path: Path):
    import json
    import yaml

    report_dir = tmp_path / "idos-journal" / "strategies" / "MOMENTUM_ETF"
    report_dir.mkdir(parents=True)
    older = {
        "as_of_date": "2026-10-18",
        "generated_at": "2026-10-18T10:00:00-03:00",
        "run_scope": "full",
        "action": "REVIEW_ALLOCATION",
        "candidate_count": 7,
        "eligible_universe_count": 7,
        "coverage_complete": True,
        "eligible": [{"ticker": "XLF"}],
    }
    newer = {
        "as_of_date": "2026-10-18",
        "generated_at": "2026-10-18T11:00:00-03:00",
        "run_scope": "bounded",
        "action": "CASH_FALLBACK",
        "candidate_count": 2,
        "eligible_universe_count": 7,
        "coverage_complete": False,
        "eligible": [],
        "requested_tickers": ["QQQ", "GLD"],
    }
    (report_dir / "23-later-name.yml").write_text(yaml.safe_dump(older), encoding="utf-8")
    (report_dir / "01-earlier-name.yml").write_text(yaml.safe_dump(newer), encoding="utf-8")

    out = write_site(tmp_path, tmp_path / "site")
    payload = json.loads((out / "data.json").read_text(encoding="utf-8"))
    signal = payload["dashboard"]["ide"]["strategy_signals"]["MOMENTUM_ETF"]
    app_js = (out / "assets" / "app.js").read_text(encoding="utf-8")

    assert signal["run_scope"] == "bounded"
    assert signal["candidate_count"] == 2
    assert signal["eligible_universe_count"] == 7
    assert "Prueba parcial" in app_js
    assert "no interpretar como señal global" in app_js


def test_market_data_provenance_ignores_malformed_source_and_refresh_lists(tmp_path: Path):
    import json

    builder = _builder()
    builder.cache = tmp_path / "cache"
    builder.cache.mkdir()
    (builder.cache / "AAA.json").write_text(
        json.dumps({"data_provenance": {"sources_used": None, "field_sources": {}}}),
        encoding="utf-8",
    )
    (builder.cache / "last_refresh.json").write_text(
        json.dumps({"tickers": None, "refreshed_at": "2026-10-18T12:00:00Z"}),
        encoding="utf-8",
    )

    provenance = builder._load_data_provenance("AAA", "2026-10-18")

    assert provenance["sources_used"] == []
    assert provenance["source_count"] == 0
    assert provenance["refreshed_at"] is None


def test_market_data_provenance_ignores_non_object_refresh_cache(tmp_path: Path):
    import json

    builder = _builder()
    builder.cache = tmp_path / "cache"
    builder.cache.mkdir()
    (builder.cache / "AAA.json").write_text(
        json.dumps({"data_provenance": {"sources_used": ["Yahoo"], "source_count": 1}}),
        encoding="utf-8",
    )
    (builder.cache / "last_refresh.json").write_text("[]", encoding="utf-8")

    provenance = builder._load_data_provenance("AAA")

    assert provenance["sources_used"] == ["Yahoo"]
    assert provenance["refreshed_at"] is None


def test_public_site_exposes_market_provenance_and_single_source_alert(tmp_path: Path):
    import json

    _write_ddd_case(tmp_path, review=None)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "VIST.json").write_text(
        json.dumps({
            "price_history": [12.5],
            "price_history_dates": ["2026-10-18"],
            "data_provenance": {
                "source_count": 1,
                "sources_used": ["yfinance"],
                "field_sources": {"price_history": ["yfinance"]},
                "conflicts": [],
            },
        }),
        encoding="utf-8",
    )
    (cache / "last_refresh.json").write_text(
        json.dumps({"tickers": ["VIST"], "refreshed_at": "2026-10-18T12:00:00Z"}),
        encoding="utf-8",
    )

    site = SiteBuilder(tmp_path).build()
    opportunity = next(item for item in site.opportunities if item["ticker"] == "VIST")
    alerts = site.dashboard["alerts"]
    output = write_site(tmp_path, tmp_path / "site-output")
    payload = json.loads((output / "data.json").read_text(encoding="utf-8"))
    app = (output / "assets" / "app.js").read_text(encoding="utf-8")

    assert opportunity["market_data"]["sources_used"] == ["yfinance"]
    assert opportunity["market_data"]["field_sources"] == {"price_history": ["yfinance"]}
    assert opportunity["market_data"]["refreshed_at"] == "2026-10-18T12:00:00Z"
    assert any(a["ticker"] == "VIST" and "una sola fuente" in a["message"] for a in alerts)
    assert payload["opportunities"][0]["market_data"]["source_count"] == 1
    assert "Procedencia por campo" in app
    assert "Dato / fuentes" in app
