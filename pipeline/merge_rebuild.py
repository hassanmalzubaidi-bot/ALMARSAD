# -*- coding: utf-8 -*-
"""③ الدمج إلى الطابور: يضيف الأحداث المصنّفة إلى data/pending.json (لا يمسّ الموقع العام).

نموذج «طابور المراجعة»: الأحداث الجديدة لا تُنشر مباشرة، بل تنتظر اعتماد الأدمن.
إزالة التكرار تتم مقابل الموقع العام (المعتمد) والطابور معًا.
"""
import json, os, sys, re, difflib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import classify as CL

CLASSIFIED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "classified.json")


def public_keys():
    """مفاتيح إزالة التكرار من الموقع العام (الأحداث المعتمدة)."""
    html = open(C.SITE, encoding="utf-8").read()
    data = json.loads(re.search(r'<script id="EV" type="application/json">(.*?)</script>', html, re.S).group(1))
    ents, keys = data["ents"], set()
    for r in data["rows"]:
        head = str(ents[r[1]]).split("/")[0].strip()
        body = re.sub(r"\W+", "", str(r[9]).lower())[:55]
        keys.add(f"{r[0]}|{head}|{body}")
    return keys


def load_pending():
    try:
        return json.load(open(C.PENDING, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def main():
    new = json.load(open(CLASSIFIED, encoding="utf-8"))
    pending = load_pending()
    keys = public_keys()
    # أضف مفاتيح الطابور الحالي لتفادي التكرار داخله
    for ev in pending:
        keys.add(CL.dedup_key(ev["الدولة"], ev["الحدث"], ev["التاريخ"]))

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
        # وسم عنصر الطابور بحقول التتبّع
        ev["_حالة"] = "معلّق"
        added.append((dc, nt, ev))
        keys.add(k)

    pending += [a[2] for a in added]
    json.dump(pending, open(C.PENDING, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"مرشحون: {len(new)} | أُضيف للطابور: {len(added)} | مكرر مُتجاوَز: {skipped} | حجم الطابور الآن: {len(pending)}")
    return len(added)


if __name__ == "__main__":
    main()
