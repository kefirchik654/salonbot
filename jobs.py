"""Фоновые задачи: напоминания о записи и «давно не были»."""
import asyncio
import logging
from datetime import datetime, timedelta

import db
from core import FMT, ikb, now_in, tsend, user_lang
from i18n import t

log = logging.getLogger("jobs")


async def reminders(bot):
    rows = await db.q("""select b.id,b.t_start,b.r24,b.r2,b.user_id,s.name svc,m.name mname,sa.name sname,sa.address,sa.tz
        from bookings b join services s on s.id=b.service_id join masters m on m.id=b.master_id join salons sa on sa.id=b.salon_id
        where b.status='confirmed' and (b.r24=0 or b.r2=0) and b.t_start>=?""",
                      ((datetime.utcnow() - timedelta(days=1)).strftime(FMT),))
    for b in rows:
        start = datetime.strptime(b["t_start"], FMT)
        delta = start - now_in(b["tz"])
        if delta <= timedelta(0):
            continue
        kw = dict(when=start, salon=b["sname"], service=b["svc"], master=b["mname"], address=b["address"] or "")
        kbf = lambda lang, i=b["id"]: ikb([[(t(lang, "b_come"), f"ok:{i}"), (t(lang, "b_resched"), f"rs:{i}")],
                                          [(t(lang, "b_cancel_bk", id=i), f"cx:{i}")]])
        if not b["r2"] and delta <= timedelta(hours=2):
            await tsend(bot, b["user_id"], "rem2", kbf=kbf, **kw)
            await db.ex("update bookings set r2=1, r24=1 where id=?", (b["id"],))
        elif not b["r24"] and delta <= timedelta(hours=24):
            await tsend(bot, b["user_id"], "rem24", kbf=kbf, **kw)
            await db.ex("update bookings set r24=1 where id=?", (b["id"],))


async def winback(bot):
    for s in await db.q("select * from salons where active=1"):
        now = now_in(s["tz"])
        if not 11 <= now.hour < 20:  # пишем только днём
            continue
        limit = (now - timedelta(days=s["return_days"])).strftime(FMT)
        rows = await db.q("""select b.user_id, u.name from bookings b join users u on u.user_id=b.user_id
            where b.salon_id=? and b.status='confirmed' and u.notify=1 group by b.user_id, u.name having max(b.t_end)<=?""",
                          (s["id"], limit))
        for r in rows:
            uid = r["user_id"]
            if await db.q1("select 1 from bookings where user_id=? and salon_id=? and status in ('pending','confirmed') and t_end>=?",
                           (uid, s["id"], now.strftime(FMT))):
                continue
            if await db.q1("select 1 from winback where user_id=? and salon_id=? and sent>?", (uid, s["id"], limit)):
                continue
            await db.ex("insert into winback values(?,?,?)", (uid, s["id"], now.strftime(FMT)))
            await tsend(bot, uid, "winback",
                        kbf=lambda lang, i=s["id"]: ikb([[(t(lang, "b_book_now"), f"bk:{i}")]]),
                        name=(r["name"] or "").split(" ")[0], salon=s["name"])


async def loop(fn, bot, seconds):
    while True:
        try:
            await fn(bot)
        except Exception:
            log.exception("job %s failed", fn.__name__)
        await asyncio.sleep(seconds)
