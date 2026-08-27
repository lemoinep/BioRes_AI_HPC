from biores_ai_hpc.verification import verify_recovery


def test_valid_recovery_is_verified() -> None:
    result = verify_recovery(
        checkpoint_valid=True,
        residual=0.001,
        maximum_residual=0.01,
    )

    assert result.passed
    assert result.checks["checkpoint_integrity"]
    assert result.checks["numerical_residual"]


def test_invalid_checkpoint_is_rejected() -> None:
    result = verify_recovery(
        checkpoint_valid=False,
        residual=0.001,
        maximum_residual=0.01,
    )

    assert not result.passed
    assert not result.checks["checkpoint_integrity"]


def test_large_residual_is_rejected() -> None:
    result = verify_recovery(
        checkpoint_valid=True,
        residual=0.1,
        maximum_residual=0.01,
    )

    assert not result.passed
    assert not result.checks["numerical_residual"]