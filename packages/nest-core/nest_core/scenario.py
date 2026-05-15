# SPDX-License-Identifier: Apache-2.0
"""Pydantic schema for NEST scenario YAML files.

Example::

    from nest_core.scenario import ScenarioConfig
    config = ScenarioConfig.from_yaml("scenarios/marketplace.yaml")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class RoleConfig(BaseModel):
    """Configuration for a specific agent role within a scenario.

    Example::

        role = RoleConfig(name="buyer", count=50, prompt_template="buyer_v1")
    """

    name: str
    count: int
    prompt_template: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    """Agent configuration for a scenario.

    Example::

        agents = AgentConfig(count=100, brain="state-machine")
    """

    count: int = 10
    brain: str = "state-machine"
    llm_model: str = "gpt-4o-mini"
    roles: list[RoleConfig] = Field(default_factory=lambda: list[RoleConfig]())


class LayerConfig(BaseModel):
    """Plugin selection for each of the 12 layers.

    Example::

        layers = LayerConfig(transport="in_memory", comms="nest_native")
    """

    transport: str = "in_memory"
    comms: str = "nest_native"
    identity: str = "did_key"
    registry: str = "in_memory"
    auth: str = "jwt"
    trust: str = "score_average"
    payments: str = "prepaid_credits"
    coordination: str = "contract_net"
    negotiation: str = "alternating_offers"
    memory: str = "blackboard"
    privacy: str = "noop"
    datafacts: str = "datafacts_v1"


class TaskConfig(BaseModel):
    """Task configuration for the scenario.

    Example::

        task = TaskConfig(type="marketplace", config={"catalog_size": 200})
    """

    type: str = "marketplace"
    config: dict[str, Any] = Field(default_factory=dict)


class FailureConfig(BaseModel):
    """Failure injection configuration.

    Example::

        failures = FailureConfig(message_drop=0.05, byzantine_agents=0.10)
    """

    message_drop: float = 0.0
    byzantine_agents: float = 0.0
    network_partition: dict[str, Any] | None = None


class OutputConfig(BaseModel):
    """Output configuration for traces and reports.

    Example::

        output = OutputConfig(trace="./traces/out.jsonl")
    """

    trace: str = "./traces/output.jsonl"
    report: str | None = None


class ScenarioConfig(BaseModel):
    """Top-level scenario configuration parsed from YAML.

    Example::

        config = ScenarioConfig(name="test", tier=1)
    """

    name: str
    description: str = ""
    tier: int = 1
    agents: AgentConfig = Field(default_factory=AgentConfig)
    layers: LayerConfig = Field(default_factory=LayerConfig)
    task: TaskConfig = Field(default_factory=TaskConfig)
    failures: FailureConfig = Field(default_factory=FailureConfig)
    duration: str = "ticks: 10000"
    metrics: list[str] = Field(default_factory=list)
    output: OutputConfig = Field(default_factory=OutputConfig)
    seed: int = 0

    def get_max_ticks(self) -> int:
        """Parse the duration field into max ticks.

        Example::

            ticks = config.get_max_ticks()
        """
        if self.duration.startswith("ticks:"):
            return int(self.duration.split(":")[1].strip())
        return 10000

    @classmethod
    def from_yaml(cls, path: str | Path) -> ScenarioConfig:
        """Load a scenario configuration from a YAML file.

        Example::

            config = ScenarioConfig.from_yaml("scenarios/marketplace.yaml")
        """
        with Path(path).open() as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenarioConfig:
        """Create a scenario from a dictionary.

        Example::

            config = ScenarioConfig.from_dict({"name": "test", "tier": 1})
        """
        return cls.model_validate(data)
