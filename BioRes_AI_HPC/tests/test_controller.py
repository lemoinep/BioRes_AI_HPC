from biores_ai_hpc.controller import ResilienceController
from biores_ai_hpc.state_machine import RecoveryState


def test_rejected_verification_marks_restored_state_unsafe() -> None:
    controller = ResilienceController()

    controller.detect_incident()
    controller.isolate_incident()
    controller.activate_degraded_mode()
    controller.restore()

    result = controller.verify(
        checkpoint_valid=True,
        residual=0.02,
        maximum_residual=0.01,
    )

    assert result.passed is False
    assert result.checks["numerical_residual"] is False
    assert controller.state == RecoveryState.UNSAFE
    assert controller.timing.verified_at is None
    assert controller.timing.safe_recovery_time() is None