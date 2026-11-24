"""
قفل وفتح الجروب بمواعيد - بيشتغل على GitHub Actions من غير ما جهازك يكون شغال.
مفيش مكتبات تتنزّل: بيستخدم بايثون العادي بس.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, time
from zoneinfo import ZoneInfo

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}/"

# اسم الصلاحية في config.json  ->  اسمها في تليجرام
TYPES = {
    "messages": "can_send_messages",
    "photos": "can_send_photos",
    "videos": "can_send_videos",
    "documents": "can_send_documents",
    "audios": "can_send_audios",
    "voice": "can_send_voice_notes",
    "video_notes": "can_send_video_notes",
    "polls": "can_send_polls",
    "stickers": "can_send_other_messages",
    "link_previews": "can_add_web_page_previews",
    "reactions": "can_react_to_messages",
}
# صلاحيات مش بنلمسها، بنسيبها زي ما هي في الجروب
KEEP_FIELDS = [
    "can_change_info", "can_invite_users", "can_pin_messages",
    "can_manage_topics", "can_edit_tag",
]


def api(method, **params):
    req = urllib.request.Request(
        API + method,
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        data = json.load(e)
    if not data.get("ok"):
        raise RuntimeError(f"{method}: {data.get('description')}")
    return data["result"]


def parse_hhmm(text):
    return datetime.strptime(text.strip(), "%H:%M").time()


def in_lock_window(lock: time, unlock: time, now: time) -> bool:
    if lock == unlock:
        return False
    if lock < unlock:
        return lock <= now < unlock
    return now >= lock or now < unlock  # الفترة بتعدي نص الليل


def build_permissions(perms, cfg, locked_now):
    """بيحسب الصلاحيات المطلوبة:
    always_open  -> مفتوحة دايمًا
    always_closed -> مقفولة دايمًا
    lock          -> بتتقفل وقت القفل وتتفتح وقت الفتح
    أي حاجة تانية -> بتفضل زي ما هي في الجروب"""
    always_open = set(cfg.get("always_open", []))
    always_closed = set(cfg.get("always_closed", []))
    lock = set(cfg.get("lock", []))

    desired = {}
    for key, field in TYPES.items():
        if key in always_closed:
            desired[field] = False
        elif key in always_open:
            desired[field] = True
        elif key in lock:
            desired[field] = not locked_now
        else:
            desired[field] = bool(perms.get(field))

    new = dict(desired)
    for f in KEEP_FIELDS:
        new[f] = bool(perms.get(f))
    return desired, new


def process_chat(chat_id, cfg, locked_now):
    chat = api("getChat", chat_id=chat_id)
    perms = chat.get("permissions", {})

    lock_fields = [TYPES[k] for k in cfg.get("lock", []) if k in TYPES]
    current_locked = any(not perms.get(f) for f in lock_fields)

    desired, new = build_permissions(perms, cfg, locked_now)
    changes = [f for f, v in desired.items() if bool(perms.get(f)) != v]
    if not changes:
        print(f"[{chat_id}] already correct, nothing to do")
        return

    api("setChatPermissions", chat_id=chat_id, permissions=new,
        use_independent_chat_permissions=True)
    print(f"[{chat_id}] updated: {', '.join(changes)}")

    # بنبعت رسالة بس لما القفل أو الفتح يتغيّر فعلًا
    if cfg.get("announce", True) and current_locked != locked_now:
        text = cfg["lock_message"] if locked_now else cfg["unlock_message"]
        api("sendMessage", chat_id=chat_id, text=text)


def find_chats():
    """بيطبع الجروبات اللي البوت شافها، عشان تاخد الآي دي."""
    updates = api("getUpdates", timeout=0, allowed_updates=["message", "my_chat_member"])
    seen = {}
    for u in updates:
        for key in ("message", "my_chat_member"):
            chat = (u.get(key) or {}).get("chat")
            if chat and chat.get("type") in ("group", "supergroup"):
                seen[chat["id"]] = chat.get("title", "")
    if not seen:
        print("مفيش جروبات ظاهرة. ضيف البوت للجروب، ابعت فيه أي رسالة، وشغّل ده تاني.")
    for cid, title in seen.items():
        print(f"GROUP: {title}  ->  ID: {cid}")


def main():
    if not TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN is missing (Secrets)")
    if len(sys.argv) > 1 and sys.argv[1] == "find":
        find_chats()
        return

    with open(os.path.join(os.path.dirname(__file__), "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)

    now = datetime.now(ZoneInfo(cfg["timezone"])).time()
    locked_now = in_lock_window(parse_hhmm(cfg["lock_time"]), parse_hhmm(cfg["unlock_time"]), now)
    print(f"now={now:%H:%M} schedule says: {'LOCKED' if locked_now else 'OPEN'}")

    failed = False
    for chat_id in cfg["chats"]:
        try:
            process_chat(chat_id, cfg, locked_now)
        except Exception as e:
            failed = True
            print(f"[{chat_id}] ERROR: {e}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
