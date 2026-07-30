from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from idos.data.journal import JournalRepository
from idos.data.knowledge import KnowledgeRepository
from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
from idos.models.knowledge import Company
from idos.models.journal import Opportunity

TEST_TICKER = "TEST"
TEST_OPP_ID = "OPP-2026-TEST-001"


# ──────────────────────────────────────────────
# Mock LLM responses
# ──────────────────────────────────────────────

MOCK_DDD_RESPONSE: dict[str, Any] = {
    "clasificacion_oportunidad": {
        "categoria": "compounder_castigado",
        "justificacion": "Negocio de alta calidad temporalmente fuera de favor",
        "categorias_descartadas": "No es value trap ni turnaround",
    },
    "error_mercado": {
        "consenso_actual": "El mercado descuenta desaceleración permanente",
        "hipotesis_contraria": "La desaceleración es cíclica, no estructural",
        "catalizador_cambio": {
            "descripcion": "Próximo earnings beat",
            "probabilidad_pct": 65,
            "impacto": "alto",
            "horizonte": "corto",
        },
        "conclusion_error_valoracion": "SI",
        "razonamiento": "Múltiplo en percentil 10 histórico sin deterioro estructural",
    },
    "resumen_ejecutivo": "Oportunidad asimétrica en compounder castigado",
    "dominio_business_quality": {"rating": "excepcional", "analisis": "Moat amplio, ROIC > 20%"},
    "dominio_financial_health": {"rating": "fuerte", "analisis": "D/E < 0.3, FCF sólido"},
    "dominio_management": {"rating": "excepcional", "analisis": "CEO con 15 años de track record"},
    "dominio_growth": {"rating": "fuerte", "analisis": "Crecimiento orgánico 10-15%"},
    "dominio_esg_supply_chain": {"rating": "bajo_riesgo", "analisis": "Sin concentración"},
    "dominio_riesgos": [
        {"riesgo": "Desaceleración macro", "probabilidad": "media", "impacto": "medio"},
    ],
    "dominio_catalizadores": [
        {"descripcion": "Earnings beat", "probabilidad_pct": 65, "impacto": "alto",
         "horizonte": "corto", "nivel_confianza": "alto"},
    ],
    "opinion_valoracion": "infravalorado",
    "tesis_inversion": "Compounder castigado con catalizador de earnings beat",
    "calidad_evidencia": {
        "hechos_verificados": ["ROIC > 20% por 5 años"],
        "inferencias_llm": ["El mercado sobreestima riesgo cíclico"],
        "preguntas_abiertas": ["Impacto exacto de tipo de cambio"],
    },
    "score_general": 82,
}

MOCK_HYPOTHESIS_RESPONSE: dict[str, Any] = {
    "hipotesis": [
        {
            "id": "H1",
            "enunciado": "El crecimiento de revenue se acelerará en próximos 2 trimestres",
            "prediccion": "Revenue growth > 10% en Q3 2026",
            "criterios_falsacion": "Revenue growth < 5%",
            "plazo": "corto",
            "categoria": "operacional",
            "prioridad": "critical",
            "magnitud": {"metrica": "revenue_growth", "valor_esperado": 12.0, "unidad": "%"},
            "depende_de": [],
        },
    ],
}

MOCK_AOIF_RESPONSE: dict[str, Any] = {
    "modelo_negocio": "Plataforma tecnológica con efectos de red",
    "status": "completado",
    "tesis": "Compounder castigado",
    "recomendacion": "comprar",
    "rango_conviccion": [70, 85],
    "puntos_monitoreo_clave": ["Revenue growth", "Margen operativo"],
}

MOCK_DECISION_BOARD_APPROVE: dict[str, Any] = {
    "all_rules_pass": True,
    "recommendation": "APPROVE",
    "rationale": "Cumple todas las reglas de entrada",
    "rules_detail": [
        {"rule_id": "RULE-001", "passes": True, "reason": "Business score 82 >= 70"},
        {"rule_id": "RULE-002", "passes": True, "reason": "Valuation atractiva"},
        {"rule_id": "RULE-003", "passes": True, "reason": "Rerating probable"},
        {"rule_id": "RULE-004", "passes": True, "reason": "Riesgo controlado"},
        {"rule_id": "RULE-008", "passes": True, "reason": "Asimetría > 3:1"},
    ],
}

MOCK_DECISION_BOARD_REJECT: dict[str, Any] = {
    "all_rules_pass": False,
    "recommendation": "REJECT",
    "rationale": "No cumple umbral mínimo de calidad",
    "rules_detail": [
        {"rule_id": "RULE-001", "passes": False, "reason": "Business score 45 < 70"},
    ],
}

