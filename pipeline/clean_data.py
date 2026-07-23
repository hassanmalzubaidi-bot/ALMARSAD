# -*- coding: utf-8 -*-
"""تنظيف بيانات المرصد: تكرارات، دمج كيانات مكررة الاسم، حذف صفوف شاذة، إحداثيات صفرية.

python pipeline/clean_data.py            → معاينة فقط (لا يكتب شيئًا)
python pipeline/clean_data.py --apply    → تطبيق التنظيف على public/index.html
"""
import difflib
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402  (جدول CAPITALS)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "public", "index.html")
APPLY = "--apply" in sys.argv

# دمج الكيانات مكررة الاسم: البديل → القانوني (حالات لا لبس فيها فقط)
MERGE = {
    "الإكوادور": "إكوادور",
    "اوربا": "أوروبا",
    "الولايات المتحدة الأمريكية": "الولايات المتحدة",
    "الصين الشعبية": "الصين",
    "اليمن (الحوثيون)": "اليمن",   # ما تبقى بعد نقل أحداث الذراع إلى «الحوثيون»
}
# كيانات شاذة (بقايا استيراد لا تمثل فاعلين) — تُحذف صفوفها بعد المعاينة
ARTIFACTS = {"الاستنتاجات", "الاستنتاجات الرئيسية"}

DUP_SIM = 0.90  # عتبة حذف التكرار (أشد من عتبة تقرير الفحص 0.88)


def norm(t):
    return re.sub(r"\W+", " ", str(t).lower()).strip()[:140]


def row_score(r):
    """أي نسخة نُبقي عند التكرار؟ الأغنى معلومات."""
    return (len(str(r[10] or "")), 1 if r[13] else 0, len(str(r[12] or "")), 1 if r[5] else 0)


