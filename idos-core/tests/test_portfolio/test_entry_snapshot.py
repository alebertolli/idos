import yaml

from idos.portfolio.entry_snapshot import (
    build_entry_snapshot,
    load_entry_snapshot,
    save_entry_snapshot,
)


def _seed_ddd(journal, ticker: str, opp_id: str):
    opp = journal.opportunity_path(ticker, opp_id)
    opp.mkdir(parents=True, exist_ok=True)
    ddd = {
        "tesis_inversion": "Tesis de prueba: calidad + crecimiento",
        "resumen_ejecutivo": "Resumen de prueba",
        "opinion_valoracion": "infravalorado",
        "score_general": 82,
        "clasificacion_oportunidad": {"categoria": "compounder"},
        "error_mercado": {"conclusion_error_valoracion": "SI"},
        "dominio_catalizadores": [
            {"descripcion": "Catalizador A", "impacto": "alto", "probabilidad_pct": 30},
        ],
        "dominio_riesgos": [
            {"riesgo": "Riesgo X", "impacto": "medio", "probabilidad": "media"},
        ],
        "dominio_business_quality": {"rating": "excepcional", "analisis": "moat"},
        "prompt_inputs": {"roic": 25.0, "pe_ratio": 12.0},
    }
    (opp / "ddd_report.yml").write_text(yaml.dump(ddd, allow_unicode=True), encoding="utf-8")


def _seed_wyckoff(journal, ticker: str, opp_id: str):
    opp = journal.opportunity_path(ticker, opp_id)
    opp.mkdir(parents=True, exist_ok=True)
    entry = {
        "analyzed_at": "2026-01-02T10:00:00-03:00",
        "phase": "accumulation",
        "score": 74,
        "confidence": "alta",
        "entry_point": "lps",
        "price_target": 150.0,
        "indicators": {"ma_50d": 95.0, "current_price": 100.0},
        "triggered_entry": True,
        "llm_response": {"pruebas_compra": {"pruebas_pasan": 8, "total_pruebas": 9}},
    }
    latest = {
        "analyzed_at": "2026-06-01T10:00:00-03:00",
        "phase": "distribution",
        "score": 30,
        "confidence": "baja",
        "triggered_entry": False,
    }
    w_dir = opp / "wyckoff"
    w_dir.mkdir(parents=True, exist_ok=True)
    (w_dir / "20260102_100000.yml").write_text(yaml.dump(entry, allow_unicode=True), encoding="utf-8")
    (w_dir / "20260601_100000.yml").write_text(yaml.dump(latest, allow_unicode=True), encoding="utf-8")


def _seed_proposal(journal, ticker: str, opp_id: str):
    opp = journal.opportunity_path(ticker, opp_id)
    opp.mkdir(parents=True, exist_ok=True)
    proposal = {
        "assessments": {
            "BusinessAssessmentEngine": {
                "engine": "BusinessAssessmentEngine",
                "score": 85,
                "confidence": "HIGH",
                "recommendation": "FAVORABLE",
                "findings": [{"detail": "ROIC alto", "type": "POSITIVE"}],
                "risks": [],
            },
            "ValuationAssessmentEngine": {
                "engine": "ValuationAssessmentEngine",
                "score": 70,
                "confidence": "MEDIUM",
                "recommendation": "ATTRACTIVE",
                "findings": [],
                "risks": [],
            },
        },
        "rules_passed": ["RULE-001", "RULE-003"],
        "rules_failed": [],
        "recommendation": "APPROVE",
    }
    (opp / "decision_proposal.yml").write_text(yaml.dump(proposal, allow_unicode=True), encoding="utf-8")


class TestBuildEntrySnapshot:
    def test_captures_all_domains(self, tmp_journal):
        _seed_ddd(tmp_journal, "AAA", "OPP-TEST-001")
        _seed_wyckoff(tmp_journal, "AAA", "OPP-TEST-001")
        _seed_proposal(tmp_journal, "AAA", "OPP-TEST-001")

        snap = build_entry_snapshot(tmp_journal, "AAA", "OPP-TEST-001", {
            "entry_price": 100.0,
            "quantity": 10,
            "stop_loss": 85.0,
            "target_price": 150.0,
            "intrinsic_value": 150.0,
            "conviction": 74,
            "current_price": 100.0,
            "entry_date": "2026-01-02T10:30:00-03:00",
        })

        assert snap["entry"]["entry_price"] == 100.0
        assert snap["entry"]["conviction_at_entry"] == 74
        assert snap["thesis"]["tesis_inversion"] == "Tesis de prueba: calidad + crecimiento"
        assert snap["thesis"]["opinion_valoracion"] == "infravalorado"
        assert snap["fundamentals"]["roic"] == 25.0

        engines = {a["engine"] for a in snap["assessments"]}
        assert engines == {"BusinessAssessmentEngine", "ValuationAssessmentEngine"}
        biz = next(a for a in snap["assessments"] if a["engine"] == "BusinessAssessmentEngine")
        assert biz["score"] == 85

        # Wyckoff: debe ser el de la entrada (triggered_entry), no el ultimo
        assert snap["technical"]["wyckoff_phase"] == "accumulation"
        assert snap["technical"]["wyckoff_score"] == 74
        assert snap["technical"]["triggered_entry"] is True
        assert snap["technical"]["indicators"]["ma_50d"] == 95.0

        assert len(snap["catalysts"]) == 1
        assert len(snap["risks"]) == 1
        assert "dominio_business_quality" in snap["dominios"]
        assert snap["rules_passed"] == ["RULE-001", "RULE-003"]
        assert snap["recommendation"] == "APPROVE"

    def test_save_load_roundtrip(self, tmp_journal):
        _seed_ddd(tmp_journal, "BBB", "OPP-TEST-002")
        _seed_wyckoff(tmp_journal, "BBB", "OPP-TEST-002")
        _seed_proposal(tmp_journal, "BBB", "OPP-TEST-002")

        snap = build_entry_snapshot(tmp_journal, "BBB", "OPP-TEST-002", {
            "entry_price": 100.0,
            "target_price": 150.0,
            "intrinsic_value": 150.0,
            "conviction": 70,
            "entry_date": "2026-01-02T10:30:00-03:00",
        })
        save_entry_snapshot(tmp_journal, "BBB", "OPP-TEST-002", snap)

        loaded = load_entry_snapshot(tmp_journal, "BBB", "OPP-TEST-002")
        assert loaded is not None
        assert loaded["thesis"]["tesis_inversion"] == "Tesis de prueba: calidad + crecimiento"
        assert loaded["technical"]["wyckoff_score"] == 74