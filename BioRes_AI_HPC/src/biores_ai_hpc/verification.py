from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    checks: dict[str, bool]
    message: str


def verify_recovery(
    checkpoint_valid: bool,
    residual: float,
    maximum_residual: float,
) -> VerificationResult:
    residual_valid = residual <= maximum_residual

    checks = {
        "checkpoint_integrity": checkpoint_valid,
        "numerical_residual": residual_valid,
    }

    passed = all(checks.values())

    if passed:
        message = "Recovered state satisfies integrity and numerical checks."
    else:
        failed_checks = [name for name, status in checks.items() if not status]
        message = f"Recovery verification failed: {', '.join(failed_checks)}."

    return VerificationResult(
        passed=passed,
        checks=checks,
        message=message,
    )