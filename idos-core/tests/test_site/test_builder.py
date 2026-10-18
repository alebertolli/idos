from pathlib import Path

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


def test_public_site_withholds_unreviewed_ddd_claims(tmp_path: Path):
    _write_ddd_case(tmp_path, review=None)

    data = SiteBuilder(tmp_path).build()
    opp = next(o for o in data.opportunities if o["ticker"] == "VIST")

    assert opp["ddd"]["evidence_review"]["status"] == "pending_manager_review"
    assert opp["ddd"]["resumen_ejecutivo"] is None
    assert opp["ddd"]["tesis_inversion"] is None
    assert opp["ddd"]["score_general"] is None
    assert opp["ddd"]["dominios"] == []

    output = write_site(tmp_path, tmp_path / "site-output")
    payload = (output / "data.json").read_text(encoding="utf-8")
    app = (output / "assets" / "app.js").read_text(encoding="utf-8")
    assert "Tesis antigua sin validar" not in payload
    assert "Afirmación que requiere revisión" not in payload
    assert "Informe pendiente de validación del gestor" in app


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
    assert opp["ddd"]["resumen_ejecutivo"] is None


def test_public_site_keeps_deterministic_systematic_report_separate_from_fundamental_review(tmp_path: Path):
    import yaml

    _write_ddd_case(tmp_path, review=None)
    opportunity_path = tmp_path / "idos-journal" / "companies" / "VIST" / "case_file" / "opportunities" / "OPP-1" / "opportunity.yml"
    opportunity = yaml.safe_load(opportunity_path.read_text(encoding="utf-8"))
    opportunity["strategy_id"] = "MOMENTUM_ETF"
    opportunity_path.write_text(yaml.safe_dump(opportunity, allow_unicode=True), encoding="utf-8")
    report_path = tmp_path / "idos-journal" / "companies" / "VIST" / "case_file" / "opportunities" / "OPP-1" / "ddd_report.yml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    report["resumen_ejecutivo"] = "Momentum mensual normalizado con score 71"
    report["tesis_inversion"] = ""
    report["dominio_business_quality"] = {"rating": "no_aplica", "analisis": "No es criterio de la señal"}
    report["strategy_context"] = {"strategy_id": "MOMENTUM_ETF", "signal": {"score": 71}}
    report_path.write_text(yaml.safe_dump(report, allow_unicode=True), encoding="utf-8")

    data = SiteBuilder(tmp_path).build()
    opp = next(o for o in data.opportunities if o["ticker"] == "VIST")

    assert opp["ddd"]["evidence_review"]["status"] == "systematic_report"
    assert opp["ddd"]["resumen_ejecutivo"] == "Momentum mensual normalizado con score 71"
