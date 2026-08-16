"""Pure, framework-independent event validation rules."""

from app.config import VALID_RISK_SIGNALS


class InvalidRiskSignalError(ValueError):
    pass


def normalize_risk_signal(raw: str) -> str:
    """Normalize risk_signal casing/whitespace and validate against the closed set.

    Raises InvalidRiskSignalError if raw does not map to one of
    VALID_RISK_SIGNALS once lowercased and trimmed.
    """
    normalized = raw.strip().lower()
    if normalized not in VALID_RISK_SIGNALS:
        raise InvalidRiskSignalError(
            f"risk_signal must be one of {sorted(VALID_RISK_SIGNALS)}, got {raw!r}"
        )
    return normalized
