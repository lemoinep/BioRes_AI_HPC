from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from biores_ai_hpc.state_machine import (
    RecoveryState,
    RecoveryStateMachine,
)
from biores_ai_hpc.verification import VerificationResult, verify_recovery


@dataclass
class RecoveryTiming:
    detected_at: float | None = None
    isolated_at: float | None = None
    degraded_at: float | None = None
    restored_at: float | None = None
    verified_at: float | None = None

    def safe_recovery_time(self) -> float | None:
        if self.detected_at is None or self.verified_at is None:
            return None
        return self.verified_at - self.detected_at


@dataclass
class ResilienceController:
    state_machine: RecoveryStateMachine = field(
        default_factory=RecoveryStateMachine
    )
    timing: RecoveryTiming = field(default_factory=RecoveryTiming)

    @property
    def state(self) -> RecoveryState:
        return self.state_machine.state

    def detect_incident(self) -> None:
        self.state_machine.transition_to(RecoveryState.DETECTED)
        self.timing.detected_at = perf_counter()

    def isolate_incident(self) -> None:
        self.state_machine.transition_to(RecoveryState.ISOLATED)
        self.timing.isolated_at = perf_counter()

    def activate_degraded_mode(self) -> None:
        self.state_machine.transition_to(RecoveryState.DEGRADED)
        self.timing.degraded_at = perf_counter()

    def restore(self) -> None:
        self.state_machine.transition_to(RecoveryState.RESTORED)
        self.timing.restored_at = perf_counter()

    def verify(
        self,
        checkpoint_valid: bool,
        residual: float,
        maximum_residual: float,
    ) -> VerificationResult:
        result = verify_recovery(
            checkpoint_valid=checkpoint_valid,
            residual=residual,
            maximum_residual=maximum_residual,
        )

        if result.passed:
            self.state_machine.transition_to(RecoveryState.VERIFIED)
            self.timing.verified_at = perf_counter()
        else:
            self.state_machine.transition_to(RecoveryState.UNSAFE)

        return result