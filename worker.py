"""Telegram -> website importer (Telethon).

Duita source type (dutoi ekshathe chalate paro):
  via=user : tomar Telegram account (TG_SESSION) channel/bot chat dekhe
  via=bot  : tomar nijer bot (TG_BOT_TOKEN, @BotFather theke). Bot-e keu message/forward korle post hoy,
             kintu shudhu allowed_senders / allowed_chats-er message. Bot reply diye janiye dey.

Text / photo / link  -> public.posts
Video (vertical)     -> public.content  (is_short = true  => reel)
Video (landscape)    -> public.content  (is_short = false => long video)
"""
import asyncio
import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityTextUrl, MessageMediaWebPage

import ai
import db
import storage
import textutil

log = logging.getLogger("tg.worker")

DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() in ("1", "true", "yes")
MAX_BYTES = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024
BACKFILL = int(os.getenv("BACKFILL_LIMIT", "0"))
CONTENT_SOURCE = os.getenv("CONTENT_SOURCE_VALUE", "external")  # existing rows-e 'external'
VIDEO_EXT = {"video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm"}


@dataclass
class Source:
    chat: object
    author_id: str
    ai_rewrite: bool = False
    entity: object = None
    key: str = ""
    via: str = "user"  # user | bot
    client: object = None
    allowed_senders: set = field(default_factory=set)
    allowed_chats: set = field(default_factory=set)


def group_messages(msgs: list) -> list[list]:
    """Album-er message gulo ekshathe, baki single. Purono -> notun order."""
    groups: dict = {}
    singles: list[list] = []
    for m in sorted(msgs, key=lambda x: x.id):
        if getattr(m, "action", None):  # service message
            continue
        if m.grouped_id:
            groups.setdefault(m.grouped_id, []).append(m)
        else:
            singles.append([m])
    out = singles + list(groups.values())
    out.sort(key=lambda g: g[0].id)
    return out


def _is_video(m) -> bool:
    return bool(m.video and not m.gif and not m.sticker)


def _entity_urls(m) -> list[str]:
    return [e.url for e in (m.entities or []) if isinstance(e, MessageEntityTextUrl) and e.url]


