from __future__ import annotations

import datetime
import json
import sqlite3
import typing
from types import TracebackType

import asqlite
import asyncpg

T = typing.TypeVar('T', asyncpg.Pool, asqlite.Pool, covariant=True)
TReturn = typing.TypeVar('TReturn', asyncpg.Record, sqlite3.Row, covariant=True)


class DbRecord(typing.Generic[T]):
    def __init__(self, data: T) -> None:
        self.data: T = data

    def __getattr__(self, item):
        return self.data[item]

    def __getitem__(self, item):
        return self.data[item]


C = typing.TypeVar('C')


class DbManager(typing.Generic[T]):
    def __init__(self, dsn: str) -> None:
        self.pool: T | None = None
        self.dsn: str = dsn

    def wrap_or_none(self, data: TReturn | None, cls: type[C] | None = None) -> DbRecord[TReturn] | None:  # noqa
        if data is None:
            return

        if cls is not None:
            return cls(DbRecord(data))
        return DbRecord(data)

    async def fetch_emojis(self) -> list[EmojiCustomDb]:
        pass

    async def fetch_emoji(self, emoji_id: int) -> EmojiCustomDb | None:
        pass

    async def fetch_latest_normal_emoji(self) -> DbRecord:
        pass

    async def create_user(self, user_id: int) -> DbRecord:
        pass

    async def create_emoji(self, emoji_id: int, fullname: str, added_by: datetime.datetime,
                           image_hash: str) -> EmojiCustomDb:
        pass

    async def create_normal_emojis(self, data: dict[str, str]):
        pass

    async def upsert_emoji_usage(self, emoji_id: int, user_id: int, amount: int) -> EmojiUsageDb:
        pass

    async def update_emoji_hash(self, emoji_id: int, hash: str) -> EmojiCustomDb:
        pass

    async def bulk_remove_emojis(self, emojis_id: list[int]) -> None:
        pass

    async def init_database(self) -> None:
        raise NotImplemented("Implement init_database please")

    async def create_pool(self) -> T:
        raise NotImplemented("Implement a pool please")

    async def __aenter__(self) -> typing.Self:
        self.pool = await self.create_pool()
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
    ) -> None:
        await self.pool.close()


