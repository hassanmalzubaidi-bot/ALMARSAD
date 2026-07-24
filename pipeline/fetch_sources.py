# -*- coding: utf-8 -*-
"""① الجلب: يسحب أخبار آخر يوم من RSS + GDELT ويكتب raw_items.json خامًا للتصنيف."""
import json, os, sys, time, re, html as _html
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "raw_items.json")
UA = {"User-Agent": "Mozilla/5.0 (MiddleEastObservatory/1.0)"}


def _get(url, timeout=25):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def _clean(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


def _relevant(text):
    return any(kw in text for kw in C.RELEVANCE_KW)


def fetch_rss(max_age_h=48):
    items, cutoff = [], datetime.now(timezone.utc) - timedelta(hours=max_age_h)
    for name, url in C.RSS_FEEDS.items():
        try:
            root = ET.fromstring(_get(url))
        except Exception as e:
            print(f"  ✗ RSS {name}: {type(e).__name__}"); continue
        n = 0
        for it in root.findall(".//item"):
            title = _clean(it.findtext("title", ""))
            desc = _clean(it.findtext("description", ""))
            link = (it.findtext("link", "") or "").strip()
            pub = it.findtext("pubDate", "") or ""
            blob = title + " " + desc
            if not _relevant(blob):
                continue
            items.append({"title": title, "summary": desc, "link": link,
                          "published": pub, "source": name, "origin": "rss"})
            n += 1
        print(f"  ✓ RSS {name}: {n} خبرًا ذا صلة")
    return items


def fetch_gdelt():
    items = []
    for q in C.GDELT_QUERIES:
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?query="
               + urllib.parse.quote(q)
               + f"&mode=artlist&maxrecords=25&timespan={C.GDELT_TIMESPAN}&format=json&sort=datedesc")
        ok = False
        for attempt in range(3):
            try:
                d = json.loads(_get(url))
                for a in d.get("articles", []):
                    t = _clean(a.get("title", ""))
                    if not _relevant(t):
                        continue
                    items.append({"title": t, "summary": "", "link": a.get("url", ""),
                                  "published": a.get("seendate", ""),
                                  "source": "GDELT/" + a.get("domain", ""), "origin": "gdelt"})
                ok = True; break
            except Exception as e:
                if "429" in str(e):
                    time.sleep(C.GDELT_THROTTLE_SEC * (attempt + 1))
                else:
                    break
        print(f"  {'✓' if ok else '⚠'} GDELT «{q[:30]}…»")
        time.sleep(C.GDELT_THROTTLE_SEC)
    return items


def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = re.sub(r"\W+", "", it["title"].lower())[:70]
        if key and key not in seen:
            seen.add(key); out.append(it)
    return out


if __name__ == "__main__":
    print("① جلب المصادر…")
    all_items = fetch_rss() + fetch_gdelt()
    all_items = dedupe(all_items)
    # السياسة التحريرية: حجب ما يمسّ سمعة الأسر الحاكمة (سعودية/خليجية) من المنبع
    import editorial_policy as EP
    kept = [it for it in all_items
            if not EP.blocked(f"{it.get('title','')} {it.get('summary','')}")]
    ed_blocked = len(all_items) - len(kept)
    all_items = kept
    json.dump(all_items, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"الإجمالي بعد إزالة التكرار: {len(all_items)} خبرًا خامًا"
          + (f" (حُجب تحريريًا: {ed_blocked})" if ed_blocked else "") + f" → {OUT}")
