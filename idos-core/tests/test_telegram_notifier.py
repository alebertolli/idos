from idos.workers.notifications.telegram import TelegramNotifier


def test_telegram_notifier_omits_null_parse_mode(monkeypatch):
    requests = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "result": {"message_id": 123}}

    def fake_post(url, *, json, timeout):
        requests.append((url, json, timeout))
        return Response()

    monkeypatch.setattr("idos.workers.notifications.telegram.requests.post", fake_post)

    result = TelegramNotifier({"bot_token": "token", "chat_id": "chat"}).execute(
        {"message": "Research stopped", "parse_mode": None}
    )

    assert result.output["status"] == "sent"
    assert requests[0][1] == {
        "chat_id": "chat",
        "text": "Research stopped",
        "disable_web_page_preview": True,
    }


def test_telegram_notifier_keeps_explicit_parse_mode(monkeypatch):
    payloads = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "result": {"message_id": 124}}

    def fake_post(url, *, json, timeout):
        payloads.append(json)
        return Response()

    monkeypatch.setattr("idos.workers.notifications.telegram.requests.post", fake_post)

    TelegramNotifier({"bot_token": "token", "chat_id": "chat"}).execute(
        {"message": "*bold*"}
    )

    assert payloads[0]["parse_mode"] == "Markdown"
