# SPDX-License-Identifier: Apache-2.0
"""NEST CLI entry point.

Example::

    nest run scenarios/marketplace.yaml
    nest doctor
    nest init my-scenario
    nest plugins list
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(
    name="nest",
    help="NEST — Network Environment for Swarm Testing",
    no_args_is_help=True,
)

plugins_app = typer.Typer(help="Manage plugins.")
app.add_typer(plugins_app, name="plugins")


@app.command()
def run(
    scenario: str = typer.Argument(help="Path to a scenario YAML file."),
    seed: int | None = typer.Option(None, help="Override the scenario seed."),
    ticks: int | None = typer.Option(None, help="Override max ticks."),
    output: str | None = typer.Option(None, "-o", "--output", help="Override trace output path."),
) -> None:
    """Run a scenario from a YAML file."""
    from nest_core.scenario import ScenarioConfig

    path = Path(scenario)
    if not path.exists():
        typer.echo(f"Error: scenario file not found: {scenario}", err=True)
        raise typer.Exit(1)

    config = ScenarioConfig.from_yaml(path)

    if seed is not None:
        config.seed = seed
    if ticks is not None:
        config.duration = f"ticks: {ticks}"
    if output is not None:
        config.output.trace = output

    typer.echo(f"Running scenario: {config.name}")
    ticks = config.get_max_ticks()
    typer.echo(f"  agents: {config.agents.count}  seed: {config.seed}  ticks: {ticks}")

    trace_path = asyncio.run(_run_scenario(config))
    typer.echo(f"Trace written to: {trace_path}")


async def _run_scenario(config: Any) -> Path:
    from nest_core.runner import ScenarioRunner

    runner = ScenarioRunner(config)
    return await runner.run()


@app.command()
def init(
    name: str = typer.Argument("my-scenario", help="Name for the new scenario."),
    directory: str | None = typer.Option(
        None,
        "-d",
        "--dir",
        help="Directory to create the file in.",
    ),
) -> None:
    """Scaffold a new scenario YAML file."""
    target_dir = Path(directory) if directory else Path("scenarios")
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{name}.yaml"
    filepath = target_dir / filename

    if filepath.exists():
        typer.echo(f"Error: {filepath} already exists.", err=True)
        raise typer.Exit(1)

    template = f"""\
# NEST scenario: {name}
name: {name}
description: "TODO: describe your scenario"

tier: 1
seed: 42

agents:
  count: 20
  brain: state-machine
  roles:
    - name: buyer
      count: 10
    - name: seller
      count: 10

layers:
  transport: in_memory
  comms: nest_native
  identity: did_key
  registry: in_memory
  auth: jwt
  trust: score_average
  payments: prepaid_credits
  coordination: contract_net
  negotiation: alternating_offers
  memory: blackboard
  privacy: noop
  datafacts: datafacts_v1

task:
  type: marketplace
  config:
    rounds: 5

duration: "ticks: 5000"

metrics:
  - success_rate
  - mean_latency
  - message_count

output:
  trace: ./traces/{name}.jsonl
