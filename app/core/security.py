from __future__ import annotations

from secrets import compare_digest

from fastapi import HTTPException, Request, status


async def require_admin_token(request: Request) -> None:
    provided = request.headers.get("X-Admin-Token")
    expected = request.app.state.settings.admin_token

    if provided is None or not compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid admin token.",
        )

