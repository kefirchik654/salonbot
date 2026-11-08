"""Тексты. Русский и английский - вручную. Остальные языки - автоперевод с английского (Google Translate)
при первом обращении пользователя, затем кэшируются в базе."""
import asyncio
import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from babel.dates import format_date

import db

log = logging.getLogger("i18n")

RU = {
 "start": "👋 Привет, {name}! Я помогу записаться в салон красоты или барбершоп. Что хотите сделать?",
 "m_salons": "💈 Найти салон", "m_map": "🗺 Салоны на карте", "m_my": "📅 Мои записи", "m_lang": "🌐 Язык",
 "pick_salon": "Выберите салон:", "no_salons": "Пока нет добавленных салонов.",
 "salon_card": "<b>{name}</b>\n📍 {address}\n{phone_line}\n\n{description}",
 "b_book": "✂️ Записаться", "b_masters": "👩‍🎤 Мастера и услуги", "b_route": "📍 Показать на карте", "b_back": "⬅️ Назад",
 "masters_title": "Мастера и услуги:", "no_masters": "В этом салоне пока нет мастеров.",
 "svc_line": "• {name} — {price} · {dur} мин",
 "pick_master": "Выберите мастера:", "pick_service": "Выберите услугу:", "pick_date": "Выберите дату:",
 "no_dates": "Ближайшие 14 дней свободного времени нет. Попробуйте другого мастера.",
 "pick_time": "Выберите время ({date}):", "no_times": "На этот день свободного времени нет, выберите другой.",
 "confirm_q": "Проверьте запись:\n💈 {salon}\n👩 {master}\n✂️ {service} — {price}\n🕒 {when}\n\nПодтверждаем?",
 "b_confirm": "✅ Подтвердить", "b_cancel": "❌ Отмена",
 "sent_pending": "✅ Заявка #{id} отправлена! Салон скоро подтвердит запись, я сразу напишу вам. 💛",
 "slot_taken": "Увы, это время только что заняли. Выберите другое.",
 "confirmed_msg": "🎉 Запись #{id} подтверждена!\n💈 {salon}\n👩 {master}\n✂️ {service}\n🕒 {when}\n📍 {address}",
 "rejected_msg": "😔 К сожалению, салон не смог принять запись #{id} на {when}. Выберите, пожалуйста, другое время.",
 "my_none": "У вас нет предстоящих записей.",
 "my_line": "#{id} · {when}\n💈 {salon} · {master} · {service}\n{status}",
 "st_pending": "⏳ ждёт подтверждения", "st_confirmed": "✅ подтверждена", "st_cancelled": "❌ отменена", "st_rejected": "🚫 отклонена",
 "b_cancel_bk": "❌ Отменить запись #{id}", "cancelled_ok": "Запись #{id} отменена.",
 "rem24": "⏰ Напоминание: {when} вас ждут в «{salon}» ({service}, мастер {master}). До встречи! 💛",
 "rem2": "⏰ Ждём вас через 2 часа — {when}, «{salon}». Адрес: {address}",
 "b_come": "👍 Приду", "b_resched": "🔁 Перенести", "come_ok": "Отлично, ждём вас! 💛",
 "winback": "Привет, {name}! 💛 Давно не виделись в «{salon}». Пора освежить образ? Выберите удобное время:",
 "b_book_now": "✂️ Записаться",
 "stop_ok": "Хорошо, больше не буду напоминать о визитах. Вернуть: /resume", "resume_ok": "Напоминания снова включены 💛",
 "lang_pick": "Выберите язык (или напишите /lang и код языка, например /lang ka):", "lang_set": "Язык изменён ✅",
 "a_panel": "🛠 Панель администратора: {salon}", "b_today": "📅 Сегодня", "b_tomorrow": "📆 Завтра", "b_pending": "⏳ Ждут подтверждения",
 "a_none": "Здесь пока пусто.", "not_admin": "Вы не администратор ни одного салона.",
 "a_new": "🆕 Новая запись #{id}\n👤 {client}\n👩 {master}\n✂️ {service}\n🕒 {when}",
 "b_ok": "✅ Подтвердить", "b_no": "🚫 Отклонить",
 "a_line": "#{id} · {when} · {master}\n👤 {client} · {service}\n{status}",
 "a_cancelled_by_client": "❌ Клиент {client} отменил запись #{id} ({when}).",
 "a_handled": "Запись #{id}: {status}",
}

