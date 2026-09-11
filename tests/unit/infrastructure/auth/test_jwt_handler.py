"""JWT constructor owns protected claims."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jose import jwt

from app.infrastructure.auth.jwt_handler import PROTECTED_TOKEN_CLAIMS, JWTHandler


def test_additional_claims_cannot_overwrite_protected_fields() -> None:
    handler = JWTHandler(secret_key="unit-test-secret-key-which-is-long-enough")
    user_id = uuid4()
    token = handler.create_access_token(
        user_id,
        additional_claims={
            "exp": datetime(1999, 1, 1, tzinfo=UTC),
            "type": "password_reset",
            "sub": "attacker",
            "iat": datetime(1999, 1, 1, tzinfo=UTC),
            "nbf": datetime(1999, 1, 1, tzinfo=UTC),
            "role": "admin",
        },
        token_type="access",
        expires_delta=timedelta(minutes=15),
    )
    payload = jwt.decode(token, handler.secret_key, algorithms=[handler.algorithm])
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"
    exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
    assert exp.year >= datetime.now(UTC).year
    assert payload.get("role") == "admin"
    for claim in PROTECTED_TOKEN_CLAIMS:
        if claim == "nbf":
            continue
        assert payload[claim] != "attacker"


def test_password_reset_type_is_constructor_owned() -> None:
    handler = JWTHandler(secret_key="unit-test-secret-key-which-is-long-enough")
    user_id = uuid4()
    token = handler.create_access_token(
        user_id,
        additional_claims={"type": "access"},
        token_type="password_reset",
        expires_delta=timedelta(minutes=15),
    )
    assert handler.verify_token(token, token_type="password_reset") == user_id
    assert handler.verify_token(token, token_type="access") is None
