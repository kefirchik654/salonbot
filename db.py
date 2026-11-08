"""PostgreSQL через asyncpg. Интерфейс q / q1 / ex, в SQL используется '?' - он автоматически превращается в $1, $2..."""
import re
import asyncpg
from config import DATABASE_URL

_pool = None
ID_TABLES = {"salons", "masters", "services", "bookings"}  # таблицы с автоматическим id
SCHEMA = """
CREATE TABLE IF NOT EXISTS salons(id SERIAL PRIMARY KEY, name TEXT, address TEXT, lat DOUBLE PRECISION, lon DOUBLE PRECISION,
  phone TEXT, description TEXT, tz TEXT, return_days INTEGER DEFAULT 30, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS admins(user_id BIGINT, salon_id INTEGER, PRIMARY KEY(user_id, salon_id));
CREATE TABLE IF NOT EXISTS masters(id SERIAL PRIMARY KEY, salon_id INTEGER, name TEXT, calendar_id TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS services(id SERIAL PRIMARY KEY, master_id INTEGER, name TEXT, price TEXT, duration INTEGER, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS schedules(master_id INTEGER, weekday INTEGER, t_from TEXT, t_to TEXT);
CREATE TABLE IF NOT EXISTS users(user_id BIGINT PRIMARY KEY, name TEXT, lang TEXT, notify INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS bookings(id SERIAL PRIMARY KEY, salon_id INTEGER, master_id INTEGER, service_id INTEGER,
  user_id BIGINT, client_name TEXT, t_start TEXT, t_end TEXT, status TEXT, r24 INTEGER DEFAULT 0, r2 INTEGER DEFAULT 0,
  event_id TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS winback(user_id BIGINT, salon_id INTEGER, sent TEXT);
CREATE TABLE IF NOT EXISTS tr(lang TEXT, src TEXT, dst TEXT, PRIMARY KEY(lang, src));
CREATE INDEX IF NOT EXISTS ix_b_master ON bookings(master_id, t_start);
CREATE INDEX IF NOT EXISTS ix_b_user ON bookings(user_id);
"""


def _conv(sql):
    n = 0

    def rep(_):
        nonlocal n
        n += 1
        return f"${n}"
    return re.sub(r"\?", rep, sql)




async def init():
    global _pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан (см. инструкцию)")

    _pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=1, max_size=5
    )

    async with _pool.acquire() as c:
        await c.execute(SCHEMA)
        await c.execute("""
            ALTER TABLE salons ADD COLUMN IF NOT EXISTS active INTEGER DEFAULT 1;
            ALTER TABLE masters ADD COLUMN IF NOT EXISTS active INTEGER DEFAULT 1;
            ALTER TABLE services ADD COLUMN IF NOT EXISTS active INTEGER DEFAULT 1;
        """)




async def q(sql, args=()):
    async with _pool.acquire() as c:
        return await c.fetch(_conv(sql), *args)


async def q1(sql, args=()):
    rows = await q(sql, args)
    return rows[0] if rows else None


async def ex(sql, args=()):
    m = re.match(r"\s*insert\s+into\s+(\w+)", sql, re.I)
    async with _pool.acquire() as c:
        if m and m.group(1).lower() in ID_TABLES and "returning" not in sql.lower():
            return await c.fetchval(_conv(sql) + " RETURNING id", *args)
        await c.execute(_conv(sql), *args)
        return None
