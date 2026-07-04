from pathlib import Path
import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.connection: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = await aiosqlite.connect(self.path)

        await self.connection.execute("PRAGMA foreign_keys = ON")
        await self.connection.execute("PRAGMA journal_mode = WAL")
        await self.connection.commit()

        return self.connection

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None