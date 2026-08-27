import pytest

from biores_ai_hpc.state_machine import (
    InvalidStateTransition,
    RecoveryState,
    RecoveryStateMachine,
)


def test_nominal_recovery_path() -> None:
    machine = RecoveryStateMachine()

    machine.transition_to(RecoveryState.DETECTED)
    machine.transition_to(RecoveryState.ISOLATED)
    machine.transition_to(RecoveryState.DEGRADED)
    machine.transition_to(RecoveryState.RESTORED)
    machine.transition_to(RecoveryState.VERIFIED)

    assert machine.state == RecoveryState.VERIFIED


def test_restored_is_not_automatically_verified() -> None:
    machine = RecoveryStateMachine()

    machine.transition_to(RecoveryState.DETECTED)
    machine.transition_to(RecoveryState.ISOLATED)
    machine.transition_to(RecoveryState.RESTORED)

    assert machine.state == RecoveryState.RESTORED


def test_invalid_transition_is_rejected() -> None:
    machine = RecoveryStateMachine()

    with pytest.raises(InvalidStateTransition):
        machine.transition_to(RecoveryState.VERIFIED)