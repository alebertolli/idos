from unittest.mock import patch

import pytest

from idos.valuation.target_consensus import fetch_target_consensus

SA = {
    "price_target_avg": 2126.0,
    "price_target_low": 885.98,
    "price_target_high": 2862.0,
}


class TestTargetConsensus:
    def test_average_of_three_sources(self, tmp_path):
        with patch("idos.valuation.target_consensus._source_yfinance", return_value=2116.46), \
             patch("idos.valuation.target_consensus._source_finviz", return_value=2396.0), \
             patch("idos.valuation.target_consensus._source_stockanalysis", return_value=SA):
            res = fetch_target_consensus("ASML", base_path=tmp_path)

        assert res is not None
        assert res.n_fuentes == 3
        assert res.promedio == pytest.approx((2116.46 + 2396.0 + 2126.0) / 3, rel=1e-6)
        assert res.mediana == pytest.approx(2126.0, rel=1e-6)
        assert res.fuentes["yfinance"] == 2116.46
        assert res.fuentes["finviz"] == 2396.0
        assert res.fuentes["stockanalysis"] == 2126.0
        assert res.target_low == 885.98
        assert res.target_high == 2862.0

    def test_single_source_allowed(self, tmp_path):
        with patch("idos.valuation.target_consensus._source_yfinance", return_value=2116.46), \
             patch("idos.valuation.target_consensus._source_finviz", return_value=None), \
             patch("idos.valuation.target_consensus._source_stockanalysis", return_value=None):
            res = fetch_target_consensus("ASML", base_path=tmp_path)

        assert res is not None
        assert res.n_fuentes == 1
        assert res.promedio == pytest.approx(2116.46)

    def test_failed_source_is_dropped(self, tmp_path):
        def boom(*_a, **_k):
            raise RuntimeError("network error")

        with patch("idos.valuation.target_consensus._source_yfinance", return_value=2116.46), \
             patch("idos.valuation.target_consensus._source_finviz", side_effect=boom), \
             patch("idos.valuation.target_consensus._source_stockanalysis", return_value={"price_target_avg": 2126.0}):
            res = fetch_target_consensus("ASML", base_path=tmp_path)

        assert res is not None
        assert res.n_fuentes == 2
        assert res.promedio == pytest.approx((2116.46 + 2126.0) / 2)

    def test_non_numeric_source_is_ignored(self, tmp_path):
        with patch("idos.valuation.target_consensus._source_yfinance", return_value=2116.46), \
             patch("idos.valuation.target_consensus._source_finviz", return_value="n/a"), \
             patch("idos.valuation.target_consensus._source_stockanalysis", return_value=None):
            res = fetch_target_consensus("ASML", base_path=tmp_path)

        assert res is not None
        assert res.n_fuentes == 1
        assert res.promedio == pytest.approx(2116.46)

    def test_no_sources_returns_none(self, tmp_path):
        with patch("idos.valuation.target_consensus._source_yfinance", return_value=None), \
             patch("idos.valuation.target_consensus._source_finviz", return_value=None), \
             patch("idos.valuation.target_consensus._source_stockanalysis", return_value=None):
            res = fetch_target_consensus("ASML", base_path=tmp_path)

        assert res is None

    def test_cache_is_used(self, tmp_path):
        with patch("idos.valuation.target_consensus._source_yfinance", return_value=2116.46) as m_yf, \
             patch("idos.valuation.target_consensus._source_finviz", return_value=2396.0) as m_fz, \
             patch("idos.valuation.target_consensus._source_stockanalysis", return_value=SA) as m_sa:
            r1 = fetch_target_consensus("ASML", base_path=tmp_path)
            r2 = fetch_target_consensus("ASML", base_path=tmp_path)

        assert m_yf.call_count == 1
        assert m_fz.call_count == 1
        assert m_sa.call_count == 1
        assert r2 is not None
        assert r2.promedio == r1.promedio
