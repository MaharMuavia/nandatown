# SPDX-License-Identifier: Apache-2.0
"""Metrics computation from JSONL traces.

Example::

    results = compute_metrics(trace_path, ["success_rate", "mean_latency", "message_count"])
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def compute_metrics(
    trace_path: str | Path,
    metric_names: list[str],
) -> dict[str, float]:
    """Compute requested metrics from a JSONL trace file.

    Example::

        results = compute_metrics("trace.jsonl", ["success_rate", "message_count"])
    """
    trace_path = Path(trace_path)
    events = _load_events(trace_path)

    results: dict[str, float] = {}
    for name in metric_names:
        func = _METRIC_FUNCS.get(name)
        if func is not None:
            results[name] = func(events)

    return results


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def _success_rate(events: list[dict[str, Any]]) -> float:
    sends = 0
    receives = 0
    for ev in events:
        kind = ev.get("kind", "")
        if kind == "send":
            sends += 1
        elif kind == "receive":
            receives += 1
    if sends == 0:
        return 0.0
    return receives / sends


def _mean_latency(events: list[dict[str, Any]]) -> float:
    send_times: dict[str, float] = {}
    latencies: list[float] = []

    for ev in events:
        kind = ev.get("kind", "")
        corr = ev.get("corr", "")
        ts = ev.get("ts", 0.0)

        if kind == "send" and corr:
            send_times[corr] = ts
        elif kind == "receive" and corr:
            send_ts = send_times.get(corr)
            if send_ts is not None:
                latencies.append(ts - send_ts)

    if not latencies:
        return 0.0
    return sum(latencies) / len(latencies)


def _message_count(events: list[dict[str, Any]]) -> float:
    return float(sum(1 for ev in events if ev.get("kind") in ("send", "receive")))


def _dropped_count(events: list[dict[str, Any]]) -> float:
    return float(sum(1 for ev in events if ev.get("kind") == "dropped"))


def _agent_count(events: list[dict[str, Any]]) -> float:
    agents: set[str] = set()
    for ev in events:
        agent = ev.get("agent", "")
        if agent:
            agents.add(agent)
    return float(len(agents))


def _duration(events: list[dict[str, Any]]) -> float:
    if not events:
        return 0.0
    timestamps = [ev.get("ts", 0.0) for ev in events]
    return max(timestamps) - min(timestamps)


def _throughput(events: list[dict[str, Any]]) -> float:
    dur = _duration(events)
    msgs = _message_count(events)
    if dur <= 0:
        return msgs
    return msgs / dur


def _per_agent_stats(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"sends": 0, "receives": 0, "dropped": 0},
    )
    for ev in events:
        agent = ev.get("agent", "")
        kind = ev.get("kind", "")
        if kind == "send":
            stats[agent]["sends"] += 1
        elif kind == "receive":
            stats[agent]["receives"] += 1
        elif kind == "dropped":
            stats[agent]["dropped"] += 1
    return dict(stats)


_METRIC_FUNCS: dict[str, Any] = {
    "success_rate": _success_rate,
    "mean_latency": _mean_latency,
    "message_count": _message_count,
    "dropped_count": _dropped_count,
    "agent_count": _agent_count,
    "duration": _duration,
    "throughput": _throughput,
}

ALL_METRICS: list[str] = list(_METRIC_FUNCS.keys())


def generate_html_report(
    trace_path: str | Path,
    metrics: dict[str, float],
    output_path: str | Path,
) -> Path:
    """Generate an HTML report from metrics and trace data.

    Example::

        path = generate_html_report("trace.jsonl", metrics, "report.html")
    """
    trace_path = Path(trace_path)
    output_path = Path(output_path)
    events = _load_events(trace_path)
    agent_stats = _per_agent_stats(events)

    event_counts: dict[str, int] = defaultdict(int)
    for ev in events:
        kind = ev.get("kind", "unknown")
        event_counts[kind] += 1

    metrics_rows = "".join(
        f"<tr><td>{name}</td><td>{value:.4f}</td></tr>" for name, value in sorted(metrics.items())
    )

    event_rows = "".join(
        f"<tr><td>{kind}</td><td>{count}</td></tr>" for kind, count in sorted(event_counts.items())
    )

    agent_rows = ""
    sorted_agents = sorted(agent_stats.items(), key=lambda kv: kv[1]["sends"], reverse=True)
    for agent_name, stats in sorted_agents[:20]:
        agent_rows += (
            f"<tr><td>{agent_name}</td>"
            f"<td>{stats['sends']}</td>"
            f"<td>{stats['receives']}</td>"
            f"<td>{stats['dropped']}</td></tr>"
        )

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NEST Trace Report</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 900px;
  margin: 2rem auto; padding: 0 1rem; color: #333; }}
h1 {{ color: #1a1a2e; }}
h2 {{ color: #16213e; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%;
  margin: 1rem 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px;
  text-align: left; }}
th {{ background: #f4f4f8; font-weight: 600; }}
tr:nth-child(even) {{ background: #fafafa; }}
.summary {{ display: grid; gap: 1rem; margin: 1rem 0;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }}
.card {{ background: #f4f4f8; border-radius: 8px;
  padding: 1rem; }}
.card .value {{ font-size: 1.5rem; font-weight: 700;
  color: #1a1a2e; }}
.card .label {{ font-size: 0.85rem; color: #666; }}
footer {{ margin-top: 3rem; padding-top: 1rem;
  border-top: 1px solid #eee; font-size: 0.8rem; color: #999; }}
</style>
</head>
<body>
<h1>NEST Trace Report</h1>
<p>Source: <code>{trace_path.name}</code> &mdash; {len(events)} events</p>

<div class="summary">
<div class="card"><div class="value">\
{metrics.get("agent_count", len(agent_stats)):.0f}\
</div><div class="label">Agents</div></div>
<div class="card"><div class="value">\
{metrics.get("message_count", 0):.0f}\
</div><div class="label">Messages</div></div>
<div class="card"><div class="value">\
{metrics.get("success_rate", 0):.1%}\
</div><div class="label">Success Rate</div></div>
<div class="card"><div class="value">\
{metrics.get("mean_latency", 0):.2f}\
</div><div class="label">Mean Latency</div></div>
</div>

<h2>Metrics</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
{metrics_rows}
</table>

<h2>Event Breakdown</h2>
<table>
<tr><th>Kind</th><th>Count</th></tr>
{event_rows}
</table>

<h2>Top Agents</h2>
<table>
<tr><th>Agent</th><th>Sends</th><th>Receives</th><th>Dropped</th></tr>
{agent_rows}
</table>

<footer>Generated by NEST (Network Environment for Swarm Testing)</footer>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    return output_path
