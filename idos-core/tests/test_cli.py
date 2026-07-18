"""Smoke tests for CLI commands.

Verifies that all CLI commands register and respond without crashing.
Uses typer.testing.CliRunner for isolated invocation.
"""
import pytest
from typer.testing import CliRunner

from idos.cli.main import app

pytestmark = pytest.mark.smoke

runner = CliRunner()


class TestCLISmoke:
    def test_init(self):
        with runner.isolated_filesystem():
            result = runner.invoke(app, ["init"])
            assert result.exit_code == 0
            assert "initialized" in result.stdout.lower()

    def test_dashboard(self):
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0
        assert "idos" in result.stdout.lower()

    def test_event_log(self):
        result = runner.invoke(app, ["event-log"])
        assert result.exit_code == 0

    def test_opp_list(self):
        result = runner.invoke(app, ["opp-list"])
        assert result.exit_code == 0

    def test_watchlist(self):
        result = runner.invoke(app, ["watchlist"])
        assert result.exit_code == 0

    def test_position_list(self):
        result = runner.invoke(app, ["position-list"])
        assert result.exit_code == 0

    def test_schedule_status(self):
        result = runner.invoke(app, ["schedule-status"])
        assert result.exit_code == 0

    def test_company_add_and_show(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init"])
            result = runner.invoke(app, ["company-add", "TEST", "--name",
                                          "Test Corp", "--sector", "Technology"])
            assert result.exit_code == 0

            result = runner.invoke(app, ["company-show", "TEST"])
            assert result.exit_code == 0
            assert "TEST" in result.stdout

    def test_opportunity_crud(self):
        with runner.isolated_filesystem():
            runner.invoke(app, ["init"])
            opp_id = "OPP-2026-CLI-001"

            runner.invoke(app, ["company-add", "CLI"])
            result = runner.invoke(app, ["opp-create", "CLI"])
            assert result.exit_code == 0

            result = runner.invoke(app, ["opp-list"])
            assert result.exit_code == 0

    def test_opp_show_not_found(self):
        result = runner.invoke(app, ["opp-show", "NONEXISTENT"])
        assert result.exit_code == 0

    def test_opp_approve_no_opps(self):
        result = runner.invoke(app, ["opp-approve", "NONEXISTENT"])
        assert result.exit_code == 0

    def test_entry_evaluate_no_opps(self):
        result = runner.invoke(app, ["entry-evaluate", "NONEXISTENT"])
        assert result.exit_code == 0

    def test_position_exit_no_opps(self):
        result = runner.invoke(app, ["position-exit", "NONEXISTENT"])
        assert result.exit_code == 0

    def test_opp_reject_no_opps(self):
        result = runner.invoke(app, ["opp-reject", "NONEXISTENT"])
        assert result.exit_code == 0