def main():
    html = open(SITE, encoding="utf-8").read()
    m = re.search(r'(<script id="EV" type="application/json">)(.*?)(</script>)', html, re.S)
    d = json.loads(m.group(2))
    ents, kinds, rows = d["ents"], d["kinds"], d["rows"]
    idx = {n: i for i, n in enumerate(ents)}
    n0 = len(rows)
    print(f"قبل: {n0:,} صفًا · {len(ents)} كيانًا\n")

    # ── ① حذف صفوف الكيانات الشاذة (مع طباعة نصوصها للمراجعة)
    art_idx = {idx[a] for a in ARTIFACTS if a in idx}
    art_rows = [r for r in rows if r[1] in art_idx]
    print(f"① صفوف شاذة تُحذف: {len(art_rows)}")
    for r in art_rows:
        print(f"   · [{ents[r[1]]}] {r[0]} — {str(r[9])[:80]}")
    rows = [r for r in rows if r[1] not in art_idx]

    # ── ② دمج الكيانات مكررة الاسم (إعادة إسناد الصفوف)
    print(f"\n② دمج كيانات:")
    remap_src = {}
    for src, dst in MERGE.items():
        if src in idx and dst in idx:
            cnt = sum(1 for r in rows if r[1] == idx[src])
            remap_src[idx[src]] = idx[dst]
            print(f"   · {src} → {dst} ({cnt} صفًا)")
    for r in rows:
        if r[1] in remap_src:
            r[1] = remap_src[r[1]]

    # ── ③ إزالة التكرارات: نفس اليوم والكيان وتشابه ≥ 0.90 — نبقي الأغنى
    by_key = {}
    for i, r in enumerate(rows):
        by_key.setdefault((r[0], r[1]), []).append(i)
    drop = set()
    dup_samples = []
    for key, grp in by_key.items():
        if len(grp) < 2:
            continue
        texts = {i: norm(rows[i][9]) for i in grp}
        for a in range(len(grp)):
            ia = grp[a]
            if ia in drop:
                continue
            for b in range(a + 1, len(grp)):
                ib = grp[b]
                if ib in drop:
                    continue
                if difflib.SequenceMatcher(None, texts[ia], texts[ib]).ratio() >= DUP_SIM:
                    loser = ia if row_score(rows[ia]) < row_score(rows[ib]) else ib
                    drop.add(loser)
                    if len(dup_samples) < 12:
                        dup_samples.append((rows[loser][0], ents[rows[loser][1]], str(rows[loser][9])[:66]))
    print(f"\n③ تكرارات تُحذف: {len(drop)}")
    for day, ent, txt in dup_samples:
        print(f"   · {day} {ent} — {txt}")
    if len(drop) > 12:
        print(f"   · … و{len(drop) - 12} أخرى")
    rows = [r for i, r in enumerate(rows) if i not in drop]

    # ── ④ إحداثيات صفرية → عاصمة الدولة (دقة country-level) حيث أمكن
    fixed = skipped = 0
    for r in rows:
        if not r[3] or not r[4]:
            head = str(ents[r[1]]).split("/")[0].strip()
            cap = C.CAPITALS.get(head)
            if cap:
                r[3], r[4], r[5] = round(cap[0], 4), round(cap[1], 4), 0
                fixed += 1
            else:
                skipped += 1
    print(f"\n④ إحداثيات صفرية: أُصلحت {fixed} (عاصمة الدولة) · بقيت {skipped} (لا عاصمة معروفة — تبقى خارج الخريطة)")

    # ── ⑤ ضغط قائمة الكيانات: أسقط من صار بلا صفوف، وأعد ترقيم rows وnet
    used = {r[1] for r in rows}
    old2new, new_ents, new_kinds = {}, [], []
    for i, name in enumerate(ents):
        if i in used:
            old2new[i] = len(new_ents)
            new_ents.append(name)
            new_kinds.append(kinds[i])
    removed_ents = len(ents) - len(new_ents)
    for r in rows:
        r[1] = old2new[r[1]]
    # net: أعد الترقيم وادمج عدّادات الأهداف المكررة وأسقط الوصلات الذاتية/اليتيمة
    net = d.get("net") or {}
    new_net = {}
    for k, links in net.items():
        ki = int(k)
        ki = remap_src.get(ki, ki)
        if ki not in old2new:
            continue
        nk = old2new[ki]
        agg = new_net.setdefault(str(nk), {})
        for j, cnt in links:
            j = remap_src.get(j, j)
            if j not in old2new:
                continue
            nj = old2new[j]
            if nj == nk:
                continue
            agg[nj] = agg.get(nj, 0) + cnt
    d["net"] = {k: sorted(([j, c] for j, c in v.items()), key=lambda x: -x[1])
                for k, v in new_net.items()}
    print(f"\n⑤ كيانات أُسقطت بعد الدمج/التنظيف: {removed_ents} → المتبقي {len(new_ents)}")

    d["ents"], d["kinds"], d["rows"] = new_ents, new_kinds, rows
    total = len(rows)
    print(f"\nبعد: {total:,} صفًا (−{n0 - total}) · {len(new_ents)} كيانًا")

    if not APPLY:
        print("\n(معاينة فقط — أعد التشغيل بـ --apply للتطبيق)")
        return

    payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    html = html[:m.start(2)] + payload + html[m.end(2):]
    html = re.sub(r"رصد [\d,٬]+ حدثًا", f"رصد {total:,} حدثًا", html)
    open(SITE, "w", encoding="utf-8").write(html)
    chk = json.loads(re.search(r'<script id="EV" type="application/json">(.*?)</script>',
                               open(SITE, encoding="utf-8").read(), re.S).group(1))
    assert len(chk["rows"]) == total and len(chk["ents"]) == len(chk["kinds"])
    assert all(0 <= r[1] < len(chk["ents"]) for r in chk["rows"])
    print("✓ طُبّق التنظيف وتحقّقت سلامة الملف")


if __name__ == "__main__":
    main()