class DbPostgres(DbManager[asyncpg.Pool]):
    async def create_pool(self) -> asyncpg.Pool:
        return await asyncpg.create_pool(self.dsn)

    async def init_database(self):
        sqlite_setup = "postgres-setup.sql"
        with open(sqlite_setup, 'r') as file:
            sql = file.read()

        sql_statements = [cleaned for stmt in sql.split(';') if (cleaned := stmt.strip())]
        for stmt in sql_statements:
            await self.pool.execute(stmt)

    async def fetch_user_usages(self, user_id: int) -> list[EmojiUsageDb]:
        records = await self.pool.fetch("SELECT * FROM emoji_used WHERE user_id=$1", user_id)
        return [EmojiUsageDb(record) for record in map(DbRecord, records)]

    async def fetch_emojis(self) -> list[EmojiCustomDb]:
        emojis_records = await self.pool.fetch("SELECT * FROM emoji")
        return [EmojiCustomDb(record) for record in map(DbRecord, emojis_records)]

    async def fetch_emoji(self, emoji_id: int) -> DbRecord[asyncpg.Record] | None:
        data = await self.pool.fetchrow("SELECT * FROM emoji WHERE id=$1", emoji_id)
        return self.wrap_or_none(data, cls=EmojiCustomDb)

    async def fetch_latest_normal_emoji(self) -> DbRecord | None:
        last_data = await self.pool.fetchrow("SELECT * FROM discord_normal_emojis ORDER BY fetched_at DESC LIMIT 1")
        return self.wrap_or_none(last_data)

    async def create_user(self, user_id: int) -> DbRecord | None:
        data = await self.pool.fetchrow(
            "INSERT INTO discord_user(id) VALUES($1) "
            "ON CONFLICT(id) "
            "DO NOTHING RETURNING *", user_id
        )
        return self.wrap_or_none(data, cls=UserDb)

    async def create_emoji(self, emoji_id: int, fullname: str, added_by: datetime.datetime,
                           image_hash: str) -> EmojiCustomDb:
        data = await self.pool.fetchrow(
            "INSERT INTO emoji(id, fullname, added_by, hash) VALUES($1, $2, $3, $4) ON CONFLICT(id) "
            "DO NOTHING RETURNING *",
            emoji_id, fullname, added_by, image_hash
        )
        return self.wrap_or_none(data, cls=EmojiCustomDb)

    async def create_normal_emojis(self, data: dict[str, str]) -> None:
        await self.pool.execute("INSERT INTO discord_normal_emojis(json_data) VALUES($1)", json.dumps(data))

    async def upsert_emoji_usage(self, emoji_id: int, user_id: int, amount: int) -> DbRecord[asyncpg.Record]:
        data = await self.pool.fetchrow(
            """
            INSERT INTO emoji_used (emoji_id, user_id, amount)
            VALUES ($1, $2, $3)
            ON CONFLICT (emoji_id, user_id)
            DO UPDATE SET amount = emoji_used.amount + $3
            RETURNING *
            """,
            emoji_id, user_id, amount
        )
        return self.wrap_or_none(data, cls=EmojiUsageDb)

    async def update_emoji_hash(self, emoji_id: int, image_hash: str):
        await self.pool.execute("UPDATE emoji SET hash=$2 WHERE id=$1", emoji_id, image_hash)

    async def bulk_remove_emojis(self, emoji_ids: list[int]):
        await self.pool.executemany("DELETE FROM emoji WHERE id=$1", [[x] for x in emoji_ids])

    async def create_emoji_favourite(self, emoji_id: int, user_id: int) -> None:
        await self.pool.execute(
            "INSERT INTO emoji_favourite(emoji_id, user_id) VALUES($1, $2)", emoji_id, user_id
        )

    async def remove_emoji_favourite(self, emoji_id: int, user_id: int) -> None:
        await self.pool.execute(
            "DELETE FROM emoji_favourite WHERE user_id=$1 AND emoji_id=$2", user_id, emoji_id
        )

    async def bulk_update_emoji_names(self, values: list[tuple[int, str]]):
        await self.pool.executemany("UPDATE emoji SET fullname=$2 WHERE id=$1", values)

    async def list_emoji_favourite(self, user_id: int) -> list[EmojiFavouriteDb]:
        records = await self.pool.fetch("SELECT * FROM emoji_favourite WHERE user_id=$1", user_id)
        return [self.wrap_or_none(record, cls=EmojiFavouriteDb) for record in records]

    async def fetch_metadata(self, version: str) -> MetadataDb:
        record = await self.pool.fetchrow(
            "INSERT INTO bot_metadata(bot_version, data) VALUES($1, $2) "
            "ON CONFLICT (bot_version) DO UPDATE SET "
            "bot_version=EXCLUDED.bot_version RETURNING *", version, "{}")
        return self.wrap_or_none(record, cls=MetadataDb)

    async def update_metadata(self, id: int, data: dict[str, typing.Any]) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE bot_metadata SET data=$2 WHERE id=$1", id, json.dumps(data))


SQLITE_RECORD = DbRecord[dict[str, typing.Any]]


