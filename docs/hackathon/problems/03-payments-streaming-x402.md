---
title: Streaming pay-per-second payments with mid-stream cancellation
layer: payments
difficulty: easy
---

# Streaming pay-per-second payments with mid-stream cancellation

## Motivation

The default payments plugin
[`nest_plugins_reference/payments/prepaid_credits.py`](../../../packages/nest-plugins-reference/nest_plugins_reference/payments/prepaid_credits.py)
is 121 lines of "one-shot debit-credit ledger." Every `pay(to, amount,
ref)` moves the full amount atomically. PR #7
(`htlc_escrow`) added hash- and time-locked *conditional* payments —
genuinely useful for atomic-swap-shaped flows, but it is still a
**one-shot** transfer: you escrow, you claim, you're done.

What's missing is the *streaming* shape:
[`docs/layers/payments.md`](../../../docs/layers/payments.md) calls
out "streaming payments" as a wanted fit, and the
[`README.md`](../../../README.md) limitations section is silent on it.
LLM-agent traffic is increasingly metered (token-rate billing, inference-
per-second, bandwidth-per-byte), and x402-style HTTP-payment proposals
are explicitly per-request. The current `Payments` protocol can't
express "pay 0.01 credits every tick this stream is open, stop billing
the moment either side terminates." Any simulation of an LLM agent
hiring another LLM agent for a continuous task can't currently model
the *bill* accurately — agents end up either pre-paying a flat amount
(which over- or under-bills) or transferring nothing.

Anyone modelling metered services (rented compute, bandwidth, advisory
sessions, inference quotas) benefits.

## Success criteria

- Ship a payments plugin (suggested name: `streaming` or
  `per_tick_metered`) registered as `(\"payments\", \"streaming\")` in
  [`nest_core/plugins.py`](../../../packages/nest-core/nest_core/plugins.py).
- API: `open_stream(to, rate_per_tick, max_total, ref) -> StreamHandle`
  and `close_stream(ref) -> Receipt`. Funds drain from payer to payee
  one tick at a time, capped at `max_total`. Either party can call
  `close_stream` at any point; the unused remainder is **never** spent.
- The plugin satisfies the existing `Payments` protocol from
  [`nest_core/layers/payments.py`](../../../packages/nest-core/nest_core/layers/payments.py)
  — i.e., the one-shot `pay`/`refund` interface still works for
  protocols that don't speak streaming. `pay(to, amount, ref)` should
  behave equivalently to opening a stream that drains the full amount
  in one tick.
- Ship an adversarial validator that catches **two specific attacks**:
  1. *Drain-after-close*: payer closes the stream but a buggy plugin
     keeps debiting. Total debited must equal total credited at every
     tick (conservation invariant).
  2. *Over-bill on partition*: payer is partitioned mid-stream; the
     plugin must not keep billing for ticks the payee can't deliver.
     Use NEST's existing `failures.network_partition` config in
     [`nest_core/sim/simulator.py`](../../../packages/nest-core/nest_core/sim/simulator.py)
     (line ~246).
- Ship `scenarios/streaming_payments.yaml` with 5 buyers, 5 sellers,
  rolling streams, and 5% message drop. Validator passes. Trace is
  deterministic.

## Suggested approach pointers

- The simulator already exposes a logical clock (see
  `ctx.schedule(delay, ...)` in the agent contract). Use it; don't
  reach for `time.time()`.
- Borrow the conservation-of-funds invariant from PR #7's
  hypothesis test (`test_conservation_under_random_op_sequence`).
  Adapt it for streams.
- Sablier-style escrow draws are a clean reference design — but
  *don't* require any on-chain primitives; this is in-process only.
- A stream is a contract: store it in a dict keyed by `PaymentRef`,
  exactly like PR #7 does for HTLC contracts.
- Decide what `verify_payment` returns for a half-drained stream —
  `PENDING`? A new `STREAMING` enum variant? Document and justify.

## Anti-patterns

- Don't ship a "streaming" plugin that just pre-pays once and lies
  about it in the trace.
- Don't ship a plugin where `close_stream` is "best-effort." The payer
  must be able to stop the bleed at *any* tick, deterministically.
- Don't bypass the existing `PaymentStatus` enum; add to it if needed.
- Don't reuse `HtlcEscrow` and rename it. Streams aren't HTLCs.

## Out of scope

- Real on-chain settlement.
- Multi-party streams (one payer, many payees). Bilateral is
  sufficient.
- Currency conversion / multi-asset support.