EN = {
 "start": "👋 Hi, {name}! I'll help you book a beauty salon or barbershop. What would you like to do?",
 "m_salons": "💈 Find a salon", "m_map": "🗺 Salons on the map", "m_my": "📅 My bookings", "m_lang": "🌐 Language",
 "pick_salon": "Choose a salon:", "no_salons": "No salons have been added yet.",
 "salon_card": "<b>{name}</b>\n📍 {address}\n{phone_line}\n\n{description}",
 "b_book": "✂️ Book", "b_masters": "👩‍🎤 Masters & services", "b_route": "📍 Show on map", "b_back": "⬅️ Back",
 "masters_title": "Masters and services:", "no_masters": "This salon has no masters yet.",
 "svc_line": "• {name} — {price} · {dur} min",
 "pick_master": "Choose a master:", "pick_service": "Choose a service:", "pick_date": "Choose a date:",
 "no_dates": "No free time in the next 14 days. Try another master.",
 "pick_time": "Choose a time ({date}):", "no_times": "No free time on that day, please pick another.",
 "confirm_q": "Please check your booking:\n💈 {salon}\n👩 {master}\n✂️ {service} — {price}\n🕒 {when}\n\nConfirm?",
 "b_confirm": "✅ Confirm", "b_cancel": "❌ Cancel",
 "sent_pending": "✅ Request #{id} sent! The salon will confirm it shortly and I'll message you right away. 💛",
 "slot_taken": "Sorry, this time was just taken. Please choose another.",
 "confirmed_msg": "🎉 Your booking #{id} is confirmed!\n💈 {salon}\n👩 {master}\n✂️ {service}\n🕒 {when}\n📍 {address}",
 "rejected_msg": "😔 Sorry, the salon couldn't accept booking #{id} for {when}. Please choose another time.",
 "my_none": "You have no upcoming bookings.",
 "my_line": "#{id} · {when}\n💈 {salon} · {master} · {service}\n{status}",
 "st_pending": "⏳ waiting for confirmation", "st_confirmed": "✅ confirmed", "st_cancelled": "❌ cancelled", "st_rejected": "🚫 declined",
 "b_cancel_bk": "❌ Cancel booking #{id}", "cancelled_ok": "Booking #{id} cancelled.",
 "rem24": "⏰ Reminder: you have an appointment on {when} at {salon} ({service}, master {master}). See you! 💛",
 "rem2": "⏰ See you in 2 hours — {when} at {salon}. Address: {address}",
 "b_come": "👍 I'll be there", "b_resched": "🔁 Reschedule", "come_ok": "Great, see you! 💛",
 "winback": "Hi, {name}! 💛 It's been a while since your last visit to {salon}. Time for a fresh look? Pick a time that suits you:",
 "b_book_now": "✂️ Book now",
 "stop_ok": "Okay, I won't send return reminders anymore. To turn back on: /resume", "resume_ok": "Reminders are on again 💛",
 "lang_pick": "Choose a language (or type /lang and a language code, e.g. /lang ka):", "lang_set": "Language changed ✅",
 "a_panel": "🛠 Admin panel: {salon}", "b_today": "📅 Today", "b_tomorrow": "📆 Tomorrow", "b_pending": "⏳ Awaiting confirmation",
 "a_none": "Nothing here yet.", "not_admin": "You are not an admin of any salon.",
 "a_new": "🆕 New booking #{id}\n👤 {client}\n👩 {master}\n✂️ {service}\n🕒 {when}",
 "b_ok": "✅ Confirm", "b_no": "🚫 Decline",
 "a_line": "#{id} · {when} · {master}\n👤 {client} · {service}\n{status}",
 "a_cancelled_by_client": "❌ Client {client} cancelled booking #{id} ({when}).",
 "a_handled": "Booking #{id}: {status}",
}

LANGS = [("🇷🇺 Русский", "ru"), ("🇬🇧 English", "en"), ("🇺🇦 Українська", "uk"), ("🇩🇪 Deutsch", "de"),
         ("🇪🇸 Español", "es"), ("🇫🇷 Français", "fr"), ("🇮🇹 Italiano", "it"), ("🇵🇹 Português", "pt"),
         ("🇹🇷 Türkçe", "tr"), ("🇵🇱 Polski", "pl"), ("🇳🇱 Nederlands", "nl"), ("🇰🇿 Қазақша", "kk"),
         ("🇺🇿 Oʻzbekcha", "uz"), ("🇸🇦 العربية", "ar"), ("🇨🇳 中文", "zh-CN"), ("🇮🇳 हिन्दी", "hi"),
         ("🇯🇵 日本語", "ja"), ("🇰🇷 한국어", "ko")]

_mem = {"ru": RU, "en": EN}
_locks = {}
_pool = ThreadPoolExecutor(8)


def norm_lang(code):
    c = (code or "en").lower().replace("_", "-")
    if c.startswith("zh"):
        return "zh-TW" if ("hant" in c or "tw" in c or "hk" in c) else "zh-CN"
    if c == "iw":
        return "he"
    return c.split("-")[0]


def _tags(s):
    return sorted(re.findall(r"\{\w+\}|</?\w+>", s))


def _tr1(lang, text):
    try:
        from deep_translator import GoogleTranslator
        out = GoogleTranslator(source="en", target=lang).translate(text)
        if out and _tags(out) == _tags(text):
            return out
    except Exception as e:
        log.warning("translate %s failed: %s", lang, e)
    return None


async def ensure_lang(lang):
    if lang in _mem:
        return
    lock = _locks.setdefault(lang, asyncio.Lock())
    async with lock:
        if lang in _mem:
            return
        cache = {r["src"]: r["dst"] for r in await db.q("select src,dst from tr where lang=?", (lang,))}
        todo = [EN[k] for k in EN if EN[k] not in cache]
        if todo:
            loop = asyncio.get_running_loop()
            res = await asyncio.gather(*[loop.run_in_executor(_pool, _tr1, lang, s) for s in todo])
            for s, r in zip(todo, res):
                if r:
                    cache[s] = r
                    await db.ex("insert into tr values(?,?,?) on conflict(lang, src) do update set dst=excluded.dst", (lang, s, r))
        _mem[lang] = {k: cache.get(EN[k], EN[k]) for k in EN}


def _loc(lang):
    return lang.replace("-", "_")


def fdate(lang, d):
    try:
        return format_date(d, "EEE d MMM", locale=_loc(lang))
    except Exception:
        return format_date(d, "EEE d MMM", locale="en")


def fwhen(lang, dt):
    return f"{fdate(lang, dt.date())}, {dt:%H:%M}"


def t(lang, key, **kw):
    s = _mem.get(lang, EN).get(key) or EN.get(key, key)
    out = {}
    for k, v in kw.items():
        if isinstance(v, datetime):
            v = fwhen(lang, v)
        elif isinstance(v, date):
            v = fdate(lang, v)
        elif isinstance(v, str):
            v = html.escape(v)
        out[k] = v
    try:
        return s.format(**out)
    except Exception:
        return EN[key].format(**out)
