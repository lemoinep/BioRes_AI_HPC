from __future__ import annotations

import json
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Any

import typer
from rich.console import Console

from biores_ai_hpc.checkpoint_store import CheckpointStore
from biores_ai_hpc.controller import ResilienceController
from biores_ai_hpc.cpp_bridge import run_worker
from biores_ai_hpc.state_machine import RecoveryState

app = typer.Typer(
    name="biores",
    help="BioRes-AI/HPC resilience prototype.",
    no_args_is_help=True,
)

console = Console()


@app.callback()
def main() -> None:
    """BioRes-AI/HPC command-line interface."""


@app.command()
def demo(
    worker: Path = typer.Option(
        Path("build/cpp/Release/biores_worker.exe"),
        help="Path to the C++ worker executable.",
    ),
    residual_threshold: float = typer.Option(
        0.01,
        min=0.0,
        help="Maximum acceptable numerical residual.",
    ),
) -> None:
    """Run a nominal C++ workflow and demonstrate verification logic."""
    if not worker.exists():
        raise typer.BadParameter(
            f"Worker executable not found: {worker}. "
            "Build the C++ project first."
        )

    controller = ResilienceController()
    last_checkpoint_valid = False
    final_residual = float("inf")

    process = subprocess.Popen(
        [
            str(worker),
            "--iterations",
            "100",
            "--checkpoint-interval",
            "20",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    assert process.stdout is not None

    for raw_line in process.stdout:
        line = raw_line.strip()

        if not line:
            continue

        event = json.loads(line)

        if event["event_type"] == "checkpoint":
            last_checkpoint_valid = bool(event["checksum_valid"])
            console.print(
                f"[green]Observed checkpoint:[/green] "
                f"{event['checkpoint_id']}"
            )

        elif event["event_type"] == "completed":
            final_residual = float(event["residual"])

    return_code = process.wait()

    if return_code != 0:
        console.print("[red]Worker execution failed.[/red]")
        raise typer.Exit(code=return_code)

    controller.detect_incident()
    controller.isolate_incident()
    controller.activate_degraded_mode()
    controller.restore()

    result = controller.verify(
        checkpoint_valid=last_checkpoint_valid,
        residual=final_residual,
        maximum_residual=residual_threshold,
    )

    console.print(f"Final state: [bold]{controller.state.value}[/bold]")
    console.print(result.message)

    safe_recovery_time = controller.timing.safe_recovery_time()
    if safe_recovery_time is not None:
        console.print(
            f"Safe recovery time: {safe_recovery_time:.6f} seconds"
        )

    if controller.state != RecoveryState.VERIFIED:
        raise typer.Exit(code=3)


@app.command(name="run-failure")
def run_failure(
    worker: Path = typer.Option(
        Path("build/cpp/Release/biores_worker.exe"),
        help="Path to the C++ worker executable.",
    ),
    iterations: int = typer.Option(
        100,
        min=1,
        help="Total number of workflow iterations.",
    ),
    checkpoint_interval: int = typer.Option(
        20,
        min=1,
        help="Checkpoint interval in iterations.",
    ),
    fail_at: int = typer.Option(
        55,
        min=1,
        help="Iteration at which the first worker fails.",
    ),
    corrupt_checkpoint_at: int | None = typer.Option(
        None,
        help="Mark the checkpoint at this iteration as corrupted.",
    ),
    run_id: str = typer.Option(
        "default-run",
        help="Identifier used for checkpoint storage.",
    ),
    checkpoint_root: Path = typer.Option(
        Path("results/checkpoints"),
        help="Root directory containing checkpoint artifacts.",
    ),
    residual_threshold: float = typer.Option(
        0.01,
        min=0.0,
        help="Maximum acceptable residual after recovery.",
    ),
) -> None:
    """Inject a worker fault and perform stateful verified recovery."""
    if not worker.exists():
        raise typer.BadParameter(f"Worker executable not found: {worker}")

    if fail_at >= iterations:
        raise typer.BadParameter(
            "--fail-at must be lower than --iterations."
        )

    checkpoint_store = CheckpointStore(checkpoint_root, run_id)
    controller = ResilienceController()
    final_residual = float("inf")

    def observe_first_run(event: dict[str, Any]) -> None:
        event_type = event.get("event_type")

        if event_type == "checkpoint":
            checkpoint_id = str(event["checkpoint_id"])
            iteration = int(event["iteration"])
            residual = float(event["residual"])
            checksum_valid = bool(event["checksum_valid"])
            state_path = str(event["state_path"])

            stored = checkpoint_store.write(
                checkpoint_id=checkpoint_id,
                iteration=iteration,
                residual=residual,
                checksum_valid=checksum_valid,
                state_path=state_path,
            )

            if checksum_valid:
                console.print(
                    f"[green]Checkpoint stored and validated:[/green] "
                    f"{stored.checkpoint_id}"
                )
            else:
                console.print(
                    f"[red]Checkpoint stored but corrupted:[/red] "
                    f"{stored.checkpoint_id}"
                )

        elif event_type == "fault_injected":
            console.print(
                "[yellow]Fault injected:[/yellow] "
                f"{event['fault_type']} at iteration {event['iteration']}"
            )

    failure_started_at = perf_counter()

    first_run = run_worker(
        worker,
        iterations=iterations,
        checkpoint_interval=checkpoint_interval,
        fail_at=fail_at,
        corrupt_checkpoint_at=corrupt_checkpoint_at,
        checkpoint_directory=checkpoint_store.run_directory,
        on_event=observe_first_run,
    )

    if first_run.return_code != 42:
        console.print(
            "[red]The worker did not terminate with expected fault code 42. "
            f"Observed: {first_run.return_code}[/red]"
        )
        raise typer.Exit(code=first_run.return_code or 1)

    console.print(
        "[yellow]Worker exited with expected fault code 42.[/yellow]"
    )

    controller.detect_incident()
    detection_completed_at = perf_counter()

    controller.isolate_incident()
    isolation_completed_at = perf_counter()

    checkpoint = checkpoint_store.latest_valid()

    if checkpoint is None:
        controller.state_machine.transition_to(RecoveryState.FAILED)
        console.print(
            "[red]No persistent verified checkpoint is available; "
            "recovery failed.[/red]"
        )
        raise typer.Exit(code=2)

    state_file = Path(checkpoint.metadata.state_path)

    if not state_file.exists():
        controller.state_machine.transition_to(RecoveryState.FAILED)
        console.print(
            "[red]Selected checkpoint state file is missing:[/red] "
            f"{state_file}"
        )
        raise typer.Exit(code=2)

    controller.activate_degraded_mode()
    reconfiguration_completed_at = perf_counter()

    console.print(
        "[cyan]Selected persistent verified checkpoint:[/cyan] "
        f"{checkpoint.metadata.checkpoint_id} "
        f"(iteration {checkpoint.metadata.iteration})"
    )
    console.print(
        f"[cyan]Restoring C++ state from:[/cyan] {state_file}"
    )

    def observe_recovery_run(event: dict[str, Any]) -> None:
        nonlocal final_residual

        if event.get("event_type") == "started":
            if bool(event.get("resumed", False)):
                console.print(
                    "[green]Worker resumed from persisted state:[/green] "
                    f"iteration {event['start_iteration']}"
                )

        elif event.get("event_type") == "completed":
            final_residual = float(event["residual"])

    second_run = run_worker(
        worker,
        iterations=iterations,
        checkpoint_interval=checkpoint_interval,
        resume_from=state_file,
        checkpoint_directory=checkpoint_store.run_directory,
        on_event=observe_recovery_run,
    )

    if second_run.return_code != 0:
        controller.state_machine.transition_to(RecoveryState.FAILED)
        console.print(
            f"[red]Recovery worker failed with exit code "
            f"{second_run.return_code}.[/red]"
        )
        raise typer.Exit(code=second_run.return_code)

    controller.restore()
    restoration_completed_at = perf_counter()

    verification_result = controller.verify(
        checkpoint_valid=checkpoint.valid,
        residual=final_residual,
        maximum_residual=residual_threshold,
    )
    verification_completed_at = perf_counter()

    t_detect = detection_completed_at - failure_started_at
    t_isolate = isolation_completed_at - detection_completed_at
    t_reconfigure = reconfiguration_completed_at - isolation_completed_at
    t_restore = restoration_completed_at - reconfiguration_completed_at
    t_verify = verification_completed_at - restoration_completed_at
    safe_recovery_time = (
        t_detect + t_isolate + t_reconfigure + t_restore + t_verify
    )

    console.print()
    console.print(f"Final state: [bold]{controller.state.value}[/bold]")
    console.print(verification_result.message)
    console.print()
    console.print("[bold]Safe recovery timing[/bold]")
    console.print(f"  T_detect:   {t_detect:.6f} s")
    console.print(f"  T_isolate:  {t_isolate:.6f} s")
    console.print(f"  T_reconf:   {t_reconfigure:.6f} s")
    console.print(f"  T_restore:  {t_restore:.6f} s")
    console.print(f"  T_verify:   {t_verify:.6f} s")
    console.print(f"  T_SR:       {safe_recovery_time:.6f} s")

    if controller.state != RecoveryState.VERIFIED:
        raise typer.Exit(code=3)


if __name__ == "__main__":
    app()