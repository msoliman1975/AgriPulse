"""One-off dev helper: create a 20m grid config for a block.

Calls GridService directly against the dev DB so we don't need to
mint a JWT just to PUT one config row.

Usage:
  python -m scripts.dev_setup_grid <tenant_schema> <block_uuid> <product_uuid> <cell_size_m>
"""

import asyncio
import sys
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import get_settings
from app.modules.grid.service import get_grid_service


async def main(tenant_schema: str, block_id: UUID, product_id: UUID, cell_size_m: float) -> None:
    url = str(get_settings().database_url).replace("postgresql://", "postgresql+psycopg://")
    engine = create_async_engine(url, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {tenant_schema}, public"))
        svc = get_grid_service(tenant_session=session)
        from decimal import Decimal

        cfg = await svc.upsert_config(
            block_id=block_id,
            product_id=product_id,
            cell_size_m=Decimal(str(cell_size_m)),
            created_by=None,
        )
        print(
            f"created grid_config id={cfg.id} cells={cfg.cell_count} cell_size={cfg.cell_size_m}m"
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], UUID(sys.argv[2]), UUID(sys.argv[3]), float(sys.argv[4])))
