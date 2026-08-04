import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from idos.cli.main import app

pytestmark = pytest.mark.smoke

runner = CliRunner()


class TestCLISmoke:
    def test_init(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            result = runner.invoke(app, ["init"])
            assert result.exit_code == 0
            assert "initialized" in result.stdout.lower()
        finally:
            os.chdir(str(cwd))

    def test_dashboard(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            result = runner.invoke(app, ["dashboard"])
            assert result.exit_code == 0
            assert "idos" in result.stdout.lower()
        finally:
            os.chdir(str(cwd))

    def test_event_log(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            result = runner.invoke(app, ["event-log"])
            assert result.exit_code == 0
        finally:
            os.chdir(str(cwd))

    def test_opp_list(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            result = runner.invoke(app, ["opp-list"])
            assert result.exit_code == 0
        finally:
            os.chdir(str(cwd))

    def test_watchlist(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            result = runner.invoke(app, ["watchlist"])
            assert result.exit_code == 0
        finally:
            os.chdir(str(cwd))

    def test_position_list(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            result = runner.invoke(app, ["position-list"])
            assert result.exit_code == 0
        finally:
            os.chdir(str(cwd))

    def test_schedule_status(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            result = runner.invoke(app, ["schedule-status"])
            assert result.exit_code == 0
        finally:
            os.chdir(str(cwd))

    def test_company_add_and_show(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            runner.invoke(app, ["init"])
            result = runner.invoke(app, ["company-add", "TEST", "--name",
                                          "Test Corp", "--sector", "Technology"])
            assert result.exit_code == 0

            result = runner.invoke(app, ["company-show", "TEST"])
            assert result.exit_code == 0
            assert "TEST" in result.stdout
        finally:
            os.chdir(str(cwd))

    def test_opportunity_crud(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            runner.invoke(app, ["init"])
            opp_id = "OPP-2026-CLI-001"

            runner.invoke(app, ["company-add", "CLI"])
            result = runner.invoke(app, ["opp-create", "CLI"])
            assert result.exit_code == 0

            result = runner.invoke(app, ["opp-list"])
            assert result.exit_code == 0
        finally:
            os.chdir(str(cwd))

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


class TestThesisInvalidate:
    def test_thesis_invalidate_marks_opportunity(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            from idos.data.sqlite import SQLiteStore
            from idos.data.journal import JournalRepository
            sqlite = SQLiteStore(tmp_path / "idos.db")
            journal = JournalRepository(tmp_path / "idos-journal")

            opp = {
                "id": "OPP-2026-THI-001",
                "ticker": "THI",
                "status": "FULL_POSITION",
                "conviction": {"overall": 70},
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
            sqlite.save_opportunity(opp)
            journal.save_opportunity("THI", opp)

            result = runner.invoke(app, ["thesis-invalidate", "THI", "--reason", "falsacion moat"])
            assert result.exit_code == 0

            updated = sqlite.get_opportunity("OPP-2026-THI-001")
            assert updated["thesis_active"] is False
            assert updated["thesis_invalidated_reason"] == "falsacion moat"

            yaml_opp = journal.load_opportunity("THI", "OPP-2026-THI-001")
            assert yaml_opp["thesis_active"] is False
        finally:
            os.chdir(str(cwd))

    def test_thesis_invalidate_no_position(self, tmp_path: Path):
        cwd = Path.cwd()
        try:
            os.chdir(str(tmp_path))
            result = runner.invoke(app, ["thesis-invalidate", "NONEXISTENT"])
            assert result.exit_code == 0
            assert "No active positions" in result.stdout
        finally:
            os.chdir(str(cwd))
