from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.gateway_auth import verify_gateway_identity
from app.db.session import get_db_session
from app.domain.identity import CurrentUser
from app.services.identity import IdentityService

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_user(
    request: Request,
    session: DbSession,
) -> CurrentUser:
    gateway_identity = await verify_gateway_identity(request, get_settings())
    return await IdentityService().resolve_current_user(session, gateway_identity)


CurrentUserDependency = Annotated[CurrentUser, Depends(get_current_user)]
