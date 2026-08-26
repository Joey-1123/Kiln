"""Tests for engine.supervisor — torch-free supervisor."""



from kiln.engine.supervisor import Supervisor, SupervisorConfig


class TestSupervisorConfig:
    def test_defaults(self):
        """Should have sensible defaults."""
        config = SupervisorConfig(engine_cmd=["echo", "ready"])
        assert config.ready_timeout == 30.0
        assert config.max_restarts == 5
        assert config.restart_delay == 2.0


class TestSupervisor:
    def test_not_running_initially(self):
        """Supervisor should not be running before start."""
        config = SupervisorConfig(engine_cmd=["echo", "ready"])
        supervisor = Supervisor(config)
        assert supervisor.is_running is False
        assert supervisor.engine_pid is None

    def test_stop_before_start(self):
        """Stopping before start should be safe."""
        config = SupervisorConfig(engine_cmd=["echo", "ready"])
        supervisor = Supervisor(config)
        supervisor.stop()  # Should not raise
        assert supervisor.is_running is False
