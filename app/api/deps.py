from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings


def require_ingest_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.ingest_token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.ingest_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")


def get_cors_origins() -> list[str]:
    return get_settings().cors_origins
