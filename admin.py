"""Панель администратора салона + команды управления данными."""
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from zoneinfo import ZoneInfo

import db
from config import DEFAULT_TZ
from core import (FMT, admin_salons, booking_ctx, can_manage, confirm, ikb, is_super, now_in, reject, show, tsend)
from i18n import t

log = logging.getLogger("admin")
router = Router()
DAYS = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
DN = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

HELP = """<b>Команды управления</b> (значения разделяйте знаком |)

<b>Только владелец сервиса:</b>
/addsalon Название | Адрес | широта | долгота | Телефон | Описание
/addadmin ID_салона | Telegram_ID_админа
/deladmin ID_салона | Telegram_ID_админа
/delsalon ID_салона

<b>Владелец и админ салона:</b>
/salons — список ваших салонов
/info ID_салона — мастера, услуги, графики с их ID
/addmaster ID_салона | Имя мастера
/addservice ID_мастера | Услуга | Цена | Минут
/schedule ID_мастера | пн-пт 10:00-14:00,15:00-19:00; сб 10:00-16:00
/setcal ID_мастера | calendar_id (Google Календарь)
/delmaster ID_мастера
/delservice ID_услуги
/returndays ID_салона | дней (через сколько дней без визита напомнить, по умолчанию 30)
/tz ID_салона | Europe/Moscow
/admin — панель записей"""


def args(m: Message, n):
    raw = (m.text or "").split(None, 1)
    parts = [p.strip() for p in (raw[1] if len(raw) > 1 else "").split("|")]
    if len(parts) < n or not all(parts[:n]):
        return None
    return parts


async def salon_of_master(mid):
    r = await db.q1("select salon_id from masters where id=?", (mid,))
    return r["salon_id"] if r else None


@router.message(Command("help_admin"))
async def help_admin(m: Message):
    if await admin_salons(m.from_user.id):
        await m.answer(HELP)


@router.message(Command("addsalon"))
async def addsalon(m: Message):
    if not is_super(m.from_user.id):
        return
    p = args(m, 4)
    if not p:
        return await m.answer("Формат: /addsalon Название | Адрес | широта | долгота | Телефон | Описание")
    try:
        lat, lon = float(p[2].replace(",", ".")), float(p[3].replace(",", "."))
    except ValueError:
        return await m.answer("Широта и долгота должны быть числами, например 55.7558 и 37.6173")
    phone = p[4] if len(p) > 4 else ""
    desc = p[5] if len(p) > 5 else ""
    sid = await db.ex("insert into salons(name,address,lat,lon,phone,description,tz) values(?,?,?,?,?,?,?)",
                      (p[0], p[1], lat, lon, phone, desc, DEFAULT_TZ))
    await m.answer(f"✅ Салон создан, ID = <b>{sid}</b>\nСсылка для клиентов: t.me/ИМЯ_БОТА?start=s{sid}\n"
                   f"Дальше: /addadmin {sid} | ID, /addmaster {sid} | Имя")


@router.message(Command("addadmin"))
async def addadmin(m: Message):
    if not is_super(m.from_user.id):
        return
    p = args(m, 2)
    if not p or not p[0].isdigit() or not p[1].isdigit():
        return await m.answer("Формат: /addadmin ID_салона | Telegram_ID")
    await db.ex("insert into admins values(?,?) on conflict do nothing", (int(p[1]), int(p[0])))
    await m.answer("✅ Админ добавлен. Пусть он нажмёт /start у бота, затем /admin")


@router.message(Command("deladmin"))
async def deladmin(m: Message):
    if not is_super(m.from_user.id):
        return
    p = args(m, 2)
    if p and p[0].isdigit() and p[1].isdigit():
        await db.ex("delete from admins where user_id=? and salon_id=?", (int(p[1]), int(p[0])))
        await m.answer("✅ Удалён")


@router.message(Command("delsalon"))
async def delsalon(m: Message):
    if not is_super(m.from_user.id):
        return
    p = args(m, 1)
    if p and p[0].isdigit():
        await db.ex("update salons set active=0 where id=?", (int(p[0]),))
        await m.answer("✅ Салон скрыт")


@router.message(Command("salons"))
async def salons(m: Message):
    ss = await admin_salons(m.from_user.id)
    if not ss:
        return
    await m.answer("\n".join(f"#{s['id']} {html.escape(s['name'])} ({s['tz']}, возврат через {s['return_days']} дн.)" for s in ss))


