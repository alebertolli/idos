from idos.workers.automation import gha_error_reporter


def test_failure_reporter_creates_issue_without_automatic_llm_analysis(monkeypatch):
    calls = []

    class Reporter:
        def report_failure(self, **kwargs):
            calls.append(("report", kwargs))
            return {"html_url": "https://github.com/example/repo/issues/1", "number": 1}

    monkeypatch.setattr(gha_error_reporter, "GHAErrorReporter", Reporter)
    monkeypatch.setattr(
        gha_error_reporter,
        "_send_email_notification",
        lambda issue, workflow: calls.append(("email", workflow)),
    )
    monkeypatch.setattr(
        gha_error_reporter.sys,
        "argv",
        ["gha_error_reporter.py", "Monthly Universe Pipeline", "123", "rate limited"],
    )

    gha_error_reporter.main()

    assert calls == [
        ("report", {
            "workflow": "Monthly Universe Pipeline",
            "run_id": "123",
            "error_summary": "rate limited",
        }),
        ("email", "Monthly Universe Pipeline"),
    ]
