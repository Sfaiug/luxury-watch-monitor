"""The agent asks Claude through the server's AI hub, by the project's name, never with a key of the environment's."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import BaseModel

from agent import ask
from config import APP_CONFIG
from monitor import WatchMonitor
from scripts import simulate_negotiations as simulating

KEY = "sk-ant-api03-the-environment-s-own"


@pytest.fixture
def hub(monkeypatch):
    """A fake AI hub at the hub's own address: it keeps each request and answers with the next of the answers given."""
    monkeypatch.setattr(APP_CONFIG, "agent_model", "claude-test")
    requests, answers = [], []

    class Hub(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append((self.path, self.headers, self.rfile.read(int(self.headers["Content-Length"])).decode()))
            body = json.dumps({"id": "m", "type": "message", "role": "assistant", "model": "m", "stop_reason": "end_turn",
                               "usage": {"input_tokens": 1, "output_tokens": 1},
                               "content": [{"type": "text", "text": json.dumps(answers.pop(0))}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    deadline = time.monotonic() + 10
    while True:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 8411), Hub)
            break
        except OSError:  # another run of the suite holds the address for a moment
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield requests, answers
    server.shutdown()
    server.server_close()


def through_the_hub(requests):
    """Every request reached the hub's Anthropic path by the project's name, and the environment's key with none."""
    assert requests
    for path, headers, body in requests:
        assert path == "/anthropic/v1/messages" and headers["x-api-key"] == "luxury-watch-monitor"
        assert KEY not in str(headers) and KEY not in body
    return True


class Answer(BaseModel):
    yes: bool


@pytest.mark.parametrize("environment_key", [KEY, None])
async def test_the_monitor_s_agent_asks_through_the_hub_whenever_it_has_a_model(
        hub, tmp_path, monkeypatch, environment_key):
    requests, answers = hub
    if environment_key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", environment_key)
    else:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    monitor = WatchMonitor(log_level="ERROR")
    try:
        await monitor.initialize()
        answers.append({"yes": True})
        assert await ask(monitor.agent.client, "Answer yes.", [{"type": "text", "text": "Yes?"}], Answer) == Answer(yes=True)
    finally:
        await monitor.cleanup()

    assert through_the_hub(requests)


async def test_the_simulated_negotiations_ask_through_the_hub(hub, monkeypatch):
    requests, answers = hub
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    answers += [{"message": "Hallo, ist die Uhr noch zu haben?"},  # the agent's first message
                {"message": "Leider schon gestern verkauft.", "picture": False},  # the seller's answer
                {"price": None, "accepts_offer": False, "turns_down": False, "bank_transfer": None, "delivery": None,
                 "contract": None, "id_card": None, "ended": True, "question": None}]  # the agent's reading of it

    assert await simulating.main(["sold"]) == 0
    assert len(requests) == 3 and through_the_hub(requests)
