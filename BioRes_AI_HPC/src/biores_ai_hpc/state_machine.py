from __future__ import annotations

from enum import Enum


class RecoveryState(str, Enum):
    NOMINAL = "nominal"
    DETECTED = "detected"
    ISOLATED = "isolated"
    DEGRADED = "degraded"
    RESTORED = "restored"
    VERIFIED = "verified"
    UNSAFE = "unsafe"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[RecoveryState, set[RecoveryState]] = {
    RecoveryState.NOMINAL: {
        RecoveryState.DETECTED,
        RecoveryState.FAILED,
    },
    RecoveryState.DETECTED: {
        RecoveryState.ISOLATED,
        RecoveryState.UNSAFE,
        RecoveryState.FAILED,
    },
    RecoveryState.ISOLATED: {
        RecoveryState.DEGRADED,
        RecoveryState.RESTORED,
        RecoveryState.UNSAFE,
        RecoveryState.FAILED,
    },
    RecoveryState.DEGRADED: {
        RecoveryState.RESTORED,
        RecoveryState.UNSAFE,
        RecoveryState.FAILED,
    },
    RecoveryState.RESTORED: {
        RecoveryState.VERIFIED,
        RecoveryState.UNSAFE,
        RecoveryState.FAILED,
    },
    RecoveryState.VERIFIED: {
        RecoveryState.NOMINAL,
        RecoveryState.DETECTED,
        RecoveryState.FAILED,
    },
    RecoveryState.UNSAFE: {
        RecoveryState.ISOLATED,
        RecoveryState.FAILED,
    },
    RecoveryState.FAILED: set(),
}


class InvalidStateTransition(ValueError):
    """Raised when the controller attempts an invalid state transition."""


class RecoveryStateMachine:
    def __init__(self) -> None:
        self._state = RecoveryState.NOMINAL
        self._history: list[RecoveryState] = [self._state]

    @property
    def state(self) -> RecoveryState:
        return self._state

    @property
    def history(self) -> tuple[RecoveryState, ...]:
        return tuple(self._history)

    def transition_to(self, target: RecoveryState) -> None:
        if target not in _ALLOWED_TRANSITIONS[self._state]:
            raise InvalidStateTransition(
                f"Invalid transition: {self._state.value} -> {target.value}"
            )

        self._state = target
        self._history.append(target)