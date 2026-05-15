# SPDX-License-Identifier: Apache-2.0
"""Scenario runner — wires up plugins, agents, and simulator from a ScenarioConfig.

Example::

    runner = ScenarioRunner(config)
    await runner.run()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nest_core.plugins import PluginRegistry
from nest_core.scenario import ScenarioConfig
from nest_core.sim.simulator import Simulator
from nest_core.types import AgentId


def _parse_partition_groups(raw: object) -> list[list[str]] | None:
    if not isinstance(raw, list):
        return None
    result: list[list[str]] = []
    for item in raw:  # type: ignore[union-attr]
        if isinstance(item, list):
            result.append([str(v) for v in item])  # type: ignore[union-attr]
    return result if result else None


class ScenarioRunner:
    """Runs a scenario end-to-end: resolves plugins, creates agents, runs simulation.

    Example::

        config = ScenarioConfig.from_yaml("scenarios/marketplace.yaml")
        runner = ScenarioRunner(config)
        await runner.run()
    """

    def __init__(self, config: ScenarioConfig, registry: PluginRegistry | None = None) -> None:
        self._config = config
        self._registry = registry or PluginRegistry()
        self._resolved_plugins: dict[str, Any] = {}
        self._metrics: dict[str, float] = {}

    @property
    def metrics(self) -> dict[str, float]:
        return self._metrics

    def _resolve_plugins(self) -> dict[str, Any]:
        """Resolve all layer plugins from the config.

        Example::

            plugins = runner._resolve_plugins()
        """
        layers = self._config.layers
        return {
            "transport": self._registry.resolve("transport", layers.transport),
            "comms": self._registry.resolve("comms", layers.comms),
            "identity": self._registry.resolve("identity", layers.identity),
            "registry": self._registry.resolve("registry", layers.registry),
            "auth": self._registry.resolve("auth", layers.auth),
            "trust": self._registry.resolve("trust", layers.trust),
            "payments": self._registry.resolve("payments", layers.payments),
            "coordination": self._registry.resolve("coordination", layers.coordination),
            "negotiation": self._registry.resolve("negotiation", layers.negotiation),
            "memory": self._registry.resolve("memory", layers.memory),
            "privacy": self._registry.resolve("privacy", layers.privacy),
            "datafacts": self._registry.resolve("datafacts", layers.datafacts),
        }

    def _create_agents(self, plugins: dict[str, Any]) -> dict[AgentId, Any]:
        """Create agents based on scenario config and task type.

        When the agent config specifies ``brain`` as ``"llm"`` or ``"shell"``,
        shell agent factories from *nest-shell* are used instead of the default
        state-machine factories.

        Example::

            agents = runner._create_agents(plugins)
        """
        brain = self._config.agents.brain

        if brain in ("llm", "shell"):
            return self._create_shell_agents(plugins)

        from nest_core.scenarios import get_scenario_factory

        factory = get_scenario_factory(self._config.task.type)
        return factory(self._config, plugins)

    def _create_shell_agents(self, plugins: dict[str, Any]) -> dict[AgentId, Any]:
        """Create LLM-backed shell agents for the configured task type.

        Example::

            agents = runner._create_shell_agents(plugins)
        """
        from nest_shell.agent import shell_marketplace_factory
        from nest_shell.factories import shell_auction_factory, shell_voting_factory
        from nest_shell.llm import LiteLLMBackend, MockLLMBackend

        model = self._config.agents.llm_model
        backend = MockLLMBackend() if model == "mock" else LiteLLMBackend(model=model)

        task_type = self._config.task.type
        if task_type == "marketplace":
            return shell_marketplace_factory(self._config, plugins, backend=backend)
        if task_type == "auction":
            return shell_auction_factory(self._config, plugins, backend=backend)
        if task_type == "voting":
            return shell_voting_factory(self._config, plugins, backend=backend)

        msg = f"No shell factory for task type {task_type!r}"
        raise KeyError(msg)

    async def run(self) -> Path:
        """Run the scenario and return the trace file path.

        Example::

            trace_path = await runner.run()
        """
        plugins = self._resolve_plugins()
        self._resolved_plugins = plugins

        trace_path = Path(self._config.output.trace)
        trace_path.parent.mkdir(parents=True, exist_ok=True)

        failures = self._config.failures
        partition_groups: list[list[str]] | None = None
        if failures.network_partition:
            raw_groups = failures.network_partition.get("groups")
            partition_groups = _parse_partition_groups(raw_groups)

        sim = Simulator(
            seed=self._config.seed,
            trace_path=trace_path,
            message_drop_rate=failures.message_drop,
            byzantine_fraction=failures.byzantine_agents,
            partition_groups=partition_groups,
        )

        agents = self._create_agents(plugins)
        for agent_id, agent in agents.items():
            sim.add_agent(agent_id, agent)

        max_ticks = self._config.get_max_ticks()
        await sim.run(max_ticks=max_ticks)

        if self._config.metrics:
            from nest_core.metrics import compute_metrics, generate_html_report

            self._metrics = compute_metrics(trace_path, self._config.metrics)

            if self._config.output.report:
                report_path = Path(self._config.output.report)
                generate_html_report(trace_path, self._metrics, report_path)

        return trace_path
