from __future__ import annotations

from secrets import compare_digest

from fastapi import HTTPException, Request, status


def _require_token(*, provided: str | None, expected: str, detail: str) -> None:
    if provided is None or not compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


async def require_admin_token(request: Request) -> None:
    _require_token(
        provided=request.headers.get("X-Admin-Token"),
        expected=request.app.state.settings.admin_token,
        detail="Missing or invalid admin token.",
    )


async def require_service_token(request: Request) -> None:
    _require_token(
        provided=request.headers.get("X-Service-Token"),
        expected=request.app.state.settings.service_token,
        detail="Missing or invalid service token.",
    )
