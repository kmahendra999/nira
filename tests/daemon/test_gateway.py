from __future__ import annotations


def test_gateway_session_key_format():
    from nira.daemon.gateway import GatewayDaemon

    key = GatewayDaemon.session_key(
        platform="telegram", chat_type="dm", chat_id="12345", thread_id=None
    )
    assert key == "agent:main:telegram:dm:12345:None"


def test_gateway_session_key_deterministic():
    from nira.daemon.gateway import GatewayDaemon

    key1 = GatewayDaemon.session_key("discord", "group", "abc", "thread1")
    key2 = GatewayDaemon.session_key("discord", "group", "abc", "thread1")
    assert key1 == key2


class _FakeScheduler:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self, timeout: float = 10.0) -> None:
        self.stops += 1


class TestGatewayLifecycle:
    """The daemon has to stay up and shut down cleanly.

    Its units are supervised by systemd and launchd, so a start() that returns
    immediately means the service exits 0 the moment it launches — systemd
    treats that as a clean finish and will not restart it, while launchd's
    KeepAlive respawns it forever. Both then report a healthy gateway.
    """

    def test_start_brings_components_up(self):
        from nira.daemon.gateway import GatewayDaemon

        scheduler = _FakeScheduler()
        daemon = GatewayDaemon(agent_scheduler=scheduler)

        daemon.start()

        assert daemon.is_running is True
        assert scheduler.starts == 1

    def test_start_is_idempotent(self):
        from nira.daemon.gateway import GatewayDaemon

        scheduler = _FakeScheduler()
        daemon = GatewayDaemon(agent_scheduler=scheduler)

        daemon.start()
        daemon.start()

        assert scheduler.starts == 1

    def test_stop_takes_components_down_once(self):
        from nira.daemon.gateway import GatewayDaemon

        scheduler = _FakeScheduler()
        daemon = GatewayDaemon(agent_scheduler=scheduler)
        daemon.start()

        daemon.stop()
        daemon.stop()

        assert daemon.is_running is False
        assert scheduler.stops == 1

    def test_wait_blocks_until_stopped(self):
        import threading
        import time

        from nira.daemon.gateway import GatewayDaemon

        daemon = GatewayDaemon()
        daemon.start()

        assert daemon.wait(timeout=0.05) is False, "wait() returned before stop()"

        threading.Timer(0.1, daemon.stop).start()
        started = time.monotonic()
        assert daemon.wait(timeout=5.0) is True
        assert time.monotonic() - started < 5.0

    def test_run_forever_blocks_and_then_cleans_up(self):
        import threading

        from nira.daemon.gateway import GatewayDaemon

        scheduler = _FakeScheduler()
        daemon = GatewayDaemon(agent_scheduler=scheduler)

        thread = threading.Thread(target=daemon.run_forever, daemon=True)
        thread.start()
        # Give run_forever a moment to reach its wait().
        for _ in range(200):
            if daemon.is_running:
                break
            threading.Event().wait(0.01)
        assert daemon.is_running is True
        assert thread.is_alive(), "run_forever returned instead of blocking"

        daemon.stop()
        thread.join(timeout=5.0)

        assert not thread.is_alive()
        assert scheduler.stops == 1


class TestGeneratedServiceUnits:
    def test_units_point_at_a_runnable_entry_point(self, tmp_path):
        """`python -m <target>` must not exit 0 on import.

        The templates used to target nira.daemon.gateway, which had no
        __main__ block, so the service started and immediately finished.
        """
        import importlib.util

        from nira.daemon.service import (
            generate_launchd_plist,
            generate_systemd_service,
        )

        systemd = generate_systemd_service()
        launchd = generate_launchd_plist()

        assert "-m nira.daemon" in systemd
        assert "<string>nira.daemon</string>" in launchd

        # The targeted module must be executable as a package entry point.
        assert importlib.util.find_spec("nira.daemon.__main__") is not None

    def test_launchd_writes_the_log_file_the_cli_advertises(self):
        """`nira gateway logs` tells macOS users to read this path."""
        from nira.daemon.service import generate_launchd_plist

        plist = generate_launchd_plist()

        assert "StandardOutPath" in plist
        assert "com.nira.gateway.log" in plist
        assert "StandardErrorPath" in plist
