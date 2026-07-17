import pytest
from idos.ux.reports import ReportGenerator, ReportType


class TestReportGenerator:
    def test_dd_report(self):
        rg = ReportGenerator()
        report = rg.generate_dd_report("AAPL", {
            "executive_summary": "Strong buy",
            "business_analysis": "Great business",
            "financial_analysis": "Solid finances",
            "management_assessment": "Good mgmt",
            "risk_factors": "Low risk",
            "valuation": "Undervalued",
            "recommendation": "Buy",
        })
        assert report.report_type == ReportType.DUE_DILIGENCE
        assert report.ticker == "AAPL"
        assert len(report.sections) == 7

    def test_weekly_report(self):
        rg = ReportGenerator()
        report = rg.generate_weekly_report(
            [{"ticker": "AAPL", "weight": 3}],
            {"week": "W27", "performance": {"pnl": 5.2}, "risk": {}, "actions": []},
        )
        assert report.report_type == ReportType.WEEKLY
        assert "W27" in report.title

    def test_markdown_rendering(self):
        rg = ReportGenerator()
        report = rg.generate_dd_report("AAPL", {
            "executive_summary": "Bullish thesis", "business_analysis": "",
            "financial_analysis": "", "management_assessment": "",
            "risk_factors": "", "valuation": "", "recommendation": "",
        })
        md = rg.render_markdown(report)
        assert "# Due Diligence: AAPL" in md
        assert "Bullish thesis" in md
        assert "Executive Summary" in md
