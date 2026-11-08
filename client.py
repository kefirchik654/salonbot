import html
import logging
from datetime import date, datetime, time, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo)

import db
import gcal
from config import PUBLIC_URL
from core import (FMT, create_booking, free_dates, free_slots, ikb, now_in, service_ctx, show, tsend, user_lang)
from i18n import LANGS, ensure_lang, fdate, norm_lang, t

log = logging.getLogger("client")
router = Router()


def main_kb(lang):
    r1 = [KeyboardButton(text=t(lang, "m_salons"))]
    if PUBLIC_URL.startswith("https://"):
        r1.append(KeyboardButton(text=t(lang, "m_map"), web_app=WebAppInfo(url=PUBLIC_URL + "/map")))
    r2 = [KeyboardButton(text=t(lang, "m_my")), KeyboardButton(text=t(lang, "m_lang"))]
    return ReplyKeyboardMarkup(keyboard=[r1, r2], resize_keyboard=True)


async def salon_card(sid, lang):
    s = await db.q1("select * from salons where id=? and active=1", (sid,))
    if not s:
        return None
    phone = f"📞 {s['phone']}" if s["phone"] else ""
    text = t(lang, "salon_card", name=s["name"], address=s["address"] or "", phone_line=phone, description=s["description"] or "")
    rows = [[(t(lang, "b_book"), f"bk:{sid}")], [(t(lang, "b_masters"), f"ms:{sid}")]]
    if s["lat"] is not None:
        rows.append([(t(lang, "b_route"), f"rt:{sid}")])
    rows.append([(t(lang, "b_back"), "sl")])
    return text, ikb(rows)


async def salons_kb(lang):
    ss = await db.q("select id,name from salons where active=1 order by name")
    if not ss:
        return t(lang, "no_salons"), None
    return t(lang, "pick_salon"), ikb([[("💈 " + s["name"], f"s:{s['id']}")] for s in ss])


@router.message(CommandStart())
async def start(m: Message, command: CommandObject, lang):
    arg = command.args or ""
    if arg.startswith("s") and arg[1:].isdigit():  # ссылка вида t.me/бот?start=s5 открывает салон №5
        card = await salon_card(int(arg[1:]), lang)
        if card:
            await m.answer(t(lang, "start", name=m.from_user.first_name), reply_markup=main_kb(lang))
            return await m.answer(card[0], reply_markup=card[1])
    await m.answer(t(lang, "start", name=m.from_user.first_name), reply_markup=main_kb(lang))


@router.message(Command("myid"))
async def myid(m: Message):
    await m.answer(f"Your Telegram ID: <code>{m.from_user.id}</code>")


@router.message(Command("stop"))
async def stop(m: Message, lang):
    await db.ex("update users set notify=0 where user_id=?", (m.from_user.id,))
    await m.answer(t(lang, "stop_ok"))


@router.message(Command("resume"))
async def resume(m: Message, lang):
    await db.ex("update users set notify=1 where user_id=?", (m.from_user.id,))
    await m.answer(t(lang, "resume_ok"))


async def set_lang(m: Message, code):
    code = norm_lang(code)
    await db.ex("update users set lang=? where user_id=?", (code, m.from_user.id))
    await ensure_lang(code)
    await m.answer(t(code, "lang_set"), reply_markup=main_kb(code))


@router.message(Command("lang"))
async def lang_cmd(m: Message, command: CommandObject, lang):
    if command.args:
        return await set_lang(m, command.args.strip())
    rows = [LANGS[i:i + 2] for i in range(0, len(LANGS), 2)]
    await m.answer(t(lang, "lang_pick"), reply_markup=ikb([[(n, f"lg:{c}") for n, c in r] for r in rows]))


@router.callback_query(F.data.startswith("lg:"))
async def lang_cb(cb: CallbackQuery):
    code = norm_lang(cb.data[3:])
    await db.ex("update users set lang=? where user_id=?", (code, cb.from_user.id))
    await ensure_lang(code)
    await cb.message.answer(t(code, "lang_set"), reply_markup=main_kb(code))
    await cb.answer()


@router.message(F.web_app_data)
async def from_map(m: Message, lang):
    data = (m.web_app_data.data or "").strip()
    if data.isdigit():
        card = await salon_card(int(data), lang)
        if card:
            await m.answer(card[0], reply_markup=card[1])


