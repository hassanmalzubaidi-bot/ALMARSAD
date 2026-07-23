# -*- coding: utf-8 -*-
"""تقرير نظافة بيانات أسبوعي: تكرارات محتملة، إحداثيات ناقصة، تصنيفات مبهمة.

قراءة فقط — لا يعدّل شيئًا. يطبع Markdown (يُلتقط في ملخص GitHub Actions).
"""
import difflib
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "public", "index.html")


def norm(t):
    return re.sub(r"\W+", " ", str(t).lower()).strip()[:120]


def main():
    html = open(SITE, encoding="utf-8").read()
    d = json.loads(re.search(
        r'<script id="EV" type="application/json">(.*?)</script>', html, re.S).group(1))
    ents, kinds, rows = d["ents"], d["kinds"], d["rows"]

    print("# 🧹 تقرير نظافة بيانات المرصد\n")
    print(f"- إجمالي الأحداث: **{len(rows):,}** · الكيانات: **{len(ents)}**")

    # ① تكرارات محتملة: نفس اليوم ونفس الكيان وتشابه نص ≥ 0.88
    by_key = {}
    for i, r in enumerate(rows):
        by_key.setdefault((r[0], r[1]), []).append((i, norm(r[9])))
    dupes = []
    for (day, ent_i), grp in by_key.items():
        if len(grp) < 2:
            continue
        for a in range(len(grp)):
            for b in range(a + 1, len(grp)):
                if difflib.SequenceMatcher(None, grp[a][1], grp[b][1]).ratio() >= 0.88:
                    dupes.append((day, ents[ent_i], rows[grp[a][0]][9]))
                    break
    print(f"- تكرارات محتملة (نفس اليوم/الكيان، تشابه ≥88%): **{len(dupes)}**")
    for day, ent, txt in dupes[:10]:
        print(f"  - `{day}` {ent} — {str(txt)[:70]}")
    if len(dupes) > 10:
        print(f"  - … و{len(dupes) - 10} أخرى")

    # ② الإحداثيات: على مستوى الدولة فقط (prec=0) أو صفرية
    country_level = sum(1 for r in rows if not r[5])
    zero_coord = sum(1 for r in rows if not r[3] or not r[4])
    print(f"- إحداثيات على مستوى الدولة (تقريبية): **{country_level:,}** "
          f"({country_level / len(rows) * 100:.0f}%) · صفرية: **{zero_coord}**")

    # ③ درجة خطر «غير محدد»
    undef = sum(1 for r in rows if r[8] == 5)
    print(f"- أحداث بخطر «غير محدد»: **{undef}**")

    # ④ كيانات مشبوهة: نوع unknown أو أحداث قليلة جدًا (≤2) — مرشّحة للدمج
    cnt = Counter(r[1] for r in rows)
    tiny = [(ents[i], cnt.get(i, 0)) for i in range(len(ents)) if cnt.get(i, 0) and cnt[i] <= 2]
    unknown_kind = [ents[i] for i in range(len(ents)) if kinds[i] not in ("state", "nonstate", "org", "region")]
    print(f"- كيانات بحدثين أو أقل (مرشّحة للدمج/المراجعة): **{len(tiny)}**")
    for name, c in sorted(tiny, key=lambda x: x[1])[:12]:
        print(f"  - {name} ({c})")
    if unknown_kind:
        print(f"- كيانات بنوع غير معروف: {', '.join(unknown_kind[:8])}")

    # الخلاصة
    issues = len(dupes) + zero_coord + len(unknown_kind)
    print(f"\n**الخلاصة:** {'⚠️ يُنصح بمراجعة البنود أعلاه من لوحة الأدمن.' if issues else '✅ لا مشكلات تُذكر.'}")


if __name__ == "__main__":
    main()
