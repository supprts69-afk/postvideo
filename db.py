"""Direct Postgres (Supabase) insert. content / posts / tags / content_tags / telegram_imports."""
import json
import os
import uuid

import asyncpg

from textutil import make_slug, tag_slug

pool: asyncpg.Pool | None = None

INSERT_CONTENT = """
insert into public.content
  (owner_id, title, slug, description, content_type, thumbnail_url, media_url,
   source, duration_seconds, visibility, status, is_short)
values ($1, $2, $3::text, $4, 'video', $5, $6, $7, $8, 'public', 'published', $9)
returning id
"""

UPSERT_TAG = """
insert into public.tags (name, slug) values ($1, $2::text)
on conflict (slug) do update set name = public.tags.name
returning id
"""


async def init() -> None:
    global pool
    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    # statement_cache_size=0 -> Supabase pgbouncer/pooler-er sathe lage
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3, statement_cache_size=0, command_timeout=60)


async def close() -> None:
    if pool:
        await pool.close()


async def profile_exists(profile_id: str) -> bool:
    return bool(await pool.fetchval("select 1 from public.profiles where id = $1", uuid.UUID(profile_id)))


async def is_done(source: str, message_id: int) -> bool:
    return bool(
        await pool.fetchval(
            "select 1 from public.telegram_imports where source = $1 and message_id = $2", source, message_id
        )
    )


async def last_id(source: str) -> int | None:
    return await pool.fetchval("select max(message_id) from public.telegram_imports where source = $1", source)


async def mark(source: str, message_id: int, kind: str, target: uuid.UUID | None = None, con=None) -> None:
    await (con or pool).execute(
        "insert into public.telegram_imports (source, message_id, kind, target_id) values ($1, $2, $3, $4) "
        "on conflict do nothing",
        source, message_id, kind, target,
    )


async def save_video(
    source: str, message_id: int, owner_id: str, title: str, description: str | None,
    media_url: str, thumbnail_url: str | None, duration: int | None, is_short: bool,
    tags: list[str], source_value: str,
) -> uuid.UUID:
    owner = uuid.UUID(owner_id)
    async with pool.acquire() as con:
        async with con.transaction():
            cid = None
            for _ in range(5):  # slug unique -> collision hole abar try
                slug = make_slug(title, "video")
                try:
                    async with con.transaction():  # savepoint
                        cid = await con.fetchval(
                            INSERT_CONTENT, owner, title, slug, description,
                            thumbnail_url, media_url, source_value, duration, is_short,
                        )
                    break
                except asyncpg.UniqueViolationError:
                    continue
            if cid is None:
                raise RuntimeError("slug collision 5 bar")
            for t in tags:
                slug_t = tag_slug(t)
                if not slug_t:
                    continue
                tid = await con.fetchval(UPSERT_TAG, t[:50], slug_t)
                await con.execute(
                    "insert into public.content_tags (content_id, tag_id) values ($1, $2) on conflict do nothing",
                    cid, tid,
                )
            await mark(source, message_id, "reel" if is_short else "video", cid, con)
    return cid


async def save_post(
    source: str, message_id: int, author_id: str, title: str | None, body: str | None, images: list[str]
) -> uuid.UUID:
    async with pool.acquire() as con:
        async with con.transaction():
            pid = await con.fetchval(
                "insert into public.posts (author_id, title, body, images) values ($1, $2, $3, $4::jsonb) returning id",
                uuid.UUID(author_id), title, body, json.dumps(images),
            )
            await mark(source, message_id, "post", pid, con)
    return pid
