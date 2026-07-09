# SPDX-License-Identifier: Apache-2.0
"""Tests for the OR-Map (observed-remove, add-wins) CRDT memory plugin.

Covers protocol conformance, the read/write/cas/subscribe surface, the
additive ``remove`` verb, the per-key and full-state export/merge replication
channel, the three CRDT algebraic laws (commutativity, associativity,
idempotence) of the full-state join, convergence under arbitrary delivery
order, determinism, malformed-input handling, registry wiring, the two
adversarial validators (add-wins survival and churn convergence -- which must
fail for ``blackboard`` and, for add-wins, for ``lww_register`` -- and pass for
the OR-Map), and an end-to-end scenario run under message loss that is
byte-deterministic across seeds.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from nest_core.layers.memory import Memory
from nest_core.plugins import PluginRegistry
from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig
from nest_core.validators import validate_crdt_convergence, validate_trace
from nest_plugins_reference.memory.blackboard import Blackboard
from nest_plugins_reference.memory.lww_register import LwwRegisterMemory
from nest_plugins_reference.memory.or_map import (
    CRDT_KIND,
    Dot,
    OrMapMemory,
    OrMapStateError,
)
from nest_plugins_reference.validators import (
    check_add_wins_survives_concurrent_remove,
    check_convergence_under_churn,
)

# ---------------------------------------------------------------------------
# Protocol conformance and base Memory surface
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_isinstance_memory(self) -> None:
        assert isinstance(OrMapMemory("a"), Memory)

    @pytest.mark.asyncio
    async def test_read_missing_is_none(self) -> None:
        assert await OrMapMemory("a").read("missing") is None

    @pytest.mark.asyncio
    async def test_write_read_roundtrip(self) -> None:
        mem = OrMapMemory("a")
        await mem.write("k", b"value")
        assert await mem.read("k") == b"value"

    @pytest.mark.asyncio
    async def test_overwrite_keeps_latest(self) -> None:
        mem = OrMapMemory("a")
        await mem.write("k", b"old")
        await mem.write("k", b"new")
        assert await mem.read("k") == b"new"

    @pytest.mark.asyncio
    async def test_cas_success(self) -> None:
        mem = OrMapMemory("a")
        await mem.write("k", b"old")
        assert await mem.cas("k", b"old", b"new") is True
        assert await mem.read("k") == b"new"

    @pytest.mark.asyncio
    async def test_cas_failure_leaves_value(self) -> None:
        mem = OrMapMemory("a")
        await mem.write("k", b"current")
        assert await mem.cas("k", b"wrong", b"new") is False
        assert await mem.read("k") == b"current"

    @pytest.mark.asyncio
    async def test_cas_on_missing_key(self) -> None:
        assert await OrMapMemory("a").cas("k", b"expected", b"new") is False

    @pytest.mark.asyncio
    async def test_binary_payload(self) -> None:
        mem = OrMapMemory("a")
        blob = bytes(range(256))
        await mem.write("k", blob)
        assert await mem.read("k") == blob

    @pytest.mark.asyncio
    async def test_subscribe_receives_writes(self) -> None:
        mem = OrMapMemory("a")
        sub = mem.subscribe("k")
        fut = asyncio.ensure_future(anext(sub))
        await asyncio.sleep(0)  # let the generator register its queue
        await mem.write("k", b"first")
        assert await asyncio.wait_for(fut, 5) == b"first"

    @pytest.mark.asyncio
    async def test_subscribe_receives_merges(self) -> None:
        a = OrMapMemory("a")
        b = OrMapMemory("b")
        await a.write("k", b"v")
        sub = b.subscribe("k")
        fut = asyncio.ensure_future(anext(sub))
        await asyncio.sleep(0)
        await b.merge_all(a.export_all())
        assert await asyncio.wait_for(fut, 5) == b"v"


# ---------------------------------------------------------------------------
# The additive remove verb
# ---------------------------------------------------------------------------


class TestRemove:
    @pytest.mark.asyncio
    async def test_remove_makes_key_absent(self) -> None:
        mem = OrMapMemory("a")
        await mem.write("k", b"v")
        assert await mem.remove("k") is True
        assert await mem.read("k") is None

    @pytest.mark.asyncio
    async def test_remove_missing_is_false(self) -> None:
        assert await OrMapMemory("a").remove("k") is False

    @pytest.mark.asyncio
    async def test_remove_is_idempotent(self) -> None:
        mem = OrMapMemory("a")
        await mem.write("k", b"v")
        assert await mem.remove("k") is True
        assert await mem.remove("k") is False

    @pytest.mark.asyncio
    async def test_readd_after_remove(self) -> None:
        mem = OrMapMemory("a")
        await mem.write("k", b"v1")
        await mem.remove("k")
        await mem.write("k", b"v2")
        assert await mem.read("k") == b"v2"


# ---------------------------------------------------------------------------
# Export / merge replication channel
# ---------------------------------------------------------------------------


class TestExportMerge:
    @pytest.mark.asyncio
    async def test_export_never_seen_is_none(self) -> None:
        assert OrMapMemory("a").export("k") is None

    @pytest.mark.asyncio
    async def test_export_is_grep_able_json(self) -> None:
        mem = OrMapMemory("a")
        await mem.write("k", b"hi")
        raw = mem.export("k")
        assert raw is not None
        assert CRDT_KIND.encode() in raw

    @pytest.mark.asyncio
    async def test_merge_into_empty_adopts_value(self) -> None:
        a = OrMapMemory("a")
        b = OrMapMemory("b")
        await a.write("k", b"from-a")
        state = a.export("k")
        assert state is not None
        assert await b.merge("k", state) is True
        assert await b.read("k") == b"from-a"

    @pytest.mark.asyncio
    async def test_merge_is_idempotent(self) -> None:
        a = OrMapMemory("a")
        b = OrMapMemory("b")
        await a.write("k", b"x")
        state = a.export("k")
        assert state is not None
        assert await b.merge("k", state) is True
        assert await b.merge("k", state) is False
        assert await b.read("k") == b"x"

    @pytest.mark.asyncio
    async def test_full_state_removal_propagates(self) -> None:
        a = OrMapMemory("a")
        b = OrMapMemory("b")
        await a.write("k", b"v")
        await b.merge_all(a.export_all())
        assert await b.read("k") == b"v"
        await a.remove("k")
        await b.merge_all(a.export_all())
        assert await b.read("k") is None

    @pytest.mark.asyncio
    async def test_export_all_merge_all_roundtrip(self) -> None:
        a = OrMapMemory("a")
        await a.write("k1", b"v1")
        await a.write("k2", b"v2")
        b = OrMapMemory("b")
        changed = await b.merge_all(a.export_all())
        assert changed == ["k1", "k2"]
        assert await b.read("k1") == b"v1"
        assert await b.read("k2") == b"v2"


# ---------------------------------------------------------------------------
# Add-wins semantics (the headline novelty)
# ---------------------------------------------------------------------------


class TestAddWins:
    @pytest.mark.asyncio
    async def test_concurrent_add_survives_stale_remove(self) -> None:
        a = OrMapMemory("a")
        b = OrMapMemory("b")
        await a.write("k", b"old")
        await b.merge_all(a.export_all())  # b observes the old add
        # Concurrent: a re-adds; b removes what it saw.
        await a.write("k", b"new")
        await b.remove("k")
        await a.merge_all(b.export_all())
        await b.merge_all(a.export_all())
        assert await a.read("k") == b"new"
        assert await b.read("k") == b"new"

    @pytest.mark.asyncio
    async def test_remove_of_fully_observed_add_wins(self) -> None:
        # If the remover HAS observed every add, the key is genuinely removed.
        a = OrMapMemory("a")
        b = OrMapMemory("b")
        await a.write("k", b"v")
        await b.merge_all(a.export_all())
        await b.remove("k")
        await a.merge_all(b.export_all())
        assert await a.read("k") is None
        assert await b.read("k") is None


# ---------------------------------------------------------------------------
# Malformed input handling
# ---------------------------------------------------------------------------


class TestMalformedState:
    @pytest.mark.asyncio
    async def test_merge_rejects_non_json(self) -> None:
        with pytest.raises(OrMapStateError):
            await OrMapMemory("a").merge("k", b"\xff\xfenot json")

    @pytest.mark.asyncio
    async def test_merge_rejects_wrong_kind(self) -> None:
        with pytest.raises(OrMapStateError):
            await OrMapMemory("a").merge("k", b'{"crdt": "other", "x": 1}')

    @pytest.mark.asyncio
    async def test_merge_all_rejects_bad_keys(self) -> None:
        with pytest.raises(OrMapStateError):
            await OrMapMemory("a").merge_all(b'{"crdt": "or_map", "keys": 5}')

    def test_or_map_state_error_is_value_error(self) -> None:
        assert issubclass(OrMapStateError, ValueError)


# ---------------------------------------------------------------------------
# CRDT algebraic laws (property-based) over the full-state join
# ---------------------------------------------------------------------------

_verb = st.sampled_from(["w", "r"])
_payload = st.binary(min_size=0, max_size=4)
_program = st.lists(st.tuples(_verb, _payload), min_size=0, max_size=4)


async def _state_from_program(node: str, program: list[tuple[str, bytes]]) -> bytes:
    mem = OrMapMemory(node)
    for verb, payload in program:
        if verb == "w":
            await mem.write("k", payload)
        else:
            await mem.remove("k")
    return mem.export_all()


async def _merged_export(states: list[bytes]) -> bytes:
    merger = OrMapMemory("merger")
    for s in states:
        await merger.merge_all(s)
    return merger.export_all()


class TestCrdtLaws:
    @settings(max_examples=60, deadline=None)
    @given(p1=_program, p2=_program)
    @pytest.mark.asyncio
    async def test_merge_is_commutative(
        self, p1: list[tuple[str, bytes]], p2: list[tuple[str, bytes]]
    ) -> None:
        s1 = await _state_from_program("a", p1)
        s2 = await _state_from_program("b", p2)
        assert await _merged_export([s1, s2]) == await _merged_export([s2, s1])

    @settings(max_examples=60, deadline=None)
    @given(p1=_program, p2=_program, p3=_program)
    @pytest.mark.asyncio
    async def test_merge_is_associative(
        self,
        p1: list[tuple[str, bytes]],
        p2: list[tuple[str, bytes]],
        p3: list[tuple[str, bytes]],
    ) -> None:
        s1 = await _state_from_program("a", p1)
        s2 = await _state_from_program("b", p2)
        s3 = await _state_from_program("c", p3)
        assert await _merged_export([s1, s2, s3]) == await _merged_export([s3, s2, s1])

    @settings(max_examples=60, deadline=None)
    @given(p1=_program)
    @pytest.mark.asyncio
    async def test_merge_is_idempotent(self, p1: list[tuple[str, bytes]]) -> None:
        s1 = await _state_from_program("a", p1)
        assert await _merged_export([s1]) == await _merged_export([s1, s1])


# ---------------------------------------------------------------------------
# Convergence under arbitrary delivery order + determinism
# ---------------------------------------------------------------------------


class TestConvergence:
    @settings(max_examples=40, deadline=None)
    @given(data=st.data())
    @pytest.mark.asyncio
    async def test_replicas_converge_for_any_order(self, data: st.DataObject) -> None:
        n_writes = data.draw(st.integers(min_value=2, max_value=6))
        replicas = data.draw(st.integers(min_value=2, max_value=5))
        writes = [
            (data.draw(st.integers(min_value=0, max_value=replicas - 1)), f"v{i}".encode())
            for i in range(n_writes)
        ]
        orders = [data.draw(st.permutations(list(range(n_writes)))) for _ in range(replicas)]
        results = await validate_crdt_convergence(OrMapMemory, writes, orders)
        assert all(r.passed for r in results), results[0].detail

    @pytest.mark.asyncio
    async def test_determinism_same_ops_same_state(self) -> None:
        async def build() -> bytes:
            a = OrMapMemory("a")
            b = OrMapMemory("b")
            await a.write("k", b"one")
            await b.write("k", b"two")
            await a.merge_all(b.export_all())
            await a.remove("k")
            await a.write("k", b"three")
            return a.export_all()

        assert await build() == await build()

    @pytest.mark.asyncio
    async def test_dot_ordering_is_deterministic(self) -> None:
        assert Dot(counter=2, node="a") > Dot(counter=1, node="z")
        assert Dot(counter=1, node="b") > Dot(counter=1, node="a")


# ---------------------------------------------------------------------------
# Adversarial validators: reference plugins must fail, OR-Map must pass
# ---------------------------------------------------------------------------


class TestAdversarialValidators:
    def test_add_wins_passes_for_or_map(self) -> None:
        report = check_add_wins_survives_concurrent_remove(OrMapMemory)
        assert report.passed, report.detail

    def test_add_wins_fails_for_blackboard(self) -> None:
        report = check_add_wins_survives_concurrent_remove(lambda _n: Blackboard())
        assert not report.passed

    def test_add_wins_fails_for_lww_register(self) -> None:
        report = check_add_wins_survives_concurrent_remove(LwwRegisterMemory)
        assert not report.passed

    def test_churn_convergence_passes_for_or_map(self) -> None:
        report = check_convergence_under_churn(OrMapMemory)
        assert report.passed, report.detail

    def test_churn_convergence_fails_for_blackboard(self) -> None:
        report = check_convergence_under_churn(lambda _n: Blackboard())
        assert not report.passed


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_builtin_resolves(self) -> None:
        assert PluginRegistry().resolve("memory", "or_map") is OrMapMemory

    def test_listed_for_memory_layer(self) -> None:
        assert ("memory", "or_map") in PluginRegistry().list_plugins("memory")


# ---------------------------------------------------------------------------
# End-to-end scenario: convergence under loss, deterministic across seeds
# ---------------------------------------------------------------------------


class TestScenario:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", [42, 7, 1337])
    async def test_scenario_converges_and_is_deterministic(self, seed: int) -> None:
        traces: list[bytes] = []
        with tempfile.TemporaryDirectory() as tmp:
            for run in range(2):
                config = ScenarioConfig.from_yaml("scenarios/memory_or_map_add_remove.yaml")
                config.seed = seed
                out = Path(tmp) / f"run-{run}.jsonl"
                config.output.trace = str(out)
                trace_path = await ScenarioRunner(config).run()
                traces.append(trace_path.read_bytes())
                if run == 0:
                    results = validate_trace(trace_path, "memory_or_map_add_remove")
                    assert results, "validator produced no results"
                    assert all(r.passed for r in results), [r.detail for r in results]
        assert traces[0] == traces[1], "trace not byte-identical under same seed"
