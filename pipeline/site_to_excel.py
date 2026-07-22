# -*- coding: utf-8 -*-
"""مزامنة Excel من بيانات الموقع الحيّة → يبقي مصدر Power BI محدّثًا.

يقرأ بيانات الموقع (الحيّة افتراضيًا، أو public/index.html بـ --local)، يحوّلها إلى مخطط
أعمدة Power BI الـ13، ثم يدمجها مع ملف Excel الحالي:
  • يبقي كل صفوف Excel الحالية كما هي (محافظًا على «نوع الحدث» و«التقييم الإستراتيجي»).
  • يضيف فقط أحداث الموقع غير الموجودة (إزالة تكرار بالتاريخ+الكيان+نص الحدث).
النتيجة تُكتب إلى ملف Excel نفسه الذي يستورده Power BI — فيكفي بعدها ضغط Refresh.

تشغيل:  python pipeline/site_to_excel.py            (من الموقع الحيّ)
        python pipeline/site_to_excel.py --local    (من public/index.html المحلي)
"""
import os, re, sys, json, io, datetime, urllib.request
import pandas as pd

# اجعل الطباعة تعمل بـUTF-8 حتى بلا وحدة تحكّم (تشغيل مجدول)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
_LOG = os.path.join(HERE, "sync_excel.log")


def logline(msg):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line)
    try:
        with io.open(_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
LOCAL_SITE = os.path.join(os.path.dirname(HERE), "public", "index.html")
LIVE_URL = "https://famous-biscochitos-e29381.netlify.app/"
EXCEL = r"C:/Users/roa44/OneDrive/Työpöytä/مرصد الشرق الأوسط/Power BI و Excel/بيانات الأحداث الإقليمية (محدثة حتى 2026-07-21).xlsx"

COLS = ["التاريخ", "الدولة / الكيان", "المدينة / المنطقة", "خط العرض", "خط الطول",
        "طبيعة الحدث", "نوع الحدث", "درجة المخاطر", "الحدث الرئيسي", "تفاصيل الحدث",
        "التقييم الإستراتيجي", "الفئة الرئيسية", "المصدر"]
RISK = {0: "حرج", 1: "مرتفع جداً", 2: "مرتفع", 3: "متوسط", 4: "منخفض", 5: "غير محدد"}


def load_ev():
    if "--local" in sys.argv:
        html = open(LOCAL_SITE, encoding="utf-8").read()
        print("المصدر: public/index.html المحلي")
    else:
        req = urllib.request.Request(LIVE_URL + "?sync", headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
        print("المصدر: الموقع الحيّ")
    return json.loads(re.search(r'<script id="EV" type="application/json">(.*?)</script>', html, re.S).group(1))


def key(date_iso, entity, event):
    head = str(entity).split("/")[0].strip()
    body = re.sub(r"\W+", "", str(event).lower())[:55]
    return f"{date_iso}|{head}|{body}"


def ev_to_rows(ev):
    ents, nat = ev["ents"], ev["nat"]
    out = []
    for r in ev["rows"]:
        d = r[0]
        date_iso = f"20{d[0:2]}-{d[2:4]}-{d[4:6]}"
        nats = [nat[i] for i in range(len(nat)) if r[6] & (1 << i)]
        nature = " / ".join(nats) if nats else "غير محدد"
        out.append({
            "التاريخ": pd.Timestamp(date_iso),
            "الدولة / الكيان": ents[r[1]],
            "المدينة / المنطقة": r[2],
            "خط العرض": r[3], "خط الطول": r[4],
            "طبيعة الحدث": nature,
            "نوع الحدث": None,
            "درجة المخاطر": RISK.get(r[8], "غير محدد"),
            "الحدث الرئيسي": r[9],
            "تفاصيل الحدث": (r[10] or None),
            "التقييم الإستراتيجي": None,
            "الفئة الرئيسية": (nats[0] if nats else "غير محدد"),
            "المصدر": (r[12] if len(r) > 12 else None) or None,
        })
    return out


def main():
    ev = load_ev()
    site_rows = ev_to_rows(ev)
    print("أحداث الموقع:", len(site_rows))

    base = pd.read_excel(EXCEL)
    for c in COLS:
        if c not in base.columns:
            base[c] = None
    base = base[COLS]
    print("صفوف Excel الحالية:", len(base))

    seen = set()
    for _, r in base.iterrows():
        seen.add(key(str(r["التاريخ"])[:10], r["الدولة / الكيان"], r["الحدث الرئيسي"]))

    new = []
    for r in site_rows:
        k = key(str(r["التاريخ"])[:10], r["الدولة / الكيان"], r["الحدث الرئيسي"])
        if k not in seen:
            seen.add(k)
            new.append(r)
    print("أحداث جديدة من الموقع:", len(new))

    if new:
        merged = pd.concat([base, pd.DataFrame(new)], ignore_index=True)
        merged = merged.sort_values("التاريخ").reset_index(drop=True)
        merged.to_excel(EXCEL, index=False, sheet_name="Sheet1")
        logline(f"OK: كُتب Excel {len(base)} → {len(merged)} صفًا | آخر تاريخ {merged['التاريخ'].max().date()} (افتح Power BI واضغط Refresh)")
    else:
        logline("OK: لا جديد — Excel متزامن مع الموقع.")


if __name__ == "__main__":
    try:
        logline("── بدء المزامنة ──")
        main()
    except Exception as e:
        logline(f"خطأ: {type(e).__name__}: {e}")
        raise
