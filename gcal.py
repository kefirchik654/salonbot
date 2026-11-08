"""Google Calendar: создаёт/удаляет события. Работает, только если есть data/google.json."""
import asyncio
import json
import logging
import os
from config import GOOGLE_CREDENTIALS, GOOGLE_CREDENTIALS_JSON

log = logging.getLogger("gcal")
_svc = None


def _service():
    global _svc
    if _svc:
        return _svc
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    scopes = ["https://www.googleapis.com/auth/calendar"]
    if GOOGLE_CREDENTIALS_JSON.strip():
        creds = service_account.Credentials.from_service_account_info(json.loads(GOOGLE_CREDENTIALS_JSON), scopes=scopes)
    elif os.path.exists(GOOGLE_CREDENTIALS):
        creds = service_account.Credentials.from_service_account_file(GOOGLE_CREDENTIALS, scopes=scopes)
    else:
        return None
    _svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _svc


def _create(cal_id, summary, desc, start, end, tz):
    svc = _service()
    if not svc or not cal_id:
        return None
    body = {"summary": summary, "description": desc,
            "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": tz},
            "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": tz}}
    return svc.events().insert(calendarId=cal_id, body=body).execute()["id"]


def _delete(cal_id, event_id):
    svc = _service()
    if svc and cal_id and event_id:
        svc.events().delete(calendarId=cal_id, eventId=event_id).execute()


async def create_event(cal_id, summary, desc, start, end, tz):
    try:
        return await asyncio.to_thread(_create, cal_id, summary, desc, start, end, tz)
    except Exception as e:
        log.warning("Google Calendar create failed: %s", e)
        return None


async def delete_event(cal_id, event_id):
    try:
        await asyncio.to_thread(_delete, cal_id, event_id)
    except Exception as e:
        log.warning("Google Calendar delete failed: %s", e)