MOCK_POST_MORTEM: dict[str, Any] = {
    "exit_analysis": "La tesis se invalidó por deterioro del moat",
    "thesis_was_correct": False,
    "what_went_wrong": ["Subestimamos la competencia"],
    "what_went_right": ["Buena ejecución de entrada"],
    "lessons_learned": ["Exigir más evidencia de moat durability"],
    "methodological_errors": ["Sesgo de confirmación en DDD"],
    "biases_detected": ["Anchoring en estimaciones de crecimiento"],
    "would_invest_again": False,
    "wyckoff_accuracy": "incorrecta",
    "wyckoff_phase_was_correct": False,
    "wyckoff_lessons": ["La fase de acumulacion no se confirmo en retrospectiva"],
}

MOCK_ENTRY_LLM_RESPONSE: dict[str, Any] = {
    "fase_wyckoff": "acumulacion",
    "eventos_wyckoff_detectados": [
        {"evento": "PS", "descripcion": "Preliminary support detectado", "confianza": "alta"},
        {"evento": "SC", "descripcion": "Selling climax con volumen extremo", "confianza": "alta"},
        {"evento": "Spring", "descripcion": "Penetración de soporte con volumen bajo", "confianza": "media"},
    ],
    "pruebas_compra": {
        "prueba_1_objetivo_caida": "Pasa",
        "prueba_2_actividad_alcista": "Pasa",
        "prueba_3_parada_critica": "Pasa",
        "prueba_4_fortaleza_relativa": "N/A",
        "prueba_5_linea_suministro": "Pasa",
        "prueba_6_soportes_crecientes": "Pasa",
        "prueba_7_maximos_crecientes": "Pasa",
        "prueba_8_base_construida": "Pasa",
        "prueba_9_relacion_3_1": "Pasa",
        "pruebas_pasan": 8,
        "total_pruebas": 9,
    },
    "punto_entrada": "lps",
    "senal_entrada": "COMPRAR",
    "justificacion": "Acumulación confirmada con LPS en soporte",
    "confianza": "alta",
    "datos_suficientes": True,
    "limitaciones": "Sin punto y figura para conteo exacto",
}


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def tmp_sqlite(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "idos.db")


@pytest.fixture
def tmp_knowledge(tmp_path: Path) -> KnowledgeRepository:
    return KnowledgeRepository(tmp_path / "idos-knowledge")


