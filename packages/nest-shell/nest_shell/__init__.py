# SPDX-License-Identifier: Apache-2.0
"""NEST shell: Tier 2 LLM-backed reference agent."""

__version__ = "0.1.0"

from nest_shell.agent import ShellAgent as ShellAgent
from nest_shell.agent import shell_marketplace_factory as shell_marketplace_factory
from nest_shell.factories import shell_auction_factory as shell_auction_factory
from nest_shell.factories import shell_voting_factory as shell_voting_factory
from nest_shell.llm import LiteLLMBackend as LiteLLMBackend
from nest_shell.llm import LLMBackend as LLMBackend
from nest_shell.llm import MockLLMBackend as MockLLMBackend
