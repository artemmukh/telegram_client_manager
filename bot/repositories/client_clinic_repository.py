import aiosqlite


class ClientClinicRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self) -> None:
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS client_clinics(
                client_id INTEGER NOT NULL,
                clinic_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (client_id, clinic_id),
                FOREIGN KEY(client_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE
            )
        """)

        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_client_clinics_clinic_id
            ON client_clinics(clinic_id)
        """)

        # Backfill: for every existing client (role='client') with a clinic_id,
        # ensure a corresponding link row exists (their "home" clinic).
        await self.connection.execute("""
            INSERT OR IGNORE INTO client_clinics (client_id, clinic_id)
            SELECT id, clinic_id FROM users
            WHERE role = 'client' AND clinic_id IS NOT NULL
        """)

        await self.connection.commit()

    async def link_client_to_clinic(self, client_id: int, clinic_id: int) -> None:
        await self.connection.execute(
            "INSERT OR IGNORE INTO client_clinics (client_id, clinic_id) VALUES (?, ?)",
            (client_id, clinic_id),
        )
        await self.connection.commit()

    async def client_linked_to_clinic(self, client_id: int, clinic_id: int) -> bool:
        cursor = await self.connection.execute(
            "SELECT 1 FROM client_clinics WHERE client_id = ? AND clinic_id = ?",
            (client_id, clinic_id),
        )
        return await cursor.fetchone() is not None

    async def unlink_client_from_clinic(self, client_id: int, clinic_id: int) -> None:
        await self.connection.execute(
            "DELETE FROM client_clinics WHERE client_id = ? AND clinic_id = ?",
            (client_id, clinic_id),
        )
        await self.connection.commit()

    async def get_client_clinic_ids(self, client_id: int) -> list[int]:
        cursor = await self.connection.execute(
            "SELECT clinic_id FROM client_clinics WHERE client_id = ?",
            (client_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
