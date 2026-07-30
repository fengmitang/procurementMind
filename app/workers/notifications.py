import asyncio

from app.db.session import async_session_factory, engine
from app.services.notifications import NotificationService


async def run_once() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            result = await NotificationService().dispatch_due(session)
    print(
        "notification dispatch:",
        f"claimed={result.claimed}",
        f"sent={result.sent}",
        f"failed={result.failed}",
        f"exhausted={result.exhausted}",
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_once())
