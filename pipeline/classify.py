# -*- coding: utf-8 -*-
"""② مساعد التصنيف الحتمي: يحوّل الحقول الدلالية (التي ينتجها الوكيل) إلى ترميز الموقع.

الوكيل (Claude في الروتين) يقرأ raw_items.json ويكتب classified.json، كل عنصر فيه:
  {التاريخ, الدولة, المدينة, طبيعة (نص مثل "عسكري / نووي"), نطاق ("إقليمي"/"دولي"/"داخلي"),
   خطر ("حرج".."منخفض"), الحدث, التفاصيل, المصدر}
هذا الملف يضيف الإحداثيات ويحوّل النصوص إلى الأرقام التي يفهمها الموقع.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C


def geocode(city, country):
    """يُرجع (عرض، طول، دقة) — دقة 1 = مدينة، 0 = مستوى دولة/تقريبي."""
    city = (city or "").strip()
    if city in C.CITY_COORDS:
        return (*C.CITY_COORDS[city], 1)
    head = (country or "").split("/")[0].strip()
    if head in C.CAPITALS:
        return (*C.CAPITALS[head], 0)
    return (25.0, 45.0, 0)  # مركز إقليمي احتياطي


def nat_mask(nature):
    m = 0
    for tok in str(nature).split("/"):
        tok = tok.strip()
        tok = C.NAT_ALIAS.get(tok, tok)
        if tok in C.NAT:
            m |= 1 << C.NAT.index(tok)
    return m or (1 << C.NAT.index("أخرى"))


def scope_idx(scope):
    scope = str(scope).strip()
    return C.SCOPE.index(scope) if scope in C.SCOPE else 3


def risk_idx(risk):
    risk = str(risk).replace("جدًا", "جداً").strip()
    return C.RISK.index(risk) if risk in C.RISK else 5


def date_compact(iso):
    """YYYY-MM-DD → YYMMDD (ترميز الموقع)."""
    p = str(iso)[:10].split("-")
    return p[0][2:] + p[1] + p[2]


def dedup_key(country, event, date_iso):
    import re
    head = str(country).split("/")[0].strip()
    body = re.sub(r"\W+", "", str(event).lower())[:55]
    return f"{date_compact(date_iso)}|{head}|{body}"
