# -*- coding: utf-8 -*-
"""③④ الدمج والنشر المباشر: يضيف الأحداث المصنّفة مباشرةً إلى public/index.html (بلا مراجعة).

النموذج: نشر مباشر مرّتين يوميًا. إزالة التكرار تتم مقابل الموقع العام الحالي.
"""
import json, os, sys, re, difflib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import classify as CL

CLASSIFIED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "classified.json")
ORGS = {"حماس", "حزب الله", "الحوثيون", "الناتو", "الاتحاد الأوروبي", "الأمم المتحدة", "داعش"}
REG = {"البحر الأحمر", "مضيق هرمز", "الشرق الأوسط", "الخليج"}


def ent_index(data, name):
    name = str(name).split("/")[0].strip()
    if name in data["ents"]:
        return data["ents"].index(name)
    data["ents"].append(name)
    data["kinds"].append("org" if name in ORGS else ("region" if name in REG else "state"))
    return len(data["ents"]) - 1


def existing_keys(data):
    ents, keys = data["ents"], set()
    for r in data["rows"]:
        head = str(ents[r[1]]).split("/")[0].strip()
        body = re.sub(r"\W+", "", str(r[9]).lower())[:55]
        keys.add(f"{r[0]}|{head}|{body}")
    return keys


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
    new = json.load(open(CLASSIFIED, encoding="utf-8"))
    html = open(C.SITE, encoding="utf-8").read()
    m = re.search(r'(<script id="EV" type="application/json">)(.*?)(</script>)', html, re.S)
    data = json.loads(m.group(2))
    keys = existing_keys(data)

    added, skipped = [], 0
    for ev in new:
        k = CL.dedup_key(ev["الدولة"], ev["الحدث"], ev["التاريخ"])
        if k in keys:
            skipped += 1
            continue
        dc = CL.date_compact(ev["التاريخ"])
        nt = re.sub(r"\W+", " ", str(ev["الحدث"]).lower())
        if any(a[0] == dc and difflib.SequenceMatcher(None, nt, a[1]).ratio() >= 0.72 for a in added):
            skipped += 1
            continue
        added.append((dc, nt, ev))
        keys.add(k)

    for _, _, ev in added:
        data["rows"].append(to_row(data, ev))
    data["rows"].sort(key=lambda r: r[0])
    total = len(data["rows"])

    if added:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        html = html[:m.start(2)] + payload + html[m.end(2):]
        html = re.sub(r"رصد [\d,٬]+ حدثًا", f"رصد {total:,} حدثًا", html)
        open(C.SITE, "w", encoding="utf-8").write(html)
        chk = json.loads(re.search(r'<script id="EV" type="application/json">(.*?)</script>',
                                   open(C.SITE, encoding="utf-8").read(), re.S).group(1))
        assert len(chk["rows"]) == total and len(chk["ents"]) == len(chk["kinds"])

    print(f"مرشحون: {len(new)} | نُشر: {len(added)} | مكرر مُتجاوَز: {skipped} | إجمالي الموقع: {total}")
    return len(added)


if __name__ == "__main__":
    main()