class DbSqlite(DbManager[asqlite.Pool]):
    _emoji_keys = ['id', 'fullname', 'added_by', 'hash']

    def _sqlite_datetime(self, data: int) -> datetime.datetime:
        return datetime.datetime.fromisoformat(data).replace(tzinfo=datetime.timezone.utc)

    def stmt_star(self, stmt: str, keys: list[str]) -> str:
        return stmt.replace('*', ','.join([key if isinstance(key, str) else key[0] for key in keys]))

    def wrap_key_or_none(self, data: SQLITE_RECORD | None, keys: list[str | tuple[str, typing.Callable]],
                         cls: type[C] | None = None) -> C | None:
        if data is not None:
            return super().wrap_or_none(dict(
                (key[0], key[1](d)) if isinstance(key, tuple) else (key, d)
                for key, d in zip(keys, data)
            ), cls=cls)

    async def create_pool(self) -> asqlite.Pool:
        return await asqlite.create_pool(self.dsn)

    async def init_database(self) -> None:
        sqlite_setup = "sqlite-setup.sql"
        with open(sqlite_setup, 'r') as file:
            sql = file.read()

        async with self.pool.acquire() as conn:
            await conn.executescript(sql)

    async def fetch_user_usages(self, user_id: int) -> list[EmojiUsageDb]:
        keys = EmojiUsageDb.__slots__
        async with self.pool.acquire() as conn:
            stmt = self.stmt_star("SELECT * FROM emoji_used WHERE user_id=?", keys)
            records = await conn.fetchall(stmt, (user_id,))

        return [self.wrap_key_or_none(record, keys, cls=EmojiUsageDb) for record in records]

    async def fetch_emojis(self) -> list[EmojiCustomDb]:
        async with self.pool.acquire() as conn:
            emojis_records = await conn.fetchall(self.stmt_star(f"SELECT * FROM emoji", EmojiCustomDb.__slots__))

        return [self.wrap_key_or_none(record, EmojiCustomDb.__slots__, cls=EmojiCustomDb) for record in emojis_records]

    async def fetch_emoji(self, emoji_id: int) -> EmojiCustomDb | None:
        async with self.pool.acquire() as conn:
            stmt = self.stmt_star(f"SELECT * FROM emoji WHERE id=?", self._emoji_keys)
            data = await conn.fetchone(stmt, (emoji_id,))

        return self.wrap_key_or_none(data, EmojiCustomDb.__slots__, cls=EmojiCustomDb)

    async def fetch_metadata(self, version: str) -> MetadataDb:
        keys = [
            'id', ('data', lambda data: json.loads(data)),
            'bot_version',
            ('created_at', self._sqlite_datetime)
        ]
        async with self.pool.acquire() as conn:
            stmt = (
                "INSERT INTO bot_metadata(bot_version, data) VALUES(?, ?) "
                "ON CONFLICT (bot_version) DO NOTHING"
            )
            await conn.execute(stmt, version, "{}")
            stmt = self.stmt_star("SELECT * FROM bot_metadata WHERE bot_version=?", keys)
            data = await conn.fetchone(stmt, (version,))
            return self.wrap_key_or_none(data, keys, cls=MetadataDb)

    async def update_metadata(self, id: int, data: dict[str, typing.Any]) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE bot_metadata SET data=? WHERE id=?", (json.dumps(data), id))

    async def fetch_latest_normal_emoji(self) -> SQLITE_RECORD | None:
        keys = [
            'id', 'json_data',
            ('fetched_at', self._sqlite_datetime)
        ]
        async with self.pool.acquire() as conn:
            stmt = self.stmt_star(
                "SELECT * FROM discord_normal_emojis "
                "ORDER BY fetched_at "
                "DESC LIMIT 1", keys
            )
            last_data = await conn.fetchone(stmt)
        return self.wrap_key_or_none(last_data, keys)

    async def create_user(self, user_id: int) -> UserDb:
        keys = UserDb.__slots__
        async with self.pool.acquire() as conn:
            value = user_id,
            await conn.execute(
                "INSERT INTO discord_user(id) VALUES(?) "
                "ON CONFLICT(id) "
                f"DO NOTHING", value
            )
            data = await conn.fetchone(self.stmt_star("SELECT * FROM discord_user WHERE id=?", keys), value)
        return self.wrap_key_or_none(data, keys, cls=UserDb)

    async def create_emoji(self, emoji_id: int, fullname: str, added_by: int, image_hash: str) -> EmojiCustomDb:
        stmt = (
            "INSERT INTO emoji(id, fullname, added_by, hash) VALUES(?, ?, ?, ?) ON CONFLICT(id) "
            "DO NOTHING"
        )
        keys = EmojiCustomDb.__slots__
        async with self.pool.acquire() as conn:
            await conn.execute(stmt, (emoji_id, fullname, added_by, image_hash))
            get_stmt = self.stmt_star("SELECT * FROM emoji WHERE id=?", keys)
            data = await conn.fetchone(get_stmt, (emoji_id,))
        return self.wrap_key_or_none(data, keys, cls=EmojiCustomDb)

    async def create_normal_emojis(self, data: dict[str, str]) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO discord_normal_emojis(json_data) VALUES(?)", json.dumps(data))

    async def create_emoji_favourite(self, emoji_id: int, user_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO emoji_favourite(emoji_id, user_id) VALUES(?, ?)", (emoji_id, user_id))

    async def remove_emoji_favourite(self, emoji_id: int, user_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM emoji_favourite WHERE user_id=? AND emoji_id=?", (user_id, emoji_id))

    async def list_emoji_favourite(self, user_id: int) -> list[EmojiFavouriteDb]:
        async with self.pool.acquire() as conn:
            stmt = self.stmt_star("SELECT * FROM emoji_favourite WHERE user_id=?", EmojiFavouriteDb.__slots__)
            records = await conn.fetchall(stmt, (user_id,))

        return [self.wrap_key_or_none(record, EmojiFavouriteDb.__slots__, cls=EmojiFavouriteDb) for record in records]

    async def upsert_emoji_usage(self, emoji_id: int, user_id: int, amount: int) -> SQLITE_RECORD:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO emoji_used (emoji_id, user_id, amount)
                VALUES (?, ?, ?)
                ON CONFLICT (emoji_id, user_id)
                DO UPDATE SET amount = emoji_used.amount + excluded.amount
                """,
                (emoji_id, user_id, amount)
            )
            keys = EmojiUsageDb.__slots__
            stmt = self.stmt_star("SELECT * FROM emoji_used WHERE emoji_id=?", keys)
            data = await conn.fetchone(stmt, (emoji_id,))
        return self.wrap_key_or_none(data, keys, cls=EmojiUsageDb)

    async def update_emoji_hash(self, emoji_id: int, image_hash: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE emoji SET hash=? WHERE id=?", (image_hash, emoji_id))

    async def bulk_update_emoji_names(self, values: list[tuple[int, str]]) -> None:
        values = [(x, y) for y, x in values]
        async with self.pool.acquire() as conn:
            query = "UPDATE emoji SET fullname=? WHERE id=?"
            if len(values) == 1:
                await conn.execute(query, values[0])
            else:
                await conn.executemany(query, values)

    async def bulk_remove_emojis(self, emoji_ids: list[int]) -> None:
        async with self.pool.acquire() as conn:
            query = "DELETE FROM emoji WHERE id=?"
            if len(emoji_ids) == 1:
                await conn.execute(query, *emoji_ids)
            else:
                await conn.executemany(query, [(x,) for x in emoji_ids])


class EmojiCustomDb(typing.Generic[T]):
    __slots__ = ('id', 'fullname', 'added_by', 'hash')

    def __init__(self, data: DbRecord[T]) -> None:
        self.id: int = data.id
        self.fullname: str = data.fullname
        self.added_by: int = data.added_by
        self.hash: str = data.hash


class EmojiUsageDb(typing.Generic[T]):
    __slots__ = ('emoji_id', 'user_id', 'amount', 'first_used')

    def __init__(self, data: DbRecord[T]):
        self.emoji_id: int = data.emoji_id
        self.user_id: int = data.user_id
        self.amount: int = data.amount
        self.first_used: datetime.datetime = data.first_used


class EmojiFavouriteDb(typing.Generic[T]):
    __slots__ = ('emoji_id', 'user_id', 'made_at')

    def __init__(self, data: DbRecord[T]):
        self.emoji_id: int = data.emoji_id
        self.user_id: int = data.user_id
        self.made_at: datetime.datetime = data.made_at


class UserDb(typing.Generic[T]):
    __slots__ = ('id', 'started_at')

    def __init__(self, data: DbRecord[T]):
        self.id: int = data.id
        self.started_at: datetime.datetime = data.started_at


class MetadataDb(typing.Generic[T]):
    __slots__ = ('id', 'data', 'bot_version', 'created_at')

    def __init__(self, data: DbRecord[T]):
        if not isinstance((dt := data.data["data"]), dict):
            dt = json.loads(dt)

        self.data: dict[str, typing.Any] = dt
        self.id: int = data.id
        self.bot_version: str = data.bot_version
        self.created_at: datetime.datetime = data.created_at
