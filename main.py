import asyncio
import logging

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

import admin
import client
import db
import jobs
from config import BOT_TOKEN, PORT
from i18n import ensure_lang, norm_lang

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class LangMw(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u:
            row = await db.q1("select lang from users where user_id=?", (u.id,))
            if row and row["lang"]:
                lang = row["lang"]
                await db.ex("update users set name=? where user_id=?", (u.full_name, u.id))
            else:
                lang = norm_lang(u.language_code)
                await db.ex("insert into users(user_id,name,lang,notify) values(?,?,?,1) "
                            "on conflict(user_id) do update set name=excluded.name, lang=excluded.lang", (u.id, u.full_name, lang))
            await ensure_lang(lang)
            data["lang"] = lang
        return await handler(event, data)


async def api_salons(request):
   rows = await db.q("select id,name,address,lat,lon from salons where active=1 and lat is not null")
   return web.json_response([dict(r) for r in rows])


async def map_page(request):
    return web.FileResponse("static/map.html")


async def health(request):
    return web.Response(text="ok")


async def main():
    await db.init()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.outer_middleware(LangMw())
    dp.callback_query.outer_middleware(LangMw())
    dp.include_router(admin.router)   # админ-команды раньше клиентских
    dp.include_router(client.router)

    app = web.Application()
    app.add_routes([web.get("/map", map_page), web.get("/api/salons", api_salons), web.get("/health", health)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    asyncio.create_task(jobs.loop(jobs.reminders, bot, 60))
    asyncio.create_task(jobs.loop(jobs.winback, bot, 600))
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