@router.message(Command("info"))
async def info(m: Message):
    p = args(m, 1)
    if not p or not p[0].isdigit() or not await can_manage(m.from_user.id, int(p[0])):
        return
    sid = int(p[0])
    out = []
    for ma in await db.q("select * from masters where salon_id=? and active=1", (sid,)):
        out.append(f"\n👩 <b>#{ma['id']} {html.escape(ma['name'])}</b> (календарь: {html.escape(ma['calendar_id'] or 'нет')})")
        for s in await db.q("select * from services where master_id=? and active=1", (ma["id"],)):
            out.append(f"   ✂️ #{s['id']} {html.escape(s['name'])} — {html.escape(s['price'])}, {s['duration']} мин")
        sch = await db.q("select * from schedules where master_id=? order by weekday,t_from", (ma["id"],))
        out.append("   🕒 " + ("; ".join(f"{DN[r['weekday']]} {r['t_from']}-{r['t_to']}" for r in sch) or "график не задан"))
    await m.answer("\n".join(out) or "Мастеров пока нет. /addmaster")


@router.message(Command("addmaster"))
async def addmaster(m: Message):
    p = args(m, 2)
    if not p or not p[0].isdigit() or not await can_manage(m.from_user.id, int(p[0])):
        return await m.answer("Формат: /addmaster ID_салона | Имя")
    mid = await db.ex("insert into masters(salon_id,name) values(?,?)", (int(p[0]), p[1]))
    await m.answer(f"✅ Мастер создан, ID = <b>{mid}</b>\nДальше: /addservice {mid} | Стрижка | 1500 ₽ | 60\n"
                   f"и /schedule {mid} | пн-пт 10:00-19:00")


@router.message(Command("addservice"))
async def addservice(m: Message):
    p = args(m, 4)
    if not p or not p[0].isdigit() or not p[3].isdigit():
        return await m.answer("Формат: /addservice ID_мастера | Услуга | Цена | Минут")
    sid = await salon_of_master(int(p[0]))
    if not sid or not await can_manage(m.from_user.id, sid):
        return
    await db.ex("insert into services(master_id,name,price,duration) values(?,?,?,?)", (int(p[0]), p[1], p[2], int(p[3])))
    await m.answer("✅ Услуга добавлена")


def parse_schedule(s):
    out = []
    for chunk in s.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        dpart, _, tpart = chunk.partition(" ")
        dpart = dpart.lower()
        if "-" in dpart:
            a, b = dpart.split("-")
            i, j = DAYS[a], DAYS[b]
            days = list(range(i, j + 1)) if i <= j else list(range(i, 7)) + list(range(0, j + 1))
        else:
            days = [DAYS[x] for x in dpart.split(",")]
        for iv in tpart.replace(" ", "").split(","):
            a, b = iv.split("-")
            datetime.strptime(a, "%H:%M"), datetime.strptime(b, "%H:%M")
            for d in days:
                out.append((d, a.zfill(5), b.zfill(5)))
    return out


@router.message(Command("schedule"))
async def schedule(m: Message):
    p = args(m, 2)
    if not p or not p[0].isdigit():
        return await m.answer("Формат: /schedule ID_мастера | пн-пт 10:00-14:00,15:00-19:00; сб 10:00-16:00")
    mid = int(p[0])
    sid = await salon_of_master(mid)
    if not sid or not await can_manage(m.from_user.id, sid):
        return
    try:
        rows = parse_schedule(p[1])
    except Exception:
        return await m.answer("Не понял график. Пример: пн-пт 10:00-19:00; сб 10:00-16:00 (дни: пн вт ср чт пт сб вс)")
    await db.ex("delete from schedules where master_id=?", (mid,))
    for d, a, b in rows:
        await db.ex("insert into schedules values(?,?,?,?)", (mid, d, a, b))
    await m.answer("✅ График сохранён. Остальные дни — выходные.")


@router.message(Command("setcal"))
async def setcal(m: Message):
    p = args(m, 2)
    if not p or not p[0].isdigit():
        return await m.answer("Формат: /setcal ID_мастера | calendar_id")
    sid = await salon_of_master(int(p[0]))
    if sid and await can_manage(m.from_user.id, sid):
        await db.ex("update masters set calendar_id=? where id=?", (p[1], int(p[0])))
        await m.answer("✅ Календарь привязан. Новые подтверждённые записи попадут в Google Календарь.")


@router.message(Command("delmaster"))
async def delmaster(m: Message):
    p = args(m, 1)
    if p and p[0].isdigit():
        sid = await salon_of_master(int(p[0]))
        if sid and await can_manage(m.from_user.id, sid):
            await db.ex("update masters set active=0 where id=?", (int(p[0]),))
            await m.answer("✅ Мастер скрыт")


