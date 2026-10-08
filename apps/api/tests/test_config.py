"""Startup safety checks for the runtime, not behaviour that happens later.

The things here are settings whose insecure defaults are convenient in
development and catastrophic in production. They are only ever checked at
startup, so they are tested directly rather than through some request.
"""

from __future__ import annotations

import pytest
from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    """A production settings object with the given values overridden."""
    base = {
        "environment": "production",
        "secret_key": "a" * 50,
        "cookie_secure": True,
        "cookie_name": "studyos_session",
        "cors_origins": "https://studyos.app",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"secret_key": "change-me-in-production"}, "placeholder or shorter than 32 characters"),
        ({"secret_key": "x" * 16}, "placeholder or shorter than 32 characters"),
        ({"cookie_secure": False}, "COOKIE_SECURE is false"),
        ({"cors_origins": "*"}, "CORS_ORIGINS contains"),
        ({"cookie_name": "session"}, "invites a fixation attack"),
    ],
)
def test_validate_for_startup_refuses_unsafe_production_config(
    overrides: dict[str, object], needle: str
) -> None:
    with pytest.raises(RuntimeError, match=needle):
        _settings(**overrides).validate_for_startup()


def test_validate_for_startup_refuses_an_unset_secret_key() -> None:
    with pytest.raises(RuntimeError, match="SECRET_KEY is unset"):
        _settings().model_copy(update={"secret_key": ""}).validate_for_startup()


def test_validate_for_startup_passes_a_sound_production_config() -> None:
    _settings().validate_for_startup()


def test_validate_for_startup_is_silent_outside_production() -> None:
    settings = _settings(environment="development", cookie_secure=False).model_copy(
        update={"secret_key": ""}
    )
    settings.validate_for_startup()