class Importer:
    def __init__(self) -> None:
        self.clients: list[TelegramClient] = []
        self.user_client: TelegramClient | None = None
        self.bot_src: Source | None = None
        self.sources: dict[int, Source] = {}  # user-mode: peer id -> Source
        self.queue: asyncio.Queue = asyncio.Queue()
        self.tasks: list[asyncio.Task] = []
        self.ready = False
        self.last_error: str | None = None
        self.processed = 0

    def status(self) -> dict:
        return {
            "ready": self.ready,
            "dry_run": DRY_RUN,
            "user_sources": len(self.sources),
            "bot": self.bot_src is not None,
            "queue": self.queue.qsize(),
            "processed": self.processed,
            "ai": ai.enabled(),
            "last_error": self.last_error,
        }

    # ---------- lifecycle ----------
    async def run(self) -> None:
        try:
            await self.start()
        except Exception as e:  # server jeno bere thake, /health-e error dekha jabe
            self.last_error = repr(e)
            log.exception("startup failed")

    async def start(self) -> None:
        self.api_id = int(os.environ["TG_API_ID"])
        self.api_hash = os.environ["TG_API_HASH"].strip()
        session = os.getenv("TG_SESSION", "").strip()
        bot_token = os.getenv("TG_BOT_TOKEN", "").strip()
        raw = json.loads(os.environ["TG_SOURCES"])

        user_items = [i for i in raw if i.get("via", "user") == "user"]
        bot_items = [i for i in raw if i.get("via") == "bot"]
        if not raw:
            raise RuntimeError("TG_SOURCES khali")
        if len(bot_items) > 1:
            raise RuntimeError("ekta bot token-e ekta-i via=bot source dite paro")
        if user_items and not session:
            raise RuntimeError("via=user source-er jonno TG_SESSION lage")
        if bot_items and not bot_token:
            raise RuntimeError("via=bot source-er jonno TG_BOT_TOKEN lage")

        await db.init()
        self.tasks.append(asyncio.create_task(self._worker()))
        if user_items:
            await self._start_user(session, user_items)
        if bot_items:
            await self._start_bot(bot_token, bot_items[0])
        await self._catch_up()  # shudhu user-mode (bot history porte pare na)
        self.ready = True
        log.info("importer ready (DRY_RUN=%s, AI=%s)", DRY_RUN, ai.enabled())

    async def _check_author(self, item: dict) -> str:
        author = str(uuid.UUID(item["author_id"]))
        if not await db.profile_exists(author):
            raise RuntimeError(f"author_id {author} profiles table-e nai")
        return author

    async def _start_user(self, session: str, items: list[dict]) -> None:
        client = TelegramClient(StringSession(session), self.api_id, self.api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("TG_SESSION login-ed na. make_session.py abar chalao.")
        self.user_client = client
        self.clients.append(client)

        if any(isinstance(i["chat"], int) or str(i["chat"]).lstrip("-").isdigit() for i in items):
            await client.get_dialogs()  # numeric id resolve korar jonno cache lage

        for item in items:
            chat = item["chat"]
            if isinstance(chat, str) and chat.lstrip("-").isdigit():
                chat = int(chat)
            author = await self._check_author(item)
            entity = await client.get_entity(chat)
            pid = utils.get_peer_id(entity)
            self.sources[pid] = Source(chat, author, bool(item.get("ai_rewrite", False)), entity, str(pid), "user", client)
            log.info("user-mode: watching %s (peer %s) -> author %s", chat, pid, author)

        ids = list(self.sources.keys())
        client.add_event_handler(self._on_message, events.NewMessage(chats=ids, func=lambda e: not e.message.grouped_id))
        client.add_event_handler(self._on_album, events.Album(chats=ids))

    async def _start_bot(self, token: str, item: dict) -> None:
        senders = {int(x) for x in item.get("allowed_senders", [])}
        chats = {int(x) for x in item.get("allowed_chats", [])}
        if not senders and not chats:
            raise RuntimeError("bot source-e allowed_senders ba allowed_chats dite hobe (noile je keu post korte parto)")
        author = await self._check_author(item)
        client = TelegramClient(StringSession(), self.api_id, self.api_hash)
        await client.start(bot_token=token)
        self.clients.append(client)
        me = await client.get_me()
        self.bot_src = Source("bot", author, bool(item.get("ai_rewrite", False)), None, "bot", "bot", client, senders, chats)
        client.add_event_handler(self._on_bot_message, events.NewMessage(incoming=True, func=lambda e: not e.message.grouped_id))
        client.add_event_handler(self._on_bot_album, events.Album())
        log.info("bot-mode: @%s -> author %s, senders=%s chats=%s", getattr(me, "username", "?"), author, senders, chats)

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        for c in self.clients:
            await c.disconnect()
        await db.close()

    # ---------- events: user mode ----------
    async def _on_message(self, event) -> None:
        src = self.sources.get(event.chat_id)
        if src:
            self.queue.put_nowait(([event.message], src, src.key, event.chat_id))

    async def _on_album(self, event) -> None:
        src = self.sources.get(event.chat_id)
        if src:
            self.queue.put_nowait((list(event.messages), src, src.key, event.chat_id))

    # ---------- events: bot mode ----------
    def _bot_allowed(self, event) -> bool:
        s = self.bot_src
        return bool(s) and (event.sender_id in s.allowed_senders or event.chat_id in s.allowed_chats)

    async def _on_bot_message(self, event) -> None:
        await self._bot_dispatch([event.message], event)

    async def _on_bot_album(self, event) -> None:
        await self._bot_dispatch(list(event.messages), event)

    async def _bot_dispatch(self, msgs: list, event) -> None:
        text = (msgs[0].message or "").strip()
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if cmd in ("/id", "/start"):  # je keu chaile nijer id jante pare (allowlist-e boshabe)
            await event.reply(f"Tomar user id: {event.sender_id}\nChat id: {event.chat_id}\n"
                              "Ei id TG_SOURCES-er allowed_senders / allowed_chats-e dao.")
            return
        if not self._bot_allowed(event) or cmd:
            return  # onno keu / onno command: chup
        self.queue.put_nowait((msgs, self.bot_src, f"bot:{event.chat_id}", event.chat_id))

    async def _reply(self, src: Source, chat_id: int, reply_to: int, text: str) -> None:
        if src.via != "bot":
            return
        try:
            await src.client.send_message(chat_id, text, reply_to=reply_to)
        except Exception as e:
            log.warning("bot reply fail: %r", e)

    async def _worker(self) -> None:
        """Ekta ekta kore process kore (chhoto Render instance-e RAM bachate)."""
        while True:
            msgs, src, key, chat_id = await self.queue.get()
            try:
                results = await self.process(msgs, src, key)
                self.processed += 1
                if results:
                    await self._reply(src, chat_id, msgs[-1].id, "\n".join(results))
            except Exception as e:
                self.last_error = repr(e)
                log.exception("process failed (chat %s, msg %s)", chat_id, msgs[0].id if msgs else "?")
                await self._reply(src, chat_id, msgs[-1].id, f"❌ post hoy ni ({type(e).__name__}). Render log dekho.")
            finally:
                self.queue.task_done()

    async def _catch_up(self) -> None:
        """Restart/ghumiye thaka-r somoy miss howa message tule ane (shudhu user-mode)."""
        for pid, src in self.sources.items():
            last = await db.last_id(src.key)
            if last is None:
                if BACKFILL > 0:
                    msgs = [m async for m in src.client.iter_messages(src.entity, limit=BACKFILL)]
                else:  # prothom bar: ekhon theke shuru, purono post import hobe na
                    latest = [m async for m in src.client.iter_messages(src.entity, limit=1)]
                    if latest and not DRY_RUN:
                        await db.mark(src.key, latest[0].id, "baseline")
                    continue
            else:
                msgs = [m async for m in src.client.iter_messages(src.entity, min_id=last, limit=200)]
            for group in group_messages(msgs):
                self.queue.put_nowait((group, src, src.key, pid))
            if msgs:
                log.info("catch-up %s: %d message queue-te", src.chat, len(msgs))

    # ---------- processing ----------
    async def process(self, msgs: list, src: Source, key: str) -> list[str]:
        """Return: user-ke janar moto chhoto result line (bot-mode-e reply hishebe jay)."""
        if not msgs:
            return []
        msgs = sorted(msgs, key=lambda m: m.id)
        text = next((m.message for m in msgs if m.message), "").strip()
        extra_urls = [u for m in msgs for u in _entity_urls(m) if u not in text]

        photos = [m for m in msgs if m.photo]
        videos = [m for m in msgs if _is_video(m)]
        text_only = all(m.media is None or isinstance(m.media, MessageMediaWebPage) for m in msgs)
        results: list[str] = []

        if videos:
            parsed = await self._parse(text, "video", src)
            for v in videos:
                results.append(await self._video(v, src, key, parsed, extra_urls))
        if photos or (not videos and text and text_only):
            parsed = await self._parse(text, "post", src)
            results.append(await self._post(photos, msgs, src, key, parsed, extra_urls))
        if not results:
            if not DRY_RUN:
                await db.mark(key, msgs[-1].id, "skipped:unsupported")
            return ["⚠️ Ei type support kori na (shudhu text, photo, video)."]
        return [r for r in results if r]

    async def _parse(self, text: str, kind: str, src: Source) -> dict:
        tags = textutil.hashtags(text)
        result = await ai.analyze(text, kind, src.ai_rewrite) if (text and ai.enabled()) else None
        if result:
            title, body = result["title"], result["body"]
            tags = textutil.merge_tags(tags, result["tags"])
        else:
            t = textutil.strip_hashtags(text) if kind == "video" else text
            title, body = textutil.split_title_body(t)
        return {"title": title, "body": body, "tags": tags}

    async def _video(self, m, src: Source, key: str, parsed: dict, extra_urls: list[str]) -> str:
        if await db.is_done(key, m.id):
            return "ℹ️ Age-i import kora."
        f = m.file
        mime = (f.mime_type or "").lower()
        ext = VIDEO_EXT.get(mime)
        size = f.size or 0
        if not ext or size > MAX_BYTES:
            reason = "format" if not ext else "too_big"
            log.warning("skip video msg %s: %s (%s, %.1f MB, limit %d MB)", m.id, reason, mime, size / 1048576, MAX_BYTES >> 20)
            if not DRY_RUN:
                await db.mark(key, m.id, f"skipped:{reason}")
            if not ext:
                return f"⚠️ Video skip: format support kori na ({mime or 'unknown'}). mp4/mov/webm dao."
            return f"⚠️ Video skip: {size / 1048576:.0f} MB, limit {MAX_BYTES >> 20} MB."

        w, h = f.width or 0, f.height or 0
        is_short = h > w > 0  # vertical => reel
        label = "Reel" if is_short else "Long video"
        duration = int(f.duration) if f.duration else None
        title = parsed["title"] or "Video"
        description = textutil.append_urls(parsed["body"], extra_urls)

        if DRY_RUN:
            log.info("[DRY_RUN] %s msg=%s %sx%s %ss title=%r tags=%s desc=%r",
                     label.upper(), m.id, w, h, duration, title, parsed["tags"], (description or "")[:80])
            return f"🧪 DRY_RUN: {label} hobe, title: {title}"

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, f"v.{ext}")
            await src.client.download_media(m, file=path)
            data = Path(path).read_bytes()
        media_url = await storage.upload(data, ext, mime)

        thumb_url = None
        try:  # Telegram-er nijer thumbnail (ffmpeg lage na)
            tb = await src.client.download_media(m, file=bytes, thumb=-1)
            if tb:
                thumb_url = await storage.upload(tb, "jpg", "image/jpeg")
        except Exception as e:
            log.warning("thumbnail fail msg %s: %r", m.id, e)

        cid = await db.save_video(
            key, m.id, src.author_id, title, description, media_url, thumb_url,
            duration, is_short, parsed["tags"], CONTENT_SOURCE,
        )
        log.info("%s posted: content %s (msg %s)", label, cid, m.id)
        return f"✅ {label} post hoyeche: {title}"

    async def _post(self, photos: list, msgs: list, src: Source, key: str, parsed: dict, extra_urls: list[str]) -> str:
        key_id = (photos[0] if photos else msgs[0]).id
        if await db.is_done(key, key_id):
            return "ℹ️ Age-i import kora."
        title = parsed["title"] or None
        body = textutil.append_urls(parsed["body"], extra_urls)
        if not photos and not (title or body):
            return ""
        if DRY_RUN:
            log.info("[DRY_RUN] POST msg=%s photos=%d title=%r body=%r", key_id, len(photos), title, (body or "")[:80])
            return f"🧪 DRY_RUN: Post hobe ({len(photos)} photo)"

        images = []
        for p in photos:
            data = await src.client.download_media(p, file=bytes)
            if data:
                images.append(await storage.upload(data, "jpg", "image/jpeg"))
        pid = await db.save_post(key, key_id, src.author_id, title, body, images)
        log.info("POST posted: %s (msg %s, %d images)", pid, key_id, len(images))
        return f"✅ Post hoyeche ({len(images)} photo)"