@router.message(F.text)
async def text_router(m: Message, lang):
    x = m.text or ""
    if x.startswith("/"):
        return
    if x == t(lang, "m_salons"):
        txt, kb = await salons_kb(lang)
        await m.answer(txt, reply_markup=kb)
    elif x == t(lang, "m_my"):
        await my_bookings(m, lang)
    elif x == t(lang, "m_lang"):
        await lang_cmd(m, CommandObject(command="lang"), lang)


# ---------- салоны ----------
@router.callback_query(F.data == "sl")
async def cb_salons(cb: CallbackQuery, lang):
    txt, kb = await salons_kb(lang)
    await show(cb, txt, kb)


@router.callback_query(F.data.startswith("s:"))
async def cb_salon(cb: CallbackQuery, lang):
    card = await salon_card(int(cb.data[2:]), lang)
    if card:
        await show(cb, *card)


@router.callback_query(F.data.startswith("rt:"))
async def cb_route(cb: CallbackQuery):
    s = await db.q1("select lat,lon from salons where id=?", (int(cb.data[3:]),))
    if s and s["lat"] is not None:
        await cb.message.answer_location(s["lat"], s["lon"])
    await cb.answer()


@router.callback_query(F.data.startswith("ms:"))
async def cb_masters(cb: CallbackQuery, lang):
    sid = int(cb.data[3:])
    ms = await db.q("select id,name from masters where salon_id=? and active=1", (sid,))
    if not ms:
        return await show(cb, t(lang, "no_masters"), ikb([[(t(lang, "b_back"), f"s:{sid}")]]))
    parts = [t(lang, "masters_title")]
    for mm in ms:
        parts.append(f"\n👩‍🎤 <b>{html.escape(mm['name'])}</b>")
        for sv in await db.q("select * from services where master_id=? and active=1", (mm["id"],)):
            parts.append(t(lang, "svc_line", name=sv["name"], price=sv["price"], dur=sv["duration"]))
    await show(cb, "\n".join(parts), ikb([[(t(lang, "b_book"), f"bk:{sid}")], [(t(lang, "b_back"), f"s:{sid}")]]))


# ---------- запись ----------
@router.callback_query(F.data.startswith("bk:"))
async def cb_pick_master(cb: CallbackQuery, lang):
    sid = int(cb.data[3:])
    ms = await db.q("""select m.id,m.name from masters m where m.salon_id=? and m.active=1
        and exists(select 1 from services s where s.master_id=m.id and s.active=1)
        and exists(select 1 from schedules c where c.master_id=m.id)""", (sid,))
    if not ms:
        return await show(cb, t(lang, "no_masters"), ikb([[(t(lang, "b_back"), f"s:{sid}")]]))
    rows = [[("👩‍🎤 " + mm["name"], f"bm:{mm['id']}")] for mm in ms] + [[(t(lang, "b_back"), f"s:{sid}")]]
    await show(cb, t(lang, "pick_master"), ikb(rows))


@router.callback_query(F.data.startswith("bm:"))
async def cb_pick_service(cb: CallbackQuery, lang):
    mid = int(cb.data[3:])
    m = await db.q1("select salon_id from masters where id=?", (mid,))
    svs = await db.q("select * from services where master_id=? and active=1", (mid,))
    rows = [[(f"{s['name']} — {s['price']} · {s['duration']}′", f"bs:{s['id']}")] for s in svs]
    rows.append([(t(lang, "b_back"), f"bk:{m['salon_id']}")])
    await show(cb, t(lang, "pick_service"), ikb(rows))


@router.callback_query(F.data.startswith("bs:"))
async def cb_pick_date(cb: CallbackQuery, lang):
    sid = int(cb.data[3:])
    ctx = await service_ctx(sid)
    back = [(t(lang, "b_back"), f"bm:{ctx['mid']}")]
    ds = await free_dates(ctx)
    if not ds:
        return await show(cb, t(lang, "no_dates"), ikb([back]))
    btns = [(fdate(lang, d), f"bd:{sid}:{d}") for d in ds]
    rows = [btns[i:i + 3] for i in range(0, len(btns), 3)] + [back]
    await show(cb, t(lang, "pick_date"), ikb(rows))


@router.callback_query(F.data.startswith("bd:"))
async def cb_pick_time(cb: CallbackQuery, lang):
    _, sid, ds = cb.data.split(":")
    ctx = await service_ctx(int(sid))
    d = date.fromisoformat(ds)
    back = [(t(lang, "b_back"), f"bs:{sid}")]
    slots = await free_slots(ctx, d)
    if not slots:
        return await show(cb, t(lang, "no_times"), ikb([back]))
    btns = [(f"{s:%H:%M}", f"bt:{sid}:{ds}:{s:%H%M}") for s in slots]
    rows = [btns[i:i + 4] for i in range(0, len(btns), 4)] + [back]
    await show(cb, t(lang, "pick_time", date=d), ikb(rows))


