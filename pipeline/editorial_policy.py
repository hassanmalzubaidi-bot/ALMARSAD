# -*- coding: utf-8 -*-
"""السياسة التحريرية — خط أحمر: سمعة الأسر الحاكمة في السعودية والخليج.

القاعدة: يُحجب الخبر إذا اجتمع فيه (ذكر ملكي/حاكم خليجي أو صفة أسرية حاكمة)
مع (مفردة مسيئة للسمعة). الأخبار البروتوكولية والدبلوماسية العادية تمرّ.

تُطبَّق في: الحصاد (fetch_sources) + بوابة النشر (merge_rebuild) + كنس الأدمن (/api/sweep).
الإدارة من اللوحة الخلفية فقط — لا أثر لها في واجهة الموقع.

الاستخدام اليدوي:
  python pipeline/editorial_policy.py            → فحص بيانات الموقع (عرض فقط)
  python pipeline/editorial_policy.py --apply    → حذف المخالفات من public/index.html
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "public", "index.html")

# ذكر ملكي/أسري حاكم (السعودية ودول الخليج) — أسماء وصفات محددة، لا كلمات عامة
ROYAL = [
    "محمد بن سلمان", "بن سلمان", "الملك سلمان", "سلمان بن عبدالعزيز",
    "ولي العهد", "العاهل السعودي", "ملك السعودية", "آل سعود",
    "الأسرة المالكة", "الأسرة الحاكمة", "العائلة المالكة", "العائلة الحاكمة",
    "أمير سعودي", "أميرة سعودية", "أمراء سعوديون", "الأمراء السعوديين", "الديوان الملكي",
    "محمد بن زايد", "بن زايد", "آل نهيان", "محمد بن راشد", "بن راشد", "آل مكتوم",
    "تميم بن حمد", "أمير قطر", "آل ثاني",
    "أمير الكويت", "مشعل الأحمد", "آل صباح",
    "ملك البحرين", "عاهل البحرين", "حمد بن عيسى", "آل خليفة",
    "سلطان عمان", "هيثم بن طارق", "آل بوسعيد",
    "شيخ خليجي", "شيوخ الخليج", "أمير خليجي",
]

# مفردات المساس بالسمعة
REPUTATION = [
    "كحول", "خمر", "خمور", "مخدرات", "مخدر", "سُكر", "ثمل",
    "عشيق", "دعارة", "قمار", "ملهى", "ملاهي", "علاقة غير شرعية",
    "شذوذ", "مثلي", "تحرش", "اغتصاب", "ابتزاز",
    "فضيحة", "فضائح", "فساد", "اختلاس", "رشوة", "غسيل أموال", "تبييض أموال",
    "تعذيب", "خاشقجي", "اعتقال تعسفي", "سجناء الرأي", "انتهاكات",
    "تجسس على", "إساءة", "يسيء", "مؤامرة", "صراع العرش", "خلافات العائلة",
    "انقلاب القصر", "عمالة",
]


def blocked(text):
    """يعيد سبب الحجب إن اجتمع ذكرٌ ملكي مع مفردة سمعة، وإلا None."""
    t = str(text)
    r = next((x for x in ROYAL if x in t), None)
    if not r:
        return None
    k = next((x for x in REPUTATION if x in t), None)
    if not k:
        return None
    return f"{r} + {k}"


def sweep_rows(rows, ents):
    """يفحص صفوف الموقع ويعيد [(فهرس، سبب، صف)] للمخالف."""
    out = []
    for i, r in enumerate(rows):
        reason = blocked(f"{ents[r[1]]} {r[9]} {r[10]}")
        if reason:
            out.append((i, reason, r))
    return out


def main():
    apply = "--apply" in sys.argv
    html = open(SITE, encoding="utf-8").read()
    m = re.search(r'(<script id="EV" type="application/json">)(.*?)(</script>)', html, re.S)
    d = json.loads(m.group(2))
    hits = sweep_rows(d["rows"], d["ents"])
    print(f"فحص {len(d['rows']):,} حدثًا → مخالفات السياسة التحريرية: {len(hits)}")
    for i, reason, r in hits:
        print(f"  ✗ [{r[0]}] {d['ents'][r[1]]} — {str(r[9])[:70]}  ⟵ ({reason})")
    if not apply:
        if hits:
            print("(عرض فقط — أعد التشغيل بـ --apply للحذف)")
        return len(hits)
    if not hits:
        return 0
    drop = {i for i, _, _ in hits}
    d["rows"] = [r for i, r in enumerate(d["rows"]) if i not in drop]
    total = len(d["rows"])
    payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    html = html[:m.start(2)] + payload + html[m.end(2):]
    html = re.sub(r"رصد [\d,٬]+ حدثًا", f"رصد {total:,} حدثًا", html)
    open(SITE, "w", encoding="utf-8").write(html)
    chk = json.loads(re.search(r'<script id="EV" type="application/json">(.*?)</script>',
                               open(SITE, encoding="utf-8").read(), re.S).group(1))
    assert len(chk["rows"]) == total
    print(f"✓ حُذفت {len(hits)} — المتبقي {total:,}")
    return len(hits)


if __name__ == "__main__":
    main()
