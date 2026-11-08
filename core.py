import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db
import gcal
from config import DEFAULT_TZ, SUPER_ADMINS
from i18n import ensure_lang, t

log = logging.getLogger("core")
FMT = "%Y-%m-%d %H:%M"
STEP = 30  # шаг сетки времени, минут


def ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=a, callback_data=b) for a, b in r] for r in rows])


def now_in(tz):
    return datetime.now(ZoneInfo(tz or DEFAULT_TZ)).replace(tzinfo=None)


def is_super(uid):
    return uid in SUPER_ADMINS


async def admin_salons(uid):
    if is_super(uid):
        return await db.q("select * from salons where active=1")
    return await db.q("select s.* from salons s join admins a on a.salon_id=s.id where a.user_id=? and s.active=1", (uid,))


async def can_manage(uid, salon_id):
    return is_super(uid) or bool(await db.q1("select 1 from admins where user_id=? and salon_id=?", (uid, salon_id)))


async def show(cb, text, kb=None):
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


async def user_lang(uid):
    r = await db.q1("select lang from users where user_id=?", (uid,))
    return r["lang"] if r and r["lang"] else "en"


async def tsend(bot, uid, key, kbf=None, **kw):
    lang = await user_lang(uid)
    await ensure_lang(lang)
    try:
        await bot.send_message(uid, t(lang, key, **kw), reply_markup=kbf(lang) if kbf else None)
        return True
    except Exception as e:
        log.info("send to %s failed: %s", uid, e)
        return False


SVC_SQL = """select s.id sid, s.name svc, s.price, s.duration, m.id mid, m.name mname, m.calendar_id,
  sa.id said, sa.name sname, sa.tz, sa.address from services s join masters m on m.id=s.master_id
  join salons sa on sa.id=m.salon_id where s.id=?"""

BK_SQL = """select b.*, s.name svc, s.price, m.name mname, m.calendar_id, sa.name sname, sa.tz, sa.address
  from bookings b join services s on s.id=b.service_id join masters m on m.id=b.master_id
  join salons sa on sa.id=b.salon_id where b.id=?"""


async def service_ctx(sid):
    return await db.q1(SVC_SQL, (sid,))


async def booking_ctx(bid):
    return await db.q1(BK_SQL, (bid,))


async def free_slots(ctx, d):
    ivs = await db.q("select t_from,t_to from schedules where master_id=? and weekday=?", (ctx["mid"], d.weekday()))
    if not ivs:
        return []
    day0 = f"{d} 00:00"
    day1 = f"{d + timedelta(days=1)} 00:00"
    busy = [(r["t_start"], r["t_end"]) for r in await db.q(
        "select t_start,t_end from bookings where master_id=? and status in ('pending','confirmed') and t_start<? and t_end>?",
        (ctx["mid"], day1, day0))]
    dur = timedelta(minutes=ctx["duration"])
    limit = now_in(ctx["tz"]) + timedelta(minutes=30)
    out = set()
    for iv in ivs:
        cur = datetime.strptime(f"{d} {iv['t_from']}", FMT)
        end = datetime.strptime(f"{d} {iv['t_to']}", FMT)
        while cur + dur <= end:
            s, e = cur.strftime(FMT), (cur + dur).strftime(FMT)
            if cur >= limit and not any(s < be and e > bs for bs, be in busy):
                out.add(cur)
            cur += timedelta(minutes=STEP)
    return sorted(out)


async def free_dates(ctx, days=14):
    today = now_in(ctx["tz"]).date()
    res = []
    for i in range(days):
        d = today + timedelta(days=i)
        if await free_slots(ctx, d):
            res.append(d)
    return res


async def create_booking(bot, ctx, user, start):
    if start not in await free_slots(ctx, start.date()):
        return None
    end = start + timedelta(minutes=ctx["duration"])
    bid = await db.ex(
        "insert into bookings(salon_id,master_id,service_id,user_id,client_name,t_start,t_end,status,created) values(?,?,?,?,?,?,?, 'pending', ?)",
        (ctx["said"], ctx["mid"], ctx["sid"], user.id, user.full_name, start.strftime(FMT), end.strftime(FMT),
         datetime.utcnow().strftime(FMT)))
    admins = [r["user_id"] for r in await db.q("select user_id from admins where salon_id=?", (ctx["said"],))]
    if not admins:
        await confirm(bot, bid)
        return bid
    for uid in admins:
        await tsend(bot, uid, "a_new",
                    kbf=lambda lang: ikb([[(t(lang, "b_ok"), f"a:ok:{bid}"), (t(lang, "b_no"), f"a:no:{bid}")]]),
                    id=bid, client=user.full_name, master=ctx["mname"], service=ctx["svc"], when=start)
    return bid


async def confirm(bot, bid):
    b = await booking_ctx(bid)
    if not b or b["status"] != "pending":
        return False
    start = datetime.strptime(b["t_start"], FMT)
    end = datetime.strptime(b["t_end"], FMT)
    skip24 = 1 if start - now_in(b["tz"]) <= timedelta(hours=24) else 0
    ev = await gcal.create_event(b["calendar_id"], f"{b['svc']} — {b['client_name']}",
                                 f"Салон: {b['sname']}\nМастер: {b['mname']}\nКлиент: {b['client_name']} (tg id {b['user_id']})",
                                 start, end, b["tz"])
    await db.ex("update bookings set status='confirmed', r24=?, event_id=? where id=?", (skip24, ev, bid))
    await tsend(bot, b["user_id"], "confirmed_msg", id=bid, salon=b["sname"], master=b["mname"], service=b["svc"],
                when=start, address=b["address"] or "")
    return True


async def reject(bot, bid, notify_client=True):
    """Админ отклоняет (pending) или отменяет (confirmed) запись."""
    b = await booking_ctx(bid)
    if not b or b["status"] not in ("pending", "confirmed"):
        return False
    new = "rejected" if b["status"] == "pending" else "cancelled"
    await db.ex("update bookings set status=? where id=?", (new, bid))
    await gcal.delete_event(b["calendar_id"], b["event_id"])
    if notify_client:
        await tsend(bot, b["user_id"], "rejected_msg", id=bid, when=datetime.strptime(b["t_start"], FMT))
    return True