@pytest.fixture
def tmp_journal(tmp_path: Path) -> JournalRepository:
    return JournalRepository(tmp_path / "idos-journal")


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Mock LLMClient que responde con datos predecibles."""
    client = MagicMock()

    def generate_structured(prompt="", system_prompt="", temperature=0.1, max_tokens=4096):
        if "clasificacion_oportunidad" in prompt or "FASE 0" in prompt:
            return dict(MOCK_DDD_RESPONSE)
        if "hipotesis" in prompt.lower() and "genera" in prompt.lower():
            return dict(MOCK_HYPOTHESIS_RESPONSE)
        if "AOIF" in prompt or "8-step" in prompt:
            return dict(MOCK_AOIF_RESPONSE)
        if "Reglas de entrada" in prompt or "RULE" in prompt:
            return dict(MOCK_DECISION_BOARD_APPROVE)
        if "Post-Mortem" in prompt or "post_mortem" in prompt:
            return dict(MOCK_POST_MORTEM)
        if "Wyckoff" in prompt or "fase_wyckoff" in prompt:
            return dict(MOCK_ENTRY_LLM_RESPONSE)
        return {"score_general": 75, "tesis_inversion": "default thesis"}

    client.generate_structured.side_effect = generate_structured
    return client


@pytest.fixture
def mock_llm_reject_client() -> MagicMock:
    """Mock LLMClient que simula un DDD que no pasa las reglas."""
    client = MagicMock()

    def generate_structured(prompt="", system_prompt="", temperature=0.1, max_tokens=4096):
        resp = dict(MOCK_DDD_RESPONSE)
        resp["score_general"] = 45
        if "Reglas de entrada" in prompt or "RULE" in prompt:
            return dict(MOCK_DECISION_BOARD_REJECT)
        return resp

    client.generate_structured.side_effect = generate_structured
    return client


@pytest.fixture
def seeded_opportunity(tmp_sqlite: SQLiteStore, tmp_journal: JournalRepository) -> tuple[str, str]:
    """Crea compañía + oportunidad en estado WATCHLIST."""
    ticker = TEST_TICKER
    opp_id = TEST_OPP_ID

    opp = {
        "id": opp_id,
        "ticker": ticker,
        "status": OpportunityStatus.WATCHLIST.value,
        "conviction": {"overall": 70},
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    tmp_sqlite.save_opportunity(opp)
    tmp_journal.save_opportunity(ticker, opp)

    return ticker, opp_id


@pytest.fixture
def seeded_opportunity_under_dd(
    tmp_sqlite: SQLiteStore, tmp_journal: JournalRepository
) -> tuple[str, str]:
    """Oportunidad en UNDER_DEEP_DD para tests de DecisionBoardWorker."""
    ticker = TEST_TICKER
    opp_id = TEST_OPP_ID

    opp = {
        "id": opp_id,
        "ticker": ticker,
        "status": OpportunityStatus.UNDER_DEEP_DD.value,
        "conviction": {"overall": 70},
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    tmp_sqlite.save_opportunity(opp)
    tmp_journal.save_opportunity(ticker, opp)

    assessment = {
        "id": "ass-test-001",
        "engine": "ResearchWorker",
        "version": "3.0",
        "status": "COMPLETED",
        "score": 82,
        "confidence": "HIGH",
        "findings": ["Classification: compounder_castigado", "Market error: SI"],
        "risks": [],
        "recommendation": "REVIEW",
        "generated_at": "2026-01-01T00:00:00",
    }
    tmp_journal.save_assessment(ticker, opp_id, assessment)

    return ticker, opp_id


@pytest.fixture
def seeded_opportunity_approved(
    tmp_sqlite: SQLiteStore, tmp_journal: JournalRepository
) -> tuple[str, str]:
    """Oportunidad en APPROVED para tests de EntryMonitorWorker."""
    ticker = TEST_TICKER
    opp_id = TEST_OPP_ID

    opp = {
        "id": opp_id,
        "ticker": ticker,
        "status": OpportunityStatus.APPROVED.value,
        "conviction": {"overall": 82},
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "intrinsic_value": 130,
        "current_price": 95,
    }
    tmp_sqlite.save_opportunity(opp)
    tmp_journal.save_opportunity(ticker, opp)
    return ticker, opp_id


@pytest.fixture
def seeded_opportunity_exited(
    tmp_sqlite: SQLiteStore, tmp_journal: JournalRepository
) -> tuple[str, str]:
    """Oportunidad en EXITED para tests de PostMortemWorker."""
    ticker = TEST_TICKER
    opp_id = TEST_OPP_ID

    opp = {
        "id": opp_id,
        "ticker": ticker,
        "status": OpportunityStatus.EXITED.value,
        "conviction": {"overall": 82},
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    tmp_sqlite.save_opportunity(opp)

    dec = {
        "id": "dec-test-001",
        "type": "BUY",
        "ticker": ticker,
        "opp_id": opp_id,
        "rationale": "Entry test",
        "price": 95.0,
        "generated_at": "2026-01-01T00:00:00",
    }
    tmp_journal.save_decision(ticker, opp_id, dec)

    ass = {
        "id": "ass-test-001",
        "engine": "ResearchWorker",
        "score": 82,
        "confidence": "HIGH",
        "findings": ["Thesis: compounder castigado"],
        "status": "COMPLETED",
        "generated_at": "2026-01-01T00:00:00",
    }
    tmp_journal.save_assessment(ticker, opp_id, ass)

    pos = {
        "ticker": ticker,
        "status": "ACTIVE",
        "avg_entry_price": 95.0,
        "weight_pct": 2.5,
        "shares": 100,
    }
    tmp_journal.save_position(ticker, pos)

    return ticker, opp_id


@pytest.fixture
def base_path(tmp_path: Path) -> str:
    """Crea estructura idos-config temporal con entry_rules.yml."""
    rules_dir = tmp_path / "idos-config" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rules_file = rules_dir / "entry_rules.yml"
    rules_file.write_text(
        """
rules:
  - id: RULE-001
    description: "Minimum business quality score for entry"
    priority: 100
    condition: "assessments.business.score >= 70"
    action: "PASS"
    active: true
  - id: RULE-002
    description: "Minimum valuation score for entry"
    priority: 90
    condition: "assessments.valuation.score >= 60"
    action: "PASS"
    active: true
  - id: RULE-008
    description: "Minimum asymmetry ratio 3:1"
    priority: 100
    condition: "opportunity.asymmetry_ratio >= 3.0"
    action: "PASS"
    active: true
""", encoding="utf-8")
    return str(tmp_path)


MOCK_PRICE_DATA = [
    {"close": 100.0 + i * 0.5 + (5 if i > 40 else 0), "volume": 1_000_000 + i * 10_000}
    for i in range(252)
]
