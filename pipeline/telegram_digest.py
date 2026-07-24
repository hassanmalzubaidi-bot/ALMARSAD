# -*- coding: utf-8 -*-
"""موجز تيليجرام اليومي للمرصد: أبرز أحداث اليوم + رابط الموقع.

يقرأ بيانات EV من public/index.html مباشرة (لا شبكة للجلب)، ويرسل عبر Bot API.
الأسرار من البيئة: TELEGRAM_TOKEN و CHAT_ID — إن غابت يتخطى بهدوء (exit 0)
حتى لا يفشل سير العمل قبل ضبطها. DIGEST_MODE=diagnose يطبع دون إرسال.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "public", "index.html")
SITE_URL = "https://almarsadme.com"
RIYADH_TZ = timezone(timedelta(hours=3))

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
MODE = os.environ.get("DIGEST_MODE", "send")

RN = ["حرج", "مرتفع جداً", "مرتفع", "متوسط", "منخفض", "غير محدد"]
RE_EMOJI = ["🔴", "🟠", "🟠", "🟡", "🟢", "⚪"]


def load_data():
    html = open(SITE, encoding="utf-8").read()
    return json.loads(re.search(
        r'<script id="EV" type="application/json">(.*?)</script>', html, re.S).group(1))


def build_message(d, now_riyadh):
    ents, rows = d["ents"], d["rows"]
    # يوم الموجز = أحدث يوم في البيانات (يتحمل تأخر جولة النشر عن منتصف الليل)
    latest = max(r[0] for r in rows)
    day_rows = [r for r in rows if r[0] == latest]
    sev = sorted([r for r in day_rows if r[8] <= 1], key=lambda r: r[8])
    total_sev = len(sev)
    date_iso = f"20{latest[0:2]}-{latest[2:4]}-{latest[4:6]}"

    lines = [
        "🛡️ *مرصد الشرق الأوسط — الموجز اليومي*",
        f"🗓️ {date_iso} · 📊 {len(day_rows)} حدثًا مرصودًا"
        + (f" · منها {total_sev} حرج/مرتفع جدًا" if total_sev else ""),
        "",
    ]
    top = sev[:6] if sev else sorted(day_rows, key=lambda r: r[8])[:6]
    for r in top:
        title = str(r[9]).strip().replace("*", "").replace("_", "").replace("[", "").replace("]", "")
        if len(title) > 130:
            title = title[:127] + "…"
        lines.append(f"{RE_EMOJI[r[8]]} *{ents[r[1]]}* — {title}")
    lines += [
        "",
        f"🗺️ الخريطة والتفاصيل: {SITE_URL}",
        "⏱️ يُحدَّث آليًا مرتين يوميًا",
    ]
    return "\n".join(lines)


def send(message):
    import requests
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown",
              "disable_web_page_preview": True},
        timeout=20,
    )
    if r.status_code != 200:
        print(f"خطأ تيليجرام: {r.status_code} - {r.text}")
        return False
    return True


def main():
    now_riyadh = datetime.now(timezone.utc).astimezone(RIYADH_TZ)
    d = load_data()
    msg = build_message(d, now_riyadh)
    print("----- الموجز -----")
    print(msg)
    if MODE == "diagnose":
        print("----- (معاينة فقط — لم يُرسل) -----")
        return
    if not TOKEN or not CHAT_ID:
        print("تخطٍّ: أسرار TELEGRAM_TOKEN/CHAT_ID غير مضبوطة في المستودع — لم يُرسل شيء.")
        return
    ok = send(msg)
    print("أُرسل ✓" if ok else "فشل الإرسال ✗")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
