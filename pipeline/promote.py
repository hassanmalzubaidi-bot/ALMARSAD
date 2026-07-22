# -*- coding: utf-8 -*-
"""④ الاعتماد والنشر: يطبّق قرارات الأدمن على الطابور ويحدّث الموقع العام.

يقرأ data/pending.json حيث لكل عنصر حقل «_حالة»:
  «معتمد»  → يُحقن في public/index.html (يصبح عامًّا) ويُزال من الطابور.
  «مرفوض»  → يُزال من الطابور (يُهمَل).
  «معلّق»   → يبقى في الطابور بانتظار القرار.
تشغيل: python pipeline/promote.py   (بعد أن يعتمد الأدمن العناصر)
"""
import json, os, sys, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import classify as CL

ORGS = {"حماس", "حزب الله", "الحوثيون", "الناتو", "الاتحاد الأوروبي", "الأمم المتحدة", "داعش"}
REG = {"البحر الأحمر", "مضيق هرمز", "الشرق الأوسط", "الخليج"}


def ent_index(data, name):
    name = str(name).split("/")[0].strip()
    if name in data["ents"]:
        return data["ents"].index(name)
    data["ents"].append(name)
    data["kinds"].append("org" if name in ORGS else ("region" if name in REG else "state"))
    return len(data["ents"]) - 1


def to_row(data, ev):
    lat, lon, prec = CL.geocode(ev.get("المدينة"), ev["الدولة"])
    prov = C.PROV_AI if str(ev.get("المصدر", "")).startswith("دفعة ذكاء") else C.PROV_OPEN
    return [
        CL.date_compact(ev["التاريخ"]), ent_index(data, ev["الدولة"]), (ev.get("المدينة") or "عام"),
        round(float(lat), 4), round(float(lon), 4), prec, CL.nat_mask(ev.get("طبيعة", "أخرى")),
        CL.scope_idx(ev.get("نطاق", "غير مصنّف")), CL.risk_idx(ev.get("خطر", "غير محدد")),
        ev["الحدث"], ev.get("التفاصيل") or "", prov, ev.get("المصدر", "مصدر مفتوح"),
        1 if prov == C.PROV_OPEN else 0,
    ]


def main():
    pending = json.load(open(C.PENDING, encoding="utf-8"))
    approved = [e for e in pending if e.get("_حالة") == "معتمد"]
    rejected = [e for e in pending if e.get("_حالة") == "مرفوض"]
    remaining = [e for e in pending if e.get("_حالة") not in ("معتمد", "مرفوض")]

    if not approved and not rejected:
        print("لا قرارات جديدة (لا معتمد ولا مرفوض). لا تغيير.")
        return 0

    html = open(C.SITE, encoding="utf-8").read()
    m = re.search(r'(<script id="EV" type="application/json">)(.*?)(</script>)', html, re.S)
    data = json.loads(m.group(2))

    for ev in approved:
        data["rows"].append(to_row(data, ev))
    data["rows"].sort(key=lambda r: r[0])
    total = len(data["rows"])

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = html[:m.start(2)] + payload + html[m.end(2):]
    html = re.sub(r"رصد [\d,٬]+ حدثًا", f"رصد {total:,} حدثًا", html)
    open(C.SITE, "w", encoding="utf-8").write(html)

    json.dump(remaining, open(C.PENDING, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # تحقق سلامة
    chk = json.loads(re.search(r'<script id="EV" type="application/json">(.*?)</script>',
                               open(C.SITE, encoding="utf-8").read(), re.S).group(1))
    assert len(chk["rows"]) == total and len(chk["ents"]) == len(chk["kinds"])
    print(f"✓ اعتُمد ونُشر: {len(approved)} | رُفض وأُهمِل: {len(rejected)} | باقٍ في الطابور: {len(remaining)} | إجمالي الموقع: {total}")
    return len(approved)


if __name__ == "__main__":
    main()