@router.message(Command("delservice"))
async def delservice(m: Message):
    p = args(m, 1)
    if p and p[0].isdigit():
        r = await db.q1("select m.salon_id from services s join masters m on m.id=s.master_id where s.id=?", (int(p[0]),))
        if r and await can_manage(m.from_user.id, r["salon_id"]):
            await db.ex("update services set active=0 where id=?", (int(p[0]),))
            await m.answer("✅ Услуга скрыта")


@router.message(Command("returndays"))
async def returndays(m: Message):
    p = args(m, 2)
    if p and p[0].isdigit() and p[1].isdigit() and await can_manage(m.from_user.id, int(p[0])):
        await db.ex("update salons set return_days=? where id=?", (int(p[1]), int(p[0])))
        await m.answer("✅ Готово")


@router.message(Command("tz"))
async def tzcmd(m: Message):
    p = args(m, 2)
    if p and p[0].isdigit() and await can_manage(m.from_user.id, int(p[0])):
        try:
            ZoneInfo(p[1])
        except Exception:
            return await m.answer("Неизвестный часовой пояс. Пример: Europe/Moscow, Asia/Almaty, Europe/Kyiv")
        await db.ex("update salons set tz=? where id=?", (p[1], int(p[0])))
        await m.answer("✅ Готово")


# ---------- панель ----------
def panel_kb(lang, sid):
    return ikb([[(t(lang, "b_pending"), f"al:pending:{sid}")],
                [(t(lang, "b_today"), f"al:today:{sid}"), (t(lang, "b_tomorrow"), f"al:tomorrow:{sid}")]])


@router.message(Command("admin"))
async def admin_cmd(m: Message, lang):
    ss = await admin_salons(m.from_user.id)
    if not ss:
        return await m.answer(t(lang, "not_admin"))
    if len(ss) == 1:
        return await m.answer(t(lang, "a_panel", salon=ss[0]["name"]), reply_markup=panel_kb(lang, ss[0]["id"]))
    await m.answer("🛠", reply_markup=ikb([[(s["name"], f"ap:{s['id']}")] for s in ss]))


@router.callback_query(F.data.startswith("ap:"))
async def ap(cb: CallbackQuery, lang):
    sid = int(cb.data[3:])
    if await can_manage(cb.from_user.id, sid):
        s = await db.q1("select name from salons where id=?", (sid,))
        await show(cb, t(lang, "a_panel", salon=s["name"]), panel_kb(lang, sid))


def booking_kb(lang, b):
    if b["status"] == "pending":
        return ikb([[(t(lang, "b_ok"), f"a:ok:{b['id']}"), (t(lang, "b_no"), f"a:no:{b['id']}")]])
    if b["status"] == "confirmed":
        return ikb([[(t(lang, "b_no"), f"a:no:{b['id']}")]])
    return None


@router.callback_query(F.data.startswith("al:"))
async def al(cb: CallbackQuery, lang):
    _, kind, sid = cb.data.split(":")
    sid = int(sid)
    if not await can_manage(cb.from_user.id, sid):
        return await cb.answer()
    s = await db.q1("select tz from salons where id=?", (sid,))
    now = now_in(s["tz"])
    base = """select b.id,b.t_start,b.status,b.client_name,ma.name mname,sv.name svc from bookings b
      join masters ma on ma.id=b.master_id join services sv on sv.id=b.service_id where b.salon_id=? """
    if kind == "pending":
        rows = await db.q(base + "and b.status='pending' and b.t_start>=? order by b.t_start limit 20", (sid, now.strftime(FMT)))
    else:
        d = now.date() + timedelta(days=1 if kind == "tomorrow" else 0)
        rows = await db.q(base + "and b.status in ('pending','confirmed') and b.t_start>=? and b.t_start<? order by b.t_start",
                          (sid, f"{d} 00:00", f"{d + timedelta(days=1)} 00:00"))
    await cb.answer()
    if not rows:
        return await cb.message.answer(t(lang, "a_none"))
    for r in rows:
        await cb.message.answer(
            t(lang, "a_line", id=r["id"], when=datetime.strptime(r["t_start"], FMT), master=r["mname"], client=r["client_name"],
              service=r["svc"], status=t(lang, "st_" + r["status"])), reply_markup=booking_kb(lang, r))


@router.callback_query(F.data.startswith("a:"))
async def a_action(cb: CallbackQuery, bot: Bot, lang):
    _, act, bid = cb.data.split(":")
    bid = int(bid)
    b = await booking_ctx(bid)
    if not b or not await can_manage(cb.from_user.id, b["salon_id"]):
        return await cb.answer()
    if act == "ok":
        await confirm(bot, bid)
    else:
        await reject(bot, bid)
    b = await booking_ctx(bid)
    await show(cb, t(lang, "a_handled", id=bid, status=t(lang, "st_" + b["status"])))
