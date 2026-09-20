"""Tests for WebSocket event bridge."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nira.core.events import EventBus, EventType

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def app(event_bus):
    from nira.server.ws_bridge import create_ws_router

    app = FastAPI()
    router = create_ws_router(event_bus)
    app.include_router(router)
    return app


class TestWSBridge:
    def test_websocket_receives_events(self, app, event_bus):
        client = TestClient(app)
        with client.websocket_connect("/v1/agents/events") as ws:
            event_bus.publish(
                EventType.AGENT_TICK_START,
                {
                    "agent_id": "test-123",
                    "agent_name": "test",
                },
            )
            time.sleep(0.05)  # Let call_soon_threadsafe deliver to queue
            data = ws.receive_json()
            assert data["type"] == "agent_tick_start"
            assert data["data"]["agent_id"] == "test-123"

    def test_websocket_filters_by_agent_id(self, app, event_bus):
        client = TestClient(app)
        with client.websocket_connect("/v1/agents/events?agent_id=agent-A") as ws:
            # This event should NOT be received (different agent)
            event_bus.publish(EventType.AGENT_TICK_START, {"agent_id": "agent-B"})
            # This event SHOULD be received
            event_bus.publish(EventType.AGENT_TICK_START, {"agent_id": "agent-A"})
            time.sleep(0.05)  # Let call_soon_threadsafe deliver to queue
            data = ws.receive_json()
            assert data["data"]["agent_id"] == "agent-A"

    def test_client_disconnect_stops_handler(self, event_bus):
        async def exercise():
            from nira.server.ws_bridge import create_ws_router

            class FakeWebSocket:
                app = SimpleNamespace(state=SimpleNamespace(api_key=""))
                query_params = {}
                headers = {}

                async def accept(self, subprotocol=None):
                    pass

                async def receive(self):
                    return {"type": "websocket.disconnect"}

            endpoint = create_ws_router(event_bus).routes[0].endpoint
            await asyncio.wait_for(endpoint(FakeWebSocket()), timeout=1)

        asyncio.run(exercise())

    def test_simultaneous_client_message_does_not_drop_event(self, event_bus):
        async def exercise():
            from nira.server.ws_bridge import create_ws_router

            class FakeWebSocket:
                def __init__(self):
                    self.app = SimpleNamespace(state=SimpleNamespace(api_key=""))
                    self.query_params = {}
                    self.headers = {}
                    self.sent = []
                    self.receive_count = 0
                    self.disconnect = asyncio.Event()

                async def accept(self, subprotocol=None):
                    pass

                async def receive(self):
                    self.receive_count += 1
                    if self.receive_count == 1:
                        event_bus.publish(
                            EventType.AGENT_TICK_START, {"agent_id": "not-dropped"}
                        )
                        return {"type": "websocket.receive", "text": "client message"}
                    await self.disconnect.wait()
                    return {"type": "websocket.disconnect"}

                async def send_json(self, payload):
                    self.sent.append(payload)
                    self.disconnect.set()

            websocket = FakeWebSocket()
            endpoint = create_ws_router(event_bus).routes[0].endpoint

            await asyncio.wait_for(endpoint(websocket), timeout=1)

            assert websocket.sent[0]["data"]["agent_id"] == "not-dropped"

        asyncio.run(exercise())

    def test_cancelling_handler_cleans_up_child_tasks(self, event_bus):
        async def exercise():
            from nira.server.ws_bridge import create_ws_router

            class FakeWebSocket:
                def __init__(self):
                    self.app = SimpleNamespace(state=SimpleNamespace(api_key=""))
                    self.query_params = {}
                    self.headers = {}
                    self.receiving = asyncio.Event()
                    self.receive_cancelled = asyncio.Event()

                async def accept(self, subprotocol=None):
                    pass

                async def receive(self):
                    self.receiving.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        self.receive_cancelled.set()

            websocket = FakeWebSocket()
            endpoint = create_ws_router(event_bus).routes[0].endpoint
            handler = asyncio.create_task(endpoint(websocket))
            await websocket.receiving.wait()

            handler.cancel()
            with pytest.raises(asyncio.CancelledError):
                await handler

            assert websocket.receive_cancelled.is_set()
            assert not [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()
            ]

        asyncio.run(exercise())


class TestIncludeAllRoutesBusWiring:
    """Regression: the WS endpoint must subscribe on the same EventBus that
    channels/agents actually publish to (app.state.bus), not the unrelated
    get_event_bus() global singleton — publishing on the latter used to
    silently never reach any connected browser client."""

    def test_uses_app_state_bus_not_global_singleton(self):
        from nira.core.events import reset_event_bus
        from nira.server.api_routes import include_all_routes

        reset_event_bus()  # isolate from other tests' global singleton state
        app = FastAPI()
        real_bus = EventBus()
        app.state.bus = real_bus
        include_all_routes(app)

        client = TestClient(app)
        with client.websocket_connect("/v1/agents/events") as ws:
            real_bus.publish(EventType.AGENT_TICK_START, {"agent_id": "test-123"})
            time.sleep(0.05)
            data = ws.receive_json()
            assert data["data"]["agent_id"] == "test-123"

    @pytest.mark.parametrize(
        ("path", "payload"),
        [
            ("/v1/managed-agents/test-123/run", None),
            (
                "/v1/managed-agents/test-123/messages",
                {"content": "run now", "mode": "immediate", "stream": False},
            ),
        ],
    )
    def test_managed_agent_run_paths_publish_to_app_bus(self, path, payload):
        from nira.agents.executor import AgentExecutor
        from nira.core.events import reset_event_bus
        from nira.server.api_routes import include_all_routes

        reset_event_bus()
        app_bus = EventBus()
        manager = MagicMock()
        manager.get_agent.return_value = {
            "id": "test-123",
            "name": "test",
            "status": "idle",
            "config": {},
        }
        manager.send_message.return_value = {
            "id": "message-123",
            "agent_id": "test-123",
            "content": "run now",
            "mode": "immediate",
        }

        app = FastAPI()
        app.state.bus = app_bus
        app.state.agent_manager = manager
        include_all_routes(app)

        executed = threading.Event()
        observed_buses = []

        def publish_tick(executor, agent_id, **_kwargs):
            observed_buses.append(executor._bus)
            executor._bus.publish(EventType.AGENT_TICK_START, {"agent_id": agent_id})
            executed.set()

        client = TestClient(app)
        with (
            patch.object(AgentExecutor, "execute_tick", publish_tick),
            patch(
                "nira.server.agent_manager_routes._make_lightweight_system",
                return_value=MagicMock(),
            ) as make_system,
            client.websocket_connect("/v1/agents/events?agent_id=test-123") as ws,
        ):
            request_kwargs = {"json": payload} if payload is not None else {}
            response = client.post(path, **request_kwargs)
            assert response.status_code == 200
            assert executed.wait(timeout=1)
            assert observed_buses == [app_bus]
            data = ws.receive_json()

        assert data["type"] == "agent_tick_start"
        assert data["data"]["agent_id"] == "test-123"
        make_system.assert_called_once()


class TestReplayOnReconnect:
    """A phone drops this socket constantly — cell handover, screen lock,
    walking out of Wi-Fi range. Live-only delivery meant every reconnect
    silently lost whatever happened in the gap, so progress appeared to stall
    mid-task with nothing to say it had.
    """

    def _app(self, event_bus, capacity=None):
        from nira.server.event_log import EventLog
        from nira.server.ws_bridge import create_ws_router

        log = EventLog(capacity=capacity) if capacity else EventLog()
        app = FastAPI()
        app.include_router(create_ws_router(event_bus, log))
        return app, log

    def _publish(self, event_bus, tool):
        event_bus.publish(EventType.TOOL_CALL_START, {"tool": tool, "agent": "a1"})

    def test_a_reconnecting_client_receives_what_it_missed(self, event_bus):
        app, _ = self._app(event_bus)
        client = TestClient(app)

        # First session: see one event, note its cursor, then "lose signal".
        with client.websocket_connect("/v1/agents/events") as ws:
            self._publish(event_bus, "Read")
            first = ws.receive_json()
            cursor = first["seq"]

        # Work continues while the phone is offline.
        self._publish(event_bus, "Edit")
        self._publish(event_bus, "Write")

        with client.websocket_connect(f"/v1/agents/events?since={cursor}") as ws:
            start = ws.receive_json()
            assert start["type"] == "replay_start"
            assert start["count"] == 2
            assert start["gap"] is False

            replayed = [ws.receive_json(), ws.receive_json()]
            assert [e["data"]["tool"] for e in replayed] == ["Edit", "Write"]
            assert ws.receive_json()["type"] == "replay_end"

    def test_events_carry_a_cursor(self, event_bus):
        app, _ = self._app(event_bus)

        with TestClient(app).websocket_connect("/v1/agents/events") as ws:
            self._publish(event_bus, "Read")

            assert ws.receive_json()["seq"] == 1

    def test_a_fresh_subscriber_gets_no_backlog(self, event_bus):
        """Without `since`, a client wants what happens next."""
        app, _ = self._app(event_bus)
        self._publish(event_bus, "Old")
        client = TestClient(app)

        with client.websocket_connect("/v1/agents/events") as ws:
            self._publish(event_bus, "New")

            assert ws.receive_json()["data"]["tool"] == "New"

    def test_an_evicted_cursor_is_flagged_as_a_gap(self, event_bus):
        """A partial history handed over silently would render as a full one."""
        app, _ = self._app(event_bus, capacity=2)
        for tool in ("A", "B", "C", "D"):
            self._publish(event_bus, tool)

        with TestClient(app).websocket_connect("/v1/agents/events?since=1") as ws:
            assert ws.receive_json()["gap"] is True

    def test_replay_respects_the_agent_filter(self, event_bus):
        app, _ = self._app(event_bus)
        event_bus.publish(EventType.TOOL_CALL_START, {"tool": "Mine", "agent": "a1"})
        event_bus.publish(EventType.TOOL_CALL_START, {"tool": "Theirs", "agent": "a2"})

        with TestClient(app).websocket_connect(
            "/v1/agents/events?agent_id=a1&since=0"
        ) as ws:
            assert ws.receive_json()["type"] == "replay_start"
            first = ws.receive_json()

            assert first["data"]["tool"] == "Mine"
            assert first["type"] != "replay_end"

    def test_a_malformed_cursor_is_treated_as_the_beginning(self, event_bus):
        """A client must not be disconnected over a bad query param."""
        app, _ = self._app(event_bus)
        self._publish(event_bus, "Read")

        with TestClient(app).websocket_connect(
            "/v1/agents/events?since=not-a-number"
        ) as ws:
            assert ws.receive_json()["type"] == "replay_start"

    def test_live_events_still_arrive_after_a_replay(self, event_bus):
        """Registering before replaying means events raised mid-replay are
        queued rather than lost, so the two cannot race past each other."""
        app, _ = self._app(event_bus)
        self._publish(event_bus, "Before")

        with TestClient(app).websocket_connect("/v1/agents/events?since=0") as ws:
            assert ws.receive_json()["type"] == "replay_start"
            assert ws.receive_json()["data"]["tool"] == "Before"
            assert ws.receive_json()["type"] == "replay_end"

            self._publish(event_bus, "After")
            assert ws.receive_json()["data"]["tool"] == "After"
