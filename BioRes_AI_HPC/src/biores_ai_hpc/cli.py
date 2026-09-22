from __future__ import annotations

import json
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Any, Callable

import typer
from rich.console import Console

from biores_ai_hpc.checkpoint_store import CheckpointStore
from biores_ai_hpc.controller import ResilienceController
from biores_ai_hpc.cpp_bridge import run_worker
from biores_ai_hpc.state_machine import RecoveryState

from biores_ai_hpc.telemetry import (
    FaultDomain,
    JsonlEventLogger,
    TelemetryEvent,
)

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

    log_event(
        "state_transition",
        attempt_id=attempt_id,
        state=controller.state.value,
        phase=phase,
    )

    controller.isolate_incident()

    log_event(
        "state_transition",
        attempt_id=attempt_id,
        state=controller.state.value,
        phase=phase,
    )
    controller.activate_degraded_mode()

    log_event(
        "state_transition",
        attempt_id=attempt_id,
        state=controller.state.value,
        phase=phase,
    )

    controller.restore()

    log_event(
        "state_transition",
        attempt_id=attempt_id,
        state=controller.state.value,
        phase=phase,
    )

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


    log_event(
        "state_transition",
        attempt_id=2,
        state=controller.state.value,
        phase="final_verification",
    )


    log_event(
        "run_completed",
        severity=(
            "info"
            if controller.state == RecoveryState.VERIFIED
            else "error"
        ),
        final_state=controller.state.value,
        recovery_count=recovery_count,
        final_checkpoint=(
            latest_checkpoint.metadata.checkpoint_id
            if latest_checkpoint is not None
            else None
        ),
        final_checkpoint_attempt=(
            latest_checkpoint.metadata.attempt_id
            if latest_checkpoint is not None
            else None
        ),
        final_residual=final_residual,
        total_recovery_runtime_s=total_recovery_time,
        total_experiment_time_s=total_elapsed,
        verification_time_s=verification_elapsed,
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
        checkpoint_directory=checkpoint_store.attempt_directory(0),
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

        event_type = event.get("event_type")

        if event_type == "started":
            if bool(event.get("resumed", False)):
                console.print(
                    "[green]Worker resumed from persisted state:[/green] "
                    f"iteration {event['start_iteration']}"
                )

        elif event_type == "checkpoint":
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
                    "[green]Recovery checkpoint stored and validated:[/green] "
                    f"{stored.checkpoint_id}"
                )
            else:
                console.print(
                    "[red]Recovery checkpoint stored but corrupted:[/red] "
                    f"{stored.checkpoint_id}"
                )

        elif event_type == "completed":
            final_residual = float(event["residual"])



   

    second_run = run_worker(
        worker,
        iterations=iterations,
        checkpoint_interval=checkpoint_interval,
        resume_from=state_file,
        checkpoint_directory=checkpoint_store.attempt_directory(2),
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


@app.command(name="run-cascade")
def run_cascade(
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
    first_fail_at: int = typer.Option(
        55,
        min=1,
        help="Iteration of the first injected worker failure.",
    ),
    second_fail_at: int = typer.Option(
        85,
        min=1,
        help="Iteration of the second injected worker failure.",
    ),
     corrupt_recovery_checkpoint_at: int | None = typer.Option(
        None,
        help=(
            "Mark a checkpoint created during the first recovery as "
            "corrupted."
        ),
    ),
    run_id: str = typer.Option(
        "cascade-run",
        help="Identifier used for checkpoint storage.",
    ),
    checkpoint_root: Path = typer.Option(
        Path("results/checkpoints"),
        help="Root directory containing checkpoint artifacts.",
    ),
    residual_threshold: float = typer.Option(
        0.01,
        min=0.0,
        help="Maximum acceptable residual after final recovery.",
    ),
) -> None:
    """Inject two failures and recover from persistent verified checkpoints."""
    if not worker.exists():
        raise typer.BadParameter(f"Worker executable not found: {worker}")

    if first_fail_at >= iterations:
        raise typer.BadParameter(
            "--first-fail-at must be lower than --iterations."
        )

    if second_fail_at >= iterations:
        raise typer.BadParameter(
            "--second-fail-at must be lower than --iterations."
        )

    if second_fail_at <= first_fail_at:
        raise typer.BadParameter(
            "--second-fail-at must be greater than --first-fail-at."
        )

    if (
        corrupt_recovery_checkpoint_at is not None
        and corrupt_recovery_checkpoint_at <= first_fail_at
    ):
        raise typer.BadParameter(
            "--corrupt-recovery-checkpoint-at must be greater than "
            "--first-fail-at."
        )

    if (
        corrupt_recovery_checkpoint_at is not None
        and corrupt_recovery_checkpoint_at >= second_fail_at
    ):
        raise typer.BadParameter(
            "--corrupt-recovery-checkpoint-at must be lower than "
            "--second-fail-at."
        )

    if (
        corrupt_recovery_checkpoint_at is not None
        and corrupt_recovery_checkpoint_at % checkpoint_interval != 0
    ):
        raise typer.BadParameter(
            "--corrupt-recovery-checkpoint-at must match a checkpoint "
            "iteration."
    )

    checkpoint_store = CheckpointStore(checkpoint_root, run_id)
    controller = ResilienceController()
    final_residual = float("inf")
    recovery_count = 0
    total_recovery_time = 0.0

    event_logger = JsonlEventLogger(Path("results/runs"), run_id)

    def log_event(
        event_type: str,
        *,
        source: str = "biores_controller",
        attempt_id: int | None = None,
        domain: FaultDomain | None = None,
        severity: str = "info",
        **payload: Any,
    ) -> None:
        event_logger.write(
            TelemetryEvent(
                event_type=event_type,
                source=source,
                run_id=run_id,
                attempt_id=attempt_id,
                domain=domain,
                severity=severity,
                payload=payload,
            )
        )

    log_event(
        "run_started",
        iterations=iterations,
        checkpoint_interval=checkpoint_interval,
        first_fail_at=first_fail_at,
        second_fail_at=second_fail_at,
        corrupt_recovery_checkpoint_at=corrupt_recovery_checkpoint_at,
    )

    def persist_checkpoint(
        event: dict[str, Any],
        *,
        phase: str,
        attempt_id: int,
    ) -> None:
        checkpoint_id = str(event["checkpoint_id"])
        iteration = int(event["iteration"])
        residual = float(event["residual"])
        checksum_valid = bool(event["checksum_valid"])
        state_path = str(event["state_path"])

        stored = checkpoint_store.write(
            attempt_id=attempt_id,
            checkpoint_id=checkpoint_id,
            iteration=iteration,
            residual=residual,
            checksum_valid=checksum_valid,
            state_path=state_path,
        )

        log_event(
            "checkpoint_persisted",
            source="biores_controller",
            attempt_id=attempt_id,
            severity="info" if checksum_valid else "warning",
            checkpoint_id=stored.checkpoint_id,
            iteration=iteration,
            residual=residual,
            checksum_valid=checksum_valid,
            state_path=state_path,
            phase=phase,
        )

        color = "green" if checksum_valid else "red"
        status = "validated" if checksum_valid else "corrupted"

        console.print(
            f"[{color}]{phase} checkpoint {status}:[/{color}] "
            f"{stored.checkpoint_id}"
        )

    def observe_initial_run(event: dict[str, Any]) -> None:
        event_type = event.get("event_type")

        

        if event_type == "checkpoint":
            persist_checkpoint(
                event,
                phase="Initial",
                attempt_id=0,
            )

        elif event_type == "fault_injected":
            console.print(
                "[yellow]First fault injected:[/yellow] "
                f"{event['fault_type']} at iteration {event['iteration']}"
            )

            log_event(
                "fault_injected",
                source="biores_worker",
                attempt_id=0,
                domain=FaultDomain.INFRASTRUCTURE,
                severity="high",
                phase="initial",
                iteration=int(event["iteration"]),
                fault_type=str(event["fault_type"]),
            )

    def observe_first_recovery(event: dict[str, Any]) -> None:
        event_type = event.get("event_type")

        

        if event_type == "started" and bool(event.get("resumed", False)):
            console.print(
                "[green]First recovery resumed from state:[/green] "
                f"iteration {event['start_iteration']}"
            )

        elif event_type == "checkpoint":
             persist_checkpoint(
                event,
                phase="First recovery",
                attempt_id=1,
            )

        elif event_type == "fault_injected":
            console.print(
                "[yellow]Second fault injected:[/yellow] "
                f"{event['fault_type']} at iteration {event['iteration']}"
            )

            log_event(
                "fault_injected",
                source="biores_worker",
                attempt_id=1,
                domain=FaultDomain.INFRASTRUCTURE,
                severity="high",
                phase="first_recovery",
                iteration=int(event["iteration"]),
                fault_type=str(event["fault_type"]),
            )

    def observe_second_recovery(event: dict[str, Any]) -> None:
        nonlocal final_residual

        event_type = event.get("event_type")

        if event_type == "started" and bool(event.get("resumed", False)):
            console.print(
                "[green]Second recovery resumed from state:[/green] "
                f"iteration {event['start_iteration']}"
            )

        elif event_type == "checkpoint":
            persist_checkpoint(
                event,
                phase="Second recovery",
                attempt_id=2,
            )

        elif event_type == "completed":
            final_residual = float(event["residual"])

    def recover_from_latest_checkpoint(
        *,
        phase: str,
        observer: Callable[[dict[str, Any]], None],
        fail_at: int | None,
        corrupt_checkpoint_at: int | None = None,
        attempt_id: int,
    ) -> bool:
        nonlocal recovery_count, total_recovery_time

        controller.detect_incident()

        log_event(
            "state_transition",
            attempt_id=attempt_id,
            phase=phase,
            state=controller.state.value,
        )

        controller.isolate_incident()

        log_event(
            "state_transition",
            attempt_id=attempt_id,
            phase=phase,
            state=controller.state.value,
        )

        checkpoint = checkpoint_store.latest_valid()

        if checkpoint is None:
            controller.state_machine.transition_to(RecoveryState.FAILED)
            console.print(
                f"[red]{phase}: no persistent verified checkpoint is "
                "available.[/red]"
            )
            return False

        state_file = Path(checkpoint.metadata.state_path)

        if not state_file.exists():
            controller.state_machine.transition_to(RecoveryState.FAILED)
            console.print(
                f"[red]{phase}: checkpoint state file is missing: "
                f"{state_file}[/red]"
            )
            return False

        controller.activate_degraded_mode()

        log_event(
            "state_transition",
            attempt_id=attempt_id,
            phase=phase,
            state=controller.state.value,
        )

        console.print(
            f"[cyan]{phase}: selected checkpoint:[/cyan] "
            f"{checkpoint.metadata.checkpoint_id} "
            f"(iteration {checkpoint.metadata.iteration})"
        )

        log_event(
            "checkpoint_selected",
            attempt_id=attempt_id,
            severity="info",
            phase=phase,
            checkpoint_id=checkpoint.metadata.checkpoint_id,
            checkpoint_attempt_id=checkpoint.metadata.attempt_id,
            iteration=checkpoint.metadata.iteration,
            residual=checkpoint.metadata.residual,
            state_path=checkpoint.metadata.state_path,
        )


        controller.restore()

        log_event(
            "state_transition",
            attempt_id=attempt_id,
            phase=phase,
            state=controller.state.value,
        )


        recovery_started_at = perf_counter()

        result = run_worker(
            worker,
            iterations=iterations,
            checkpoint_interval=checkpoint_interval,
            fail_at=fail_at,
            corrupt_checkpoint_at=corrupt_checkpoint_at,
            resume_from=state_file,
            checkpoint_directory=checkpoint_store.attempt_directory(attempt_id),
            on_event=observer,
        )

        recovery_elapsed = perf_counter() - recovery_started_at
        total_recovery_time += recovery_elapsed
        recovery_count += 1

        if fail_at is None:
            if result.return_code != 0:
                controller.state_machine.transition_to(RecoveryState.FAILED)
                console.print(
                    f"[red]{phase}: final recovery worker failed with "
                    f"exit code {result.return_code}.[/red]"
                )
                return False
            return True

        if result.return_code != 42:
            controller.state_machine.transition_to(RecoveryState.FAILED)
            console.print(
                f"[red]{phase}: expected fault code 42, observed "
                f"{result.return_code}.[/red]"
            )
            return False

        console.print(
            f"[yellow]{phase}: worker exited with expected fault "
            "code 42.[/yellow]"
        )
        return True

    experiment_started_at = perf_counter()

    initial_run = run_worker(
        worker,
        iterations=iterations,
        checkpoint_interval=checkpoint_interval,
        fail_at=first_fail_at,
        checkpoint_directory=checkpoint_store.attempt_directory(0),
        on_event=observe_initial_run,
    )

    if initial_run.return_code != 42:
        console.print(
            "[red]Initial run did not terminate with expected fault code 42. "
            f"Observed: {initial_run.return_code}[/red]"
        )
        raise typer.Exit(code=initial_run.return_code or 1)

    console.print(
        "[yellow]Initial worker exited with expected fault code 42.[/yellow]"
    )

    if not recover_from_latest_checkpoint(
        phase="First recovery",
        observer=observe_first_recovery,
        fail_at=second_fail_at,
        corrupt_checkpoint_at=corrupt_recovery_checkpoint_at,
        attempt_id=1,
    ):
        raise typer.Exit(code=2)

    if not recover_from_latest_checkpoint(
        phase="Second recovery",
        observer=observe_second_recovery,
        fail_at=None,
        corrupt_checkpoint_at=None,
        attempt_id=2,
    ):
        raise typer.Exit(code=2)

    verification_started_at = perf_counter()

    latest_checkpoint = checkpoint_store.latest_valid()
    checkpoint_valid = latest_checkpoint is not None

    verification_result = controller.verify(
        checkpoint_valid=checkpoint_valid,
        residual=final_residual,
        maximum_residual=residual_threshold,
    )


    verification_elapsed = perf_counter() - verification_started_at
    total_elapsed = perf_counter() - experiment_started_at

    log_event(
        "state_transition",
        attempt_id=2,
        phase="final_verification",
        state=controller.state.value,
    )

    log_event(
        "run_completed",
        severity=(
            "info"
            if controller.state == RecoveryState.VERIFIED
            else "error"
        ),
        final_state=controller.state.value,
        recovery_count=recovery_count,
        final_checkpoint=(
            latest_checkpoint.metadata.checkpoint_id
            if latest_checkpoint is not None
            else None
        ),
        final_checkpoint_attempt=(
            latest_checkpoint.metadata.attempt_id
            if latest_checkpoint is not None
            else None
        ),
        final_residual=final_residual,
        total_recovery_runtime_s=total_recovery_time,
        total_experiment_time_s=total_elapsed,
        verification_time_s=verification_elapsed,
    )





    console.print()
    console.print(f"Final state: [bold]{controller.state.value}[/bold]")
    console.print(verification_result.message)
    console.print()
    console.print("[bold]Cascade recovery summary[/bold]")
    console.print(f"  Recoveries attempted: {recovery_count}")
    console.print(f"  Final checkpoint: {latest_checkpoint.metadata.checkpoint_id if latest_checkpoint else 'none'}")
    console.print(f"  Total recovery runtime: {total_recovery_time:.6f} s")
    console.print(f"  Final verification time: {verification_elapsed:.6f} s")
    console.print(f"  Total experiment time: {total_elapsed:.6f} s")

    if controller.state != RecoveryState.VERIFIED:
        raise typer.Exit(code=3)

if __name__ == "__main__":
    app()