"""
    filepath.write_text(template)
    typer.echo(f"Created scenario: {filepath}")


@app.command()
def doctor() -> None:
    """Check installation, plugin compatibility, and system health."""
    checks_passed = 0
    checks_failed = 0

    typer.echo("NEST doctor")
    typer.echo("=" * 40)

    # Python version
    py = sys.version_info
    if py >= (3, 12):
        typer.echo(f"  [OK] Python {py.major}.{py.minor}.{py.micro}")
        checks_passed += 1
    else:
        typer.echo(f"  [FAIL] Python {py.major}.{py.minor} (need >= 3.12)")
        checks_failed += 1

    # Core imports
    core_modules = [
        ("nest_core", "nest-core"),
        ("nest_core.scenario", "scenario loader"),
        ("nest_core.plugins", "plugin registry"),
        ("nest_core.runner", "scenario runner"),
        ("nest_core.sim.simulator", "simulator"),
    ]
    for mod_name, label in core_modules:
        try:
            __import__(mod_name)
            typer.echo(f"  [OK] {label}")
            checks_passed += 1
        except ImportError as e:
            typer.echo(f"  [FAIL] {label}: {e}")
            checks_failed += 1

    # Plugin resolution
    try:
        from nest_core.plugins import PluginRegistry

        reg = PluginRegistry()
        layers = [
            "transport",
            "comms",
            "identity",
            "registry",
            "auth",
            "trust",
            "payments",
            "coordination",
            "negotiation",
            "memory",
            "privacy",
            "datafacts",
        ]
        plugin_ok = 0
        for layer_name in layers:
            try:
                reg.resolve(layer_name, _default_for(layer_name))
                plugin_ok += 1
            except KeyError:
                typer.echo(f"  [FAIL] plugin: {layer_name}")
                checks_failed += 1
        if plugin_ok == len(layers):
            typer.echo(f"  [OK] all {len(layers)} default plugins resolve")
            checks_passed += 1
    except Exception as e:
        typer.echo(f"  [FAIL] plugin registry: {e}")
        checks_failed += 1

    typer.echo("=" * 40)
    total = checks_passed + checks_failed
    typer.echo(f"{checks_passed}/{total} checks passed")
    if checks_failed > 0:
        raise typer.Exit(1)


def _default_for(layer: str) -> str:
    defaults: dict[str, str] = {
        "transport": "in_memory",
        "comms": "nest_native",
        "identity": "did_key",
        "registry": "in_memory",
        "auth": "jwt",
        "trust": "score_average",
        "payments": "prepaid_credits",
        "coordination": "contract_net",
        "negotiation": "alternating_offers",
        "memory": "blackboard",
        "privacy": "noop",
        "datafacts": "datafacts_v1",
    }
    return defaults[layer]


@app.command()
def inspect(
    trace: str = typer.Argument(help="Path to a JSONL trace file."),
) -> None:
    """Inspect and summarize a trace file."""
    from nest_core.inspect import analyze_trace, format_summary

    path = Path(trace)
    if not path.exists():
        typer.echo(f"Error: trace file not found: {trace}", err=True)
        raise typer.Exit(1)

    summary = analyze_trace(path)
    typer.echo(format_summary(summary))


@app.command()
def report(
    trace: str = typer.Argument(help="Path to a JSONL trace file."),
    output: str | None = typer.Option(None, "-o", "--output", help="Output HTML report path."),
    metrics: str | None = typer.Option(
        None,
        "-m",
        "--metrics",
        help="Comma-separated metric names.",
    ),
) -> None:
    """Compute metrics and generate an HTML report from a trace."""
    from nest_core.metrics import ALL_METRICS, compute_metrics, generate_html_report

    path = Path(trace)
    if not path.exists():
        typer.echo(f"Error: trace file not found: {trace}", err=True)
        raise typer.Exit(1)

    metric_names = metrics.split(",") if metrics else ALL_METRICS
    results = compute_metrics(path, metric_names)

    typer.echo("Metrics:")
    for name, value in sorted(results.items()):
        typer.echo(f"  {name:20s} {value:.4f}")

    if output:
        out_path = generate_html_report(path, results, output)
        typer.echo(f"\nReport written to: {out_path}")


@app.command()
def dashboard(
    trace: str | None = typer.Argument(None, help="Optional trace file to load."),
    port: int = typer.Option(8080, help="Port to serve on."),
) -> None:
    """Open the interactive trace dashboard in a browser."""
    import functools
    import http.server
    import threading
    import webbrowser

    dashboard_html = _find_dashboard_html()
    if dashboard_html is None:
        typer.echo("Error: cannot locate apps/dashboard/index.html", err=True)
        raise typer.Exit(1)

    html_content = dashboard_html.read_text(encoding="utf-8")

    if trace is not None:
        trace_path = Path(trace)
        if not trace_path.exists():
            typer.echo(f"Error: trace file not found: {trace}", err=True)
            raise typer.Exit(1)
        trace_text = trace_path.read_text(encoding="utf-8")
        # Escape for safe embedding inside JS string literal
        escaped = trace_text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
        html_content = html_content.replace("__NEST_TRACE_DATA__", escaped)

    # Serve from a temporary directory with the (possibly modified) HTML
    import tempfile

    serve_dir = tempfile.mkdtemp(prefix="nest-dashboard-")
    serve_path = Path(serve_dir) / "index.html"
    serve_path.write_text(html_content, encoding="utf-8")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=serve_dir)
    server = http.server.HTTPServer(("127.0.0.1", port), handler)

    url = f"http://127.0.0.1:{port}"
    typer.echo(f"Serving dashboard at {url}")
    if trace is not None:
        typer.echo(f"  trace: {trace}")
    typer.echo("Press Ctrl+C to stop.\n")

    # Open browser after a short delay so the server is ready
    def _open_browser() -> None:
        import time

        time.sleep(0.4)
        webbrowser.open(url)

    t = threading.Thread(target=_open_browser, daemon=True)
    t.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nShutting down.")
    finally:
        server.server_close()


def _find_dashboard_html() -> Path | None:
    """Locate the dashboard HTML file relative to the project root."""
    # Walk up from this file to find the repo root (contains pyproject.toml workspace)
    candidates: list[Path] = []

    # Try relative to CWD
    candidates.append(Path.cwd() / "apps" / "dashboard" / "index.html")

    # Try relative to this source file
    cli_dir = Path(__file__).resolve().parent  # nest_cli/
    for ancestor in [cli_dir.parent, cli_dir.parent.parent, cli_dir.parent.parent.parent]:
        candidates.append(ancestor / "apps" / "dashboard" / "index.html")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


@app.command()
def version() -> None:
    """Print the NEST version."""
    typer.echo("nest 0.1.0")


@plugins_app.command("list")
def plugins_list(
    layer: str | None = typer.Argument(None, help="Filter by layer name."),
) -> None:
    """List available plugins."""
    from nest_core.plugins import PluginRegistry

    reg = PluginRegistry()
    items = reg.list_plugins(layer)

    if not items:
        if layer:
            typer.echo(f"No plugins found for layer: {layer}")
        else:
            typer.echo("No plugins found.")
        return

    current_layer = ""
    for layer_name, plugin_name in items:
        if layer_name != current_layer:
            current_layer = layer_name
            typer.echo(f"\n{layer_name}:")
        typer.echo(f"  - {plugin_name}")


if __name__ == "__main__":
    app()
