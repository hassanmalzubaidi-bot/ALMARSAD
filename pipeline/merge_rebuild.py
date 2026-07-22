# -*- coding: utf-8 -*-
"""③④ الدمج وإعادة البناء: يدمج classified.json في index.html بلا تكرار ويحدّث العدّادات."""
import json, os, sys, re, difflib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import classify as CL

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(os.path.dirname(HERE), "index.html")
CLASSIFIED = os.path.join(HERE, "classified.json")


def load_site():
    html = open(SITE, encoding="utf-8").read()
    m = re.search(r'(<script id="EV" type="application/json">)(.*?)(</script>)', html, re.S)
    return html, m, json.loads(m.group(2))


def existing_keys(data):
    ents = data["ents"]
    keys = set()
    for r in data["rows"]:
        head = str(ents[r[1]]).split("/")[0].strip()
        body = re.sub(r"\W+", "", str(r[9]).lower())[:55]
        keys.add(f"{r[0]}|{head}|{body}")
    return keys


def ent_index(data, name):
    name = str(name).split("/")[0].strip()
    if name in data["ents"]:
        return data["ents"].index(name)
    ORGS = {"حماس","حزب الله","الحوثيون","الناتو","الاتحاد الأوروبي","الأمم المتحدة","داعش"}
    REG = {"البحر الأحمر","مضيق هرمز","الشرق الأوسط","الخليج"}
    data["ents"].append(name)
    data["kinds"].append("org" if name in ORGS else ("region" if name in REG else "state"))
    return len(data["ents"]) - 1


def main(dry_run=False):
    html, m, data = load_site()
    new = json.load(open(CLASSIFIED, encoding="utf-8"))
    keys = existing_keys(data)

    added, skipped = [], 0
    for ev in new:
        k = CL.dedup_key(ev["الدولة"], ev["الحدث"], ev["التاريخ"])
        # تكرار مقابل القاعدة الحالية
        if k in keys:
            skipped += 1; continue
        # تكرار ضبابي داخل نفس اليوم مقابل ما أضفناه للتو
        dc = CL.date_compact(ev["التاريخ"])
        nt = re.sub(r"\W+", " ", str(ev["الحدث"]).lower())
        if any(a[0] == dc and difflib.SequenceMatcher(None, nt, a[1]).ratio() >= 0.72
               for a in added):
            skipped += 1; continue
        added.append((dc, nt, ev)); keys.add(k)

    rows_new = []
    for dc, _, ev in added:
        lat, lon, prec = CL.geocode(ev.get("المدينة"), ev["الدولة"])
        prov = C.PROV_AI if str(ev.get("المصدر", "")).startswith("دفعة ذكاء") else C.PROV_OPEN
        rows_new.append([
            dc, ent_index(data, ev["الدولة"]), (ev.get("المدينة") or "عام"),
            round(lat, 4), round(lon, 4), prec, CL.nat_mask(ev.get("طبيعة", "أخرى")),
            CL.scope_idx(ev.get("نطاق", "غير مصنّف")), CL.risk_idx(ev.get("خطر", "غير محدد")),
            ev["الحدث"], ev.get("التفاصيل") or "", prov, ev.get("المصدر", "مصدر مفتوح"),
            1 if prov == C.PROV_OPEN else 0,
        ])

    data["rows"] = sorted(data["rows"] + rows_new, key=lambda r: r[0])
    total = len(data["rows"])
    print(f"مرشحون: {len(new)} | مُضاف: {len(rows_new)} | مكرر مُتجاوَز: {skipped} | الإجمالي: {total}")

    if dry_run:
        json.loads(json.dumps(data))  # تحقق سلامة
        print("(تشغيل تجريبي — لم يُكتب index.html)")
        return len(rows_new)

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = html[:m.start(2)] + payload + html[m.end(2):]
    html = re.sub(r"رصد [\d,٬]+ حدثًا", f"رصد {total:,} حدثًا", html)
    open(SITE, "w", encoding="utf-8").write(html)
    # تحقق نهائي
    chk = json.loads(re.search(r'<script id="EV" type="application/json">(.*?)</script>',
                               open(SITE, encoding="utf-8").read(), re.S).group(1))
    assert len(chk["rows"]) == total and len(chk["ents"]) == len(chk["kinds"])
    print(f"✓ كُتب index.html — {total} حدثًا، {len(chk['ents'])} كيانًا")
    return len(rows_new)


if __name__ == "__main__":
    main(dry_run="--dry" in sys.argv)