@router.callback_query(F.data.startswith("bt:"))
async def cb_confirm(cb: CallbackQuery, lang):
    _, sid, ds, hm = cb.data.split(":")
    ctx = await service_ctx(int(sid))
    start = datetime.combine(date.fromisoformat(ds), time(int(hm[:2]), int(hm[2:])))
    txt = t(lang, "confirm_q", salon=ctx["sname"], master=ctx["mname"], service=ctx["svc"], price=ctx["price"], when=start)
    await show(cb, txt, ikb([[(t(lang, "b_confirm"), f"bc:{sid}:{ds}:{hm}")], [(t(lang, "b_cancel"), f"bd:{sid}:{ds}")]]))


@router.callback_query(F.data.startswith("bc:"))
async def cb_book(cb: CallbackQuery, bot: Bot, lang):
    _, sid, ds, hm = cb.data.split(":")
    ctx = await service_ctx(int(sid))
    start = datetime.combine(date.fromisoformat(ds), time(int(hm[:2]), int(hm[2:])))
    bid = await create_booking(bot, ctx, cb.from_user, start)
    if not bid:
        return await show(cb, t(lang, "slot_taken"), ikb([[(t(lang, "b_back"), f"bd:{sid}:{ds}")]]))
    b = await db.q1("select status from bookings where id=?", (bid,))
    if b["status"] == "pending":
        await show(cb, t(lang, "sent_pending", id=bid))
    else:
        await cb.answer()


# ---------- мои записи ----------
async def my_bookings(m: Message, lang):
    since = (datetime.utcnow() - timedelta(days=1)).strftime(FMT)
    rows = await db.q("""select b.id, b.t_start, b.status, sa.name sname, ma.name mname, s.name svc from bookings b
        join salons sa on sa.id=b.salon_id join masters ma on ma.id=b.master_id join services s on s.id=b.service_id
        where b.user_id=? and b.status in ('pending','confirmed') and b.t_start>=? order by b.t_start limit 10""",
                        (m.chat.id, since))
    if not rows:
        return await m.answer(t(lang, "my_none"))
    for r in rows:
        await m.answer(t(lang, "my_line", id=r["id"], when=datetime.strptime(r["t_start"], FMT), salon=r["sname"],
                         master=r["mname"], service=r["svc"], status=t(lang, "st_" + r["status"])),
                       reply_markup=ikb([[(t(lang, "b_cancel_bk", id=r["id"]), f"cx:{r['id']}")]]))


@router.callback_query(F.data.startswith("cx:"))
async def cb_cancel(cb: CallbackQuery, bot: Bot, lang):
    from core import booking_ctx
    bid = int(cb.data[3:])
    b = await booking_ctx(bid)
    if not b or b["user_id"] != cb.from_user.id or b["status"] not in ("pending", "confirmed"):
        return await cb.answer()
    await db.ex("update bookings set status='cancelled' where id=?", (bid,))
    await gcal.delete_event(b["calendar_id"], b["event_id"])
    for r in await db.q("select user_id from admins where salon_id=?", (b["salon_id"],)):
        await tsend(bot, r["user_id"], "a_cancelled_by_client", id=bid, client=b["client_name"],
                    when=datetime.strptime(b["t_start"], FMT))
    await show(cb, t(lang, "cancelled_ok", id=bid))


@router.callback_query(F.data.startswith("ok:"))
async def cb_come(cb: CallbackQuery, lang):
    await show(cb, t(lang, "come_ok"))


@router.callback_query(F.data.startswith("rs:"))
async def cb_resched(cb: CallbackQuery, bot: Bot, lang):
    from core import booking_ctx
    bid = int(cb.data[3:])
    b = await booking_ctx(bid)
    if b and b["user_id"] == cb.from_user.id and b["status"] in ("pending", "confirmed"):
        await db.ex("update bookings set status='cancelled' where id=?", (bid,))
        await gcal.delete_event(b["calendar_id"], b["event_id"])
        for r in await db.q("select user_id from admins where salon_id=?", (b["salon_id"],)):
            await tsend(bot, r["user_id"], "a_cancelled_by_client", id=bid, client=b["client_name"],
                        when=datetime.strptime(b["t_start"], FMT))
    if b:
        await show(cb, t(lang, "pick_master"), ikb([[(t(lang, "b_book"), f"bk:{b['salon_id']}")]]))
    else:
        await cb.answer()
