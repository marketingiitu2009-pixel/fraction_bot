import aiosqlite

DB_NAME = "bot_database.db"
FACTIONS = ["Афины", "Спарта", "Итака", "Родос"]


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                faction TEXT,
                xp INTEGER DEFAULT 0,
                gold INTEGER DEFAULT 0
            )
            """
        )

        cursor = await db.execute("PRAGMA table_info(quests)")
        columns = [row[1] for row in await cursor.fetchall()]
        if columns and "target_type" not in columns:
            await db.execute("DROP TABLE quests")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                reward_xp INTEGER DEFAULT 0,
                reward_gold INTEGER DEFAULT 0,
                target_type TEXT,
                target_value TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, username, faction, xp, gold FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            return await cursor.fetchone()


async def register_user(user_id: int, username: str, faction: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, faction, xp, gold) VALUES (?, ?, ?, 0, 0)",
            (user_id, username, faction),
        )
        await db.commit()


async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, username, faction, xp, gold FROM users ORDER BY faction, username"
        ) as cursor:
            return await cursor.fetchall()


async def get_users_by_faction(faction: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, username, faction, xp, gold FROM users WHERE faction = ?",
            (faction,),
        ) as cursor:
            return await cursor.fetchall()


async def set_user_faction(user_id: int, faction: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET faction = ? WHERE user_id = ?",
            (faction, user_id),
        )
        await db.commit()


async def add_xp_gold(user_id: int, xp: int, gold: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET xp = xp + ?, gold = gold + ? WHERE user_id = ?",
            (xp, gold, user_id),
        )
        await db.commit()


async def create_quest(title: str, reward_xp: int, reward_gold: int, target_type: str, target_value: str) -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            INSERT INTO quests (title, reward_xp, reward_gold, target_type, target_value, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (title, reward_xp, reward_gold, target_type, target_value),
        )
        await db.commit()
        return cursor.lastrowid


async def get_active_quests_for_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, title, reward_xp, reward_gold, target_type, target_value, status, created_at "
            "FROM quests WHERE target_type = 'user' AND target_value = ? AND status = 'active' "
            "ORDER BY id DESC",
            (str(user_id),),
        ) as cursor:
            return await cursor.fetchall()


async def get_active_quests_for_faction(faction: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, title, reward_xp, reward_gold, target_type, target_value, status, created_at "
            "FROM quests WHERE target_type = 'faction' AND target_value = ? AND status = 'active' "
            "ORDER BY id DESC",
            (faction,),
        ) as cursor:
            return await cursor.fetchall()


async def get_all_active_quests():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, title, reward_xp, reward_gold, target_type, target_value, status, created_at "
            "FROM quests WHERE status = 'active' ORDER BY id DESC"
        ) as cursor:
            return await cursor.fetchall()


async def get_quest(quest_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, title, reward_xp, reward_gold, target_type, target_value, status, created_at "
            "FROM quests WHERE id = ?",
            (quest_id,),
        ) as cursor:
            return await cursor.fetchone()


async def complete_quest(quest_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE quests SET status = 'completed' WHERE id = ?", (quest_id,))
        await db.commit()
