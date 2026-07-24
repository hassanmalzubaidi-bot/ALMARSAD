# -*- coding: utf-8 -*-
"""لوحة أدمن «مرصد الشرق الأوسط» — أداة محلية لإدارة المحتوى المنشور.

تشغيل:  python pipeline/admin.py        (تفتح المتصفح على http://127.0.0.1:8765)
خيارات: --port 8765  --no-browser

الوظائف: بحث/تصفية كل الأحداث، تعديل أي حدث، حذف، ثم «حفظ» (يكتب public/index.html)
أو «حفظ ونشر» (يكتب + git commit + push → Netlify ينشر تلقائيًا).
تعمل محليًا فقط (127.0.0.1) — لا تُنشر ولا تحوي أسرارًا.
"""
import json, os, re, sys, time, threading, subprocess, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "public", "index.html")

RN = ["حرج", "مرتفع جداً", "مرتفع", "متوسط", "منخفض", "غير محدد"]
SC = ["إقليمي", "دولي", "داخلي", "غير مصنّف"]
EV_RE = re.compile(r'(<script id="EV" type="application/json">)(.*?)(</script>)', re.S)

STATE = {"data": None, "dirty": 0}


def _sig():
    """توقيع بنيوي لبيانات EV على القرص — لكشف أي تغيّر خارجي (أتمتة/تعديل آخر)."""
    d = json.loads(EV_RE.search(open(SITE, encoding="utf-8").read()).group(2))
    return (len(d["rows"]), len(d.get("profiles") or {}), len(d.get("dossiers") or []),
            tuple(sorted((d.get("reports") or {}).keys())),
            tuple(d.get("hidden") or []), len(d["ents"]))


def load():
    html = open(SITE, encoding="utf-8").read()
    STATE["data"] = json.loads(EV_RE.search(html).group(2))
    STATE["dirty"] = 0
    STATE["sig"] = _sig()


def save():
    d = STATE["data"]
    html = open(SITE, encoding="utf-8").read()
    m = EV_RE.search(html)
    payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    html = html[: m.start(2)] + payload + html[m.end(2):]
    total = len(d["rows"])
    html = re.sub(r"رصد [\d,٬]+ حدثًا", f"رصد {total:,} حدثًا", html)
    open(SITE, "w", encoding="utf-8").write(html)
    chk = json.loads(EV_RE.search(open(SITE, encoding="utf-8").read()).group(2))
    assert len(chk["rows"]) == total and len(chk["ents"]) == len(chk["kinds"])
    STATE["dirty"] = 0
    STATE["sig"] = _sig()
    return total


def publish():
    # حارس ضد البيانات القديمة: إن تغيّر الموقع على القرص منذ فتح اللوحة، ارفض النشر
    # (منعًا لكتابة لقطة قديمة فوق محتوى أحدث — كما حدث في 2026-07-23).
    if _sig() != STATE.get("sig"):
        return {"ok": False, "stale": True, "total": len(STATE["data"]["rows"]),
                "msg": "⚠️ تغيّر محتوى الموقع منذ فتحك اللوحة (تحديث تلقائي أو تعديل آخر). "
                       "أعد تشغيل admin.bat لتحميل أحدث البيانات ثم أعد تعديلك — منعًا لمسح محتوى أحدث."}
    total = save()
    msg = "إدارة المحتوى: تعديلات الأدمن " + time.strftime("%Y-%m-%d %H:%M")
    out = []
    for cmd in (["git", "add", "-A"], ["git", "commit", "-m", msg], ["git", "push", "origin", "main"]):
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        out.append((" ".join(cmd[:2]), p.returncode, (p.stdout or "") + (p.stderr or "")))
        if p.returncode != 0 and cmd[1] != "commit":
            return {"ok": False, "total": total, "log": out}
    committed = not any(rc != 0 and name == "git commit" for name, rc, _ in out) or True
    return {"ok": True, "total": total, "log": out, "committed": committed}


def dt_iso(s):
    return f"20{s[0:2]}-{s[2:4]}-{s[4:6]}"


def dt_compact(iso):
    p = str(iso)[:10].split("-")
    return p[0][2:] + p[1] + p[2]


def nat_names(mask):
    NAT = STATE["data"]["nat"]
    return [NAT[i] for i in range(len(NAT)) if mask & (1 << i)]


def nat_mask(names):
    NAT = STATE["data"]["nat"]
    m = 0
    for n in names:
        if n in NAT:
            m |= 1 << NAT.index(n)
    return m or (1 << NAT.index("أخرى"))


def row_view(i, r):
    d = STATE["data"]
    return {
        "i": i, "التاريخ": dt_iso(r[0]), "الدولة": d["ents"][r[1]], "المدينة": r[2],
        "خطر": r[8], "خطر_اسم": RN[r[8]] if r[8] < len(RN) else "?",
        "نطاق": r[7], "طبيعة": nat_names(r[6]), "الحدث": r[9], "التفاصيل": r[10] or "",
        "المصدر": (r[12] if len(r) > 12 else "") or "", "خط_عرض": r[3], "خط_طول": r[4],
        "مميز": bool(len(r) > 14 and r[14] == 1),
    }


def ent_index(name):
    d = STATE["data"]
    name = str(name).split("/")[0].strip()
    if name in d["ents"]:
        return d["ents"].index(name)
    d["ents"].append(name)
    d["kinds"].append("state")
    return len(d["ents"]) - 1


def api_list(q):
    # حمّل أحدث بيانات القرص عند كل فتح/تحديث للوحة (ما لم تكن هناك تعديلات معلّقة)
    # حتى تعكس اللوحة دائمًا آخر محتوى منشور وتُعاد مزامنة توقيع الحارس.
    if not STATE["dirty"]:
        load()
    d = STATE["data"]
    rows = list(enumerate(d["rows"]))
    term = (q.get("q", [""])[0] or "").strip()
    risk = q.get("risk", [""])[0]
    country = (q.get("country", [""])[0] or "").strip()
    df, dt_ = q.get("from", [""])[0], q.get("to", [""])[0]
    if term:
        rows = [(i, r) for i, r in rows if term in str(r[9]) or term in str(r[10] or "") or term in d["ents"][r[1]] or term in str(r[2])]
    if risk != "":
        rows = [(i, r) for i, r in rows if r[8] == int(risk)]
    if country:
        rows = [(i, r) for i, r in rows if country in d["ents"][r[1]]]
    if df:
        rows = [(i, r) for i, r in rows if dt_iso(r[0]) >= df]
    if dt_:
        rows = [(i, r) for i, r in rows if dt_iso(r[0]) <= dt_]
    rows.sort(key=lambda x: x[1][0], reverse=True)
    total = len(rows)
    page = int(q.get("page", ["1"])[0]); per = 50
    rows = rows[(page - 1) * per: page * per]
    return {"total": total, "page": page, "per": per, "dirty": STATE["dirty"],
            "all": len(d["rows"]), "nat": d["nat"], "rn": RN, "sc": SC,
            "reports": d.get("reports", {}), "hidden": d.get("hidden", []), "pages": PAGES,
            "forecasts": d.get("forecasts", []),
            "gate": d.get("gate", {}),
            "months": sorted({dt_iso(r[0])[:7] for r in d["rows"]}, reverse=True),
            "rows": [row_view(i, r) for i, r in rows]}


def api_edit(body):
    d = STATE["data"]
    i = int(body["i"]); r = d["rows"][i]
    r[0] = dt_compact(body["التاريخ"]); r[1] = ent_index(body["الدولة"])
    r[2] = body.get("المدينة") or "عام"
    try:
        r[3] = round(float(body.get("خط_عرض")), 4); r[4] = round(float(body.get("خط_طول")), 4)
    except (TypeError, ValueError):
        pass
    r[6] = nat_mask(body.get("طبيعة") or [])
    r[7] = int(body.get("نطاق", 3)); r[8] = int(body.get("خطر", 5))
    r[9] = body["الحدث"].strip(); r[10] = (body.get("التفاصيل") or "").strip()
    if len(r) > 12:
        r[12] = (body.get("المصدر") or "").strip()
    STATE["dirty"] += 1
    return {"ok": True, "dirty": STATE["dirty"]}


def api_delete(body):
    i = int(body["i"])
    STATE["data"]["rows"].pop(i)
    STATE["dirty"] += 1
    return {"ok": True, "dirty": STATE["dirty"], "all": len(STATE["data"]["rows"])}


def api_feature(body):
    """إبراز/إلغاء إبراز حدث: الحقل r[14] (يُوسَّع الصف عند الحاجة)."""
    i = int(body["i"]); on = int(body.get("on", 1))
    r = STATE["data"]["rows"][i]
    while len(r) < 15:
        r.append(0)
    r[14] = 1 if on else 0
    STATE["dirty"] += 1
    return {"ok": True, "dirty": STATE["dirty"], "مميز": bool(r[14])}


def api_assessment(body):
    """كتابة/تعديل/مسح التقييم التحليلي المكتوب لشهر (RAW.reports[month])."""
    month = str(body.get("month", "")).strip()
    text = str(body.get("text", "")).strip()
    by = str(body.get("by", "")).strip()
    date = str(body.get("date", "")).strip()
    if not month:
        return {"ok": False, "err": "لا شهر"}
    reports = STATE["data"].setdefault("reports", {})
    if text:
        reports[month] = {"text": text, "by": by or "محلل المرصد", "date": date}
    else:
        reports.pop(month, None)
    STATE["dirty"] += 1
    return {"ok": True, "dirty": STATE["dirty"], "saved": bool(text), "month": month}


PAGES = [("/dashboard", "لوحة المؤشرات"), ("/report", "التقرير التحليلي"), ("/atlas", "الأطلس"),
         ("/explorer", "المستكشف"), ("/hotspots", "بؤر التوتر"), ("/actors", "الفاعلون"),
         ("/reports", "التقارير"), ("/forecasts", "سجل التوقعات"), ("/methodology", "المنهجية"),
         ("/about", "عن المرصد"), ("/contact", "اتصل بنا")]


def api_pages(body):
    """ضبط الصفحات المخفية عن العامة: body['hidden'] = قائمة مسارات مخفية."""
    valid = {p for p, _ in PAGES}
    hidden = [str(p) for p in body.get("hidden", []) if str(p) in valid]
    STATE["data"]["hidden"] = hidden
    STATE["dirty"] += 1
    return {"ok": True, "dirty": STATE["dirty"], "hidden": hidden}


def api_forecast(body):
    """إغلاق توقع (correct/wrong/partial) أو إعادة فتحه (outcome=null) — الدقة وBrier يُحسبان في الموقع."""
    fid = str(body.get("id", "")).strip()
    outcome = body.get("outcome")
    if outcome not in ("correct", "wrong", "partial", None):
        return {"ok": False, "err": "outcome غير صالح"}
    fcs = STATE["data"].setdefault("forecasts", [])
    f = next((x for x in fcs if x.get("id") == fid), None)
    if not f:
        return {"ok": False, "err": f"لا توقع بالمعرف {fid}"}
    f["outcome"] = outcome
    f["resolvedOn"] = time.strftime("%Y-%m-%d") if outcome else None
    note = str(body.get("note", "")).strip()
    if note:
        f["note"] = note
    STATE["dirty"] += 1
    return {"ok": True, "dirty": STATE["dirty"], "id": fid, "outcome": outcome, "resolvedOn": f["resolvedOn"]}


def api_gate(body):
    """إعدادات بوابة العضوية (RAW.gate): تشغيل/إيقاف، حد المستكشف، الأقسام المقفولة."""
    gate = {
        "on": 1 if body.get("on") else 0,
        "limit": max(0, int(body.get("limit") or 0)),
        "assess": 1 if body.get("assess") else 0,
        "profiles": 1 if body.get("profiles") else 0,
        "dossiers": 1 if body.get("dossiers") else 0,
        "xport": 1 if body.get("xport") else 0,
    }
    STATE["data"]["gate"] = gate
    STATE["dirty"] += 1
    return {"ok": True, "dirty": STATE["dirty"], "gate": gate}


PAGE = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>لوحة أدمن — مرصد الشرق الأوسط</title><style>
:root{--line:#e2e8f0;--dim:#64748b;--bg:#f8fafc;--card:#fff}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,"Segoe UI",sans-serif;background:var(--bg);color:#0f172a}
header{position:sticky;top:0;z-index:9;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
h1{font-size:16px;margin:0 12px 0 0}input,select,button,textarea{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:#fff}
button{cursor:pointer}button.p{background:#0f766e;color:#fff;border-color:#0f766e}button.warn{background:#b91c1c;color:#fff;border-color:#b91c1c}
#stats{color:var(--dim);font-size:13px;margin-inline-start:auto}
main{max-width:1100px;margin:16px auto;padding:0 14px}
.ev{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:8px;display:flex;gap:10px;align-items:flex-start}
.chip{padding:2px 9px;border-radius:99px;color:#fff;font-size:12px;white-space:nowrap}
.meta{color:var(--dim);font-size:12.5px;margin-top:3px}
.ev .txt{flex:1}.ev .act{display:flex;gap:6px}
dialog{border:1px solid var(--line);border-radius:12px;max-width:640px;width:92vw}
dialog form{display:grid;gap:8px}label{font-size:13px;color:var(--dim)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
#nats{display:flex;flex-wrap:wrap;gap:8px}#nats label{border:1px solid var(--line);padding:4px 8px;border-radius:8px;color:inherit;font-size:13px}
#toast{position:fixed;bottom:16px;inset-inline-start:16px;background:#0f172a;color:#fff;padding:10px 16px;border-radius:10px;display:none;z-index:99}
.pager{display:flex;gap:8px;justify-content:center;margin:14px 0}
</style></head><body>
<header><h1>🛡️ لوحة الأدمن</h1>
<input id="q" placeholder="بحث في الأحداث…" style="width:200px">
<select id="risk"><option value="">كل الدرجات</option></select>
<input id="country" placeholder="الدولة" style="width:110px">
<input id="from" type="date"><input id="to" type="date">
<button onclick="P.go(1)">تصفية</button>
<span id="stats"></span>
<button onclick="P.save()">💾 حفظ</button>
<button onclick="P.openPages()">👁️ الصفحات</button>
<button onclick="P.openAssess()">✍️ التقييم التحليلي</button>
<button onclick="P.openFc()">⏳ التوقعات</button>
<button onclick="P.openGate()">🔐 العضوية</button>
<button class="p" onclick="P.publish()">🚀 حفظ ونشر</button>
</header><main id="list"></main>
<dialog id="adlg"><form method="dialog" id="af" style="display:grid;gap:10px;min-width:min(680px,92vw)">
<h3 style="margin:0">✍️ التقييم التحليلي (يكتبه المحلل)</h3>
<div class="grid2"><div><label>الشهر</label><select id="aMonth" onchange="P.loadAssess()"></select></div>
<div><label>اسم المحلل (يظهر في التوقيع)</label><input id="aBy" placeholder="محلل المرصد"></div></div>
<div><label>نص التقييم — تقديرات مصاغة بحيث يمكن مخالفتها، ودرجة ثقة صريحة، ومؤشرات تُبطلها</label>
<textarea id="aText" rows="12" placeholder="اكتب هنا... (افصل الفقرات بسطر فارغ)"></textarea></div>
<p class="meta" style="margin:0">يُحفظ للشهر المختار ويحلّ محلّ السقالة في صفحة «التقارير». لمسحه: افرغ النص واحفظ.</p>
<div style="display:flex;gap:8px;justify-content:flex-end"><button value="cancel">إغلاق</button>
<button class="p" value="ok" onclick="P.saveAssess(event)">حفظ التقييم</button></div>
</form></dialog>
<dialog id="gdlg"><form method="dialog" style="display:grid;gap:12px;min-width:min(520px,94vw)">
<h3 style="margin:0">🔐 بوابة العضوية — ماذا يرى غير المسجّلين</h3>
<label style="display:flex;align-items:center;gap:10px;border:1px solid var(--line);border-radius:8px;padding:10px 12px">
 <input type="checkbox" id="gOn" style="width:18px;height:18px"> <b>تفعيل البوابة</b>
 <span class="meta">(إيقافها = الموقع كله مفتوح للجميع)</span></label>
<label style="display:flex;align-items:center;gap:10px;padding:0 4px">حد نتائج المستكشف لغير الأعضاء
 <input type="number" id="gLimit" min="0" step="10" style="width:90px"> <span class="meta">(0 = بلا حد)</span></label>
<div style="display:grid;gap:6px">
 <p class="meta" style="margin:0">الأقسام المقفولة لغير الأعضاء (فقرة أولى + دعوة تسجيل):</p>
 <label style="display:flex;gap:10px;align-items:center"><input type="checkbox" id="gAssess" style="width:17px;height:17px"> التقييم التحليلي الشهري</label>
 <label style="display:flex;gap:10px;align-items:center"><input type="checkbox" id="gProfiles" style="width:17px;height:17px"> دوسيهات الفاعلين</label>
 <label style="display:flex;gap:10px;align-items:center"><input type="checkbox" id="gDossiers" style="width:17px;height:17px"> الملفات الموضوعية</label>
 <label style="display:flex;gap:10px;align-items:center"><input type="checkbox" id="gXport" style="width:17px;height:17px"> قفل التصدير (CSV + PDF)</label>
</div>
<a href="https://app.netlify.com/projects/famous-biscochitos-e29381/forms" target="_blank" rel="noopener"
 style="font-size:13px">👥 عرض قائمة الأعضاء المسجّلين (Netlify ← Forms ← members)</a>
<div style="display:flex;gap:8px;justify-content:flex-end"><button value="cancel">إغلاق</button>
<button class="p" value="ok" onclick="P.saveGate(event)">حفظ الإعدادات</button></div>
</form></dialog>
<dialog id="fdlg"><form method="dialog" style="display:grid;gap:10px;min-width:min(700px,94vw)">
<h3 style="margin:0">⏳ سجل التوقعات — الإغلاق والمحاسبة</h3>
<p class="meta" style="margin:0">التوقع المستحق (تجاوز أفقه بلا إغلاق) يظهر بإطار أحمر. الإغلاق يُحدّث الدقة وBrier في الموقع تلقائيًا بعد «حفظ ونشر».</p>
<div id="fcList" style="display:grid;gap:8px;max-height:60vh;overflow:auto"></div>
<div style="display:flex;justify-content:flex-end"><button value="cancel">إغلاق</button></div>
</form></dialog>
<dialog id="pdlg"><form method="dialog" style="display:grid;gap:10px;min-width:min(460px,92vw)">
<h3 style="margin:0">👁️ التحكم في الصفحات</h3>
<p class="meta" style="margin:0">أوقف تشغيل أي صفحة لإخفائها عن العامة (يُخفى رابطها ويُمنع الوصول المباشر). الرئيسية دائمًا ظاهرة.</p>
<div id="pgList" style="display:grid;gap:6px;max-height:52vh;overflow:auto"></div>
<div style="display:flex;gap:8px;justify-content:flex-end"><button value="cancel">إغلاق</button>
<button class="p" value="ok" onclick="P.savePages(event)">حفظ</button></div>
</form></dialog>
<div class="pager"><button onclick="P.go(P.page-1)">السابق</button><span id="pg"></span><button onclick="P.go(P.page+1)">التالي</button></div>
<dialog id="dlg"><form method="dialog" id="f">
<input type="hidden" name="i">
<div class="grid2"><div><label>التاريخ</label><input type="date" name="التاريخ" required></div>
<div><label>درجة الخطر</label><select name="خطر" id="riskSel"></select></div></div>
<div class="grid2"><div><label>الدولة / الكيان</label><input name="الدولة" required></div>
<div><label>المدينة</label><input name="المدينة"></div></div>
<div class="grid2"><div><label>خط العرض</label><input name="خط_عرض"></div><div><label>خط الطول</label><input name="خط_طول"></div></div>
<div><label>النطاق</label><select name="نطاق" id="scSel"></select></div>
<div><label>طبيعة الحدث</label><div id="nats"></div></div>
<div><label>الحدث</label><textarea name="الحدث" rows="3" required></textarea></div>
<div><label>التفاصيل</label><textarea name="التفاصيل" rows="2"></textarea></div>
<div><label>المصدر</label><input name="المصدر"></div>
<div style="display:flex;gap:8px;justify-content:flex-end"><button value="cancel">إلغاء</button><button class="p" value="ok" onclick="P.submitEdit(event)">حفظ التعديل</button></div>
</form></dialog>
<div id="toast"></div>
<script>
var RC=["#991b1b","#dc2626","#ea580c","#d97706","#16a34a","#64748b"];
var P={page:1,meta:null,
 toast:function(t){var e=document.getElementById('toast');e.textContent=t;e.style.display='block';setTimeout(function(){e.style.display='none'},3500)},
 go:function(p){if(p<1)return;P.page=p;
  var ps=new URLSearchParams({q:q.value,risk:risk.value,country:country.value,from:document.getElementById('from').value,to:document.getElementById('to').value,page:p});
  fetch('/api/list?'+ps).then(r=>r.json()).then(function(d){P.meta=d;
   if(!risk.options.length||risk.options.length===1){d.rn.forEach(function(n,i){var o=document.createElement('option');o.value=i;o.textContent=n;risk.appendChild(o)})}
   document.getElementById('stats').textContent='إجمالي: '+d.all+' · نتائج: '+d.total+' · تعديلات غير محفوظة: '+d.dirty;
   document.getElementById('pg').textContent=p+' / '+Math.max(1,Math.ceil(d.total/d.per));
   var h='';d.rows.forEach(function(r){
    h+='<div class="ev"><span class="chip" style="background:'+RC[r['خطر']]+'">'+r['خطر_اسم']+'</span>'+
     '<div class="txt"><div>'+esc(r['الحدث'])+'</div><div class="meta">'+r['التاريخ']+' · '+esc(r['الدولة'])+' · '+esc(r['المدينة'])+
     (r['المصدر']?' · '+esc(r['المصدر']).slice(0,60):'')+'</div></div>'+
     '<div class="act"><button onclick="P.feat('+r.i+','+(r['مميز']?0:1)+')" title="إبراز في الموقع" style="color:'+(r['مميز']?'#eab308':'#94a3b8')+';font-size:16px">'+(r['مميز']?'★':'☆')+'</button>'+
     '<button onclick=\\'P.edit('+r.i+')\\'>✎ تعديل</button><button class="warn" onclick="P.del('+r.i+')">✗ حذف</button></div></div>'});
   document.getElementById('list').innerHTML=h||'<p style="text-align:center;color:#64748b">لا نتائج</p>';
  })},
 edit:function(i){var r=P.meta.rows.filter(function(x){return x.i===i})[0];if(!r)return;
  var f=document.getElementById('f');f.i.value=i;f['التاريخ'].value=r['التاريخ'];f['الدولة'].value=r['الدولة'];
  f['المدينة'].value=r['المدينة'];f['خط_عرض'].value=r['خط_عرض'];f['خط_طول'].value=r['خط_طول'];
  f['الحدث'].value=r['الحدث'];f['التفاصيل'].value=r['التفاصيل'];f['المصدر'].value=r['المصدر'];
  var rs=document.getElementById('riskSel');rs.innerHTML='';P.meta.rn.forEach(function(n,ix){rs.innerHTML+='<option value="'+ix+'"'+(ix===r['خطر']?' selected':'')+'>'+n+'</option>'});
  var sc=document.getElementById('scSel');sc.innerHTML='';P.meta.sc.forEach(function(n,ix){sc.innerHTML+='<option value="'+ix+'"'+(ix===r['نطاق']?' selected':'')+'>'+n+'</option>'});
  var nt=document.getElementById('nats');nt.innerHTML='';P.meta.nat.forEach(function(n){nt.innerHTML+='<label><input type="checkbox" value="'+n+'"'+(r['طبيعة'].indexOf(n)>-1?' checked':'')+'> '+n+'</label>'});
  document.getElementById('dlg').showModal()},
 submitEdit:function(ev){ev.preventDefault();var f=document.getElementById('f');
  var nats=Array.prototype.slice.call(document.querySelectorAll('#nats input:checked')).map(function(c){return c.value});
  var body={i:+f.i.value,'التاريخ':f['التاريخ'].value,'الدولة':f['الدولة'].value,'المدينة':f['المدينة'].value,
   'خط_عرض':f['خط_عرض'].value,'خط_طول':f['خط_طول'].value,'خطر':+document.getElementById('riskSel').value,
   'نطاق':+document.getElementById('scSel').value,'طبيعة':nats,'الحدث':f['الحدث'].value,'التفاصيل':f['التفاصيل'].value,'المصدر':f['المصدر'].value};
  fetch('/api/edit',{method:'POST',body:JSON.stringify(body)}).then(r=>r.json()).then(function(){
   document.getElementById('dlg').close();P.toast('✓ عُدِّل (غير محفوظ بعد)');P.go(P.page)})},
 feat:function(i,on){fetch('/api/feature',{method:'POST',body:JSON.stringify({i:i,on:on})}).then(r=>r.json()).then(function(){
  P.toast(on?'★ أُبرز — سيظهر في الشريط بعد الحفظ والنشر':'أُلغي الإبراز (غير محفوظ بعد)');P.go(P.page)})},
 del:function(i){if(!confirm('حذف هذا الحدث نهائيًا من الموقع؟'))return;
  fetch('/api/delete',{method:'POST',body:JSON.stringify({i:i})}).then(r=>r.json()).then(function(){P.toast('✓ حُذف (غير محفوظ بعد)');P.go(P.page)})},
 save:function(){fetch('/api/save',{method:'POST'}).then(r=>r.json()).then(function(d){P.toast('💾 حُفظ الملف محليًا ('+d.total+' حدثًا)');P.go(P.page)})},
 publish:function(){if(!confirm('حفظ ودفع التعديلات — سينشر Netlify الموقع المحدّث. متابعة؟'))return;
  P.toast('🚀 جارٍ النشر…');
  fetch('/api/publish',{method:'POST'}).then(r=>r.json()).then(function(d){
   P.toast(d.ok?'✓ نُشر — Netlify سيحدّث الموقع خلال دقيقة':'⚠ تعذّر النشر — راجع الطرفية');P.go(P.page)})},
 openAssess:function(){
  var sel=document.getElementById('aMonth'), ms=(P.meta&&P.meta.months)||[];
  sel.innerHTML=ms.map(function(m){return '<option value="'+m+'">'+m+'</option>'}).join('');
  P.loadAssess(); document.getElementById('adlg').showModal();},
 loadAssess:function(){
  var m=document.getElementById('aMonth').value, rep=(P.meta&&P.meta.reports&&P.meta.reports[m])||null;
  document.getElementById('aText').value=rep?rep.text:'';
  document.getElementById('aBy').value=rep?(rep.by||''):'';},
 saveAssess:function(ev){ev.preventDefault();
  var body={month:document.getElementById('aMonth').value,text:document.getElementById('aText').value,
   by:document.getElementById('aBy').value,date:new Date().toISOString().slice(0,10)};
  fetch('/api/assessment',{method:'POST',body:JSON.stringify(body)}).then(r=>r.json()).then(function(d){
   document.getElementById('adlg').close();
   P.toast(d.saved?'✓ حُفظ التقييم لشهر '+d.month+' (اضغط «حفظ ونشر» لإظهاره)':'✓ مُسح التقييم');P.go(P.page)})},
 openPages:function(){
  var pages=(P.meta&&P.meta.pages)||[], hidden=(P.meta&&P.meta.hidden)||[];
  document.getElementById('pgList').innerHTML=pages.map(function(p){
   var on=hidden.indexOf(p[0])<0;
   return '<label style="display:flex;align-items:center;justify-content:space-between;gap:10px;border:1px solid var(--line);border-radius:8px;padding:8px 12px">'+
    '<span>'+p[1]+' <span style="color:#94a3b8;font-size:12px">'+p[0]+'</span></span>'+
    '<input type="checkbox" data-path="'+p[0]+'"'+(on?' checked':'')+' style="width:18px;height:18px"></label>'}).join('');
  document.getElementById('pdlg').showModal();},
 savePages:function(ev){ev.preventDefault();
  var boxes=document.querySelectorAll('#pgList input[type=checkbox]'), hidden=[];
  Array.prototype.forEach.call(boxes,function(b){if(!b.checked)hidden.push(b.getAttribute('data-path'))});
  fetch('/api/pages',{method:'POST',body:JSON.stringify({hidden:hidden})}).then(r=>r.json()).then(function(d){
   document.getElementById('pdlg').close();
   P.toast('✓ '+(d.hidden.length?d.hidden.length+' صفحة مخفية':'كل الصفحات ظاهرة')+' (اضغط «حفظ ونشر»)');P.go(P.page)})},
 openFc:function(){P.renderFc();document.getElementById('fdlg').showModal()},
 renderFc:function(){
  var fcs=(P.meta&&P.meta.forecasts)||[], today=new Date().toISOString().slice(0,10);
  var oc={correct:['صحيح','#16a34a'],wrong:['خاطئ','#b91c1c'],partial:['جزئي','#0f766e']};
  document.getElementById('fcList').innerHTML=fcs.map(function(f){
   var late=!f.outcome&&f.horizon<=today;
   var st=f.outcome?oc[f.outcome]:[late?'مستحق ⚠':'مفتوح',late?'#b91c1c':'#64748b'];
   return '<div style="border:1.5px solid '+(late?'#b91c1c':'var(--line)')+';border-radius:10px;padding:10px 12px">'+
    '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'+
     '<span class="chip" style="background:'+st[1]+'">'+st[0]+'</span>'+
     '<span class="chip" style="background:#334155">ثقة '+f.confidence+'%</span>'+
     '<span class="meta">الأفق: '+f.horizon+(f.resolvedOn?' · أُغلق: '+f.resolvedOn:'')+'</span></div>'+
    '<div style="margin:7px 0 9px;font-size:13.5px;line-height:1.7">'+esc(f.statement)+'</div>'+
    '<div style="display:flex;gap:6px;flex-wrap:wrap">'+
     (f.outcome?'<button type="button" onclick=\\'P.fcSet("'+f.id+'",null)\\'>↺ إعادة فتح</button>'
      :'<button type="button" style="color:#16a34a" onclick=\\'P.fcSet("'+f.id+'","correct")\\'>✓ صحيح</button>'+
       '<button type="button" style="color:#b91c1c" onclick=\\'P.fcSet("'+f.id+'","wrong")\\'>✗ خاطئ</button>'+
       '<button type="button" onclick=\\'P.fcSet("'+f.id+'","partial")\\'>◐ جزئي</button>')+
    '</div></div>'}).join('')||'<p class="meta">لا توقعات مسجّلة.</p>'},
 fcSet:function(id,outcome){
  fetch('/api/forecast',{method:'POST',body:JSON.stringify({id:id,outcome:outcome})}).then(r=>r.json()).then(function(d){
   if(!d.ok){P.toast('⚠ '+(d.err||'خطأ'));return}
   var f=((P.meta&&P.meta.forecasts)||[]).filter(function(x){return x.id===id})[0];
   if(f){f.outcome=d.outcome;f.resolvedOn=d.resolvedOn}
   P.renderFc();P.toast(outcome?'✓ أُغلق التوقع — اضغط «حفظ ونشر» لتحديث الموقع':'↺ أُعيد فتح التوقع (غير محفوظ بعد)')})},
 openGate:function(){
  var g=(P.meta&&P.meta.gate)||{};
  var v=function(k,dflt){return g[k]==null?dflt:g[k]};
  document.getElementById('gOn').checked=v('on',1)!==0;
  document.getElementById('gLimit').value=v('limit',50);
  document.getElementById('gAssess').checked=v('assess',1)!==0;
  document.getElementById('gProfiles').checked=v('profiles',1)!==0;
  document.getElementById('gDossiers').checked=v('dossiers',1)!==0;
  document.getElementById('gXport').checked=v('xport',1)!==0;
  document.getElementById('gdlg').showModal()},
 saveGate:function(ev){ev.preventDefault();
  var body={on:document.getElementById('gOn').checked?1:0,
   limit:+document.getElementById('gLimit').value||0,
   assess:document.getElementById('gAssess').checked?1:0,
   profiles:document.getElementById('gProfiles').checked?1:0,
   dossiers:document.getElementById('gDossiers').checked?1:0,
   xport:document.getElementById('gXport').checked?1:0};
  fetch('/api/gate',{method:'POST',body:JSON.stringify(body)}).then(r=>r.json()).then(function(d){
   if(P.meta)P.meta.gate=d.gate;
   document.getElementById('gdlg').close();
   P.toast(body.on?'🔐 حُفظت إعدادات البوابة — اضغط «حفظ ونشر» لتفعيلها على الموقع':'🔓 البوابة معطّلة — الموقع كله مفتوح بعد «حفظ ونشر»')})}
};
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')}
var q=document.getElementById('q'),risk=document.getElementById('risk'),country=document.getElementById('country');
q.addEventListener('keydown',function(e){if(e.key==='Enter')P.go(1)});
P.go(1);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif u.path == "/api/list":
            self._send(200, api_list(parse_qs(u.query)))
        else:
            self._send(404, {"err": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        ln = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}
        try:
            if u.path == "/api/edit":
                self._send(200, api_edit(body))
            elif u.path == "/api/delete":
                self._send(200, api_delete(body))
            elif u.path == "/api/feature":
                self._send(200, api_feature(body))
            elif u.path == "/api/assessment":
                self._send(200, api_assessment(body))
            elif u.path == "/api/pages":
                self._send(200, api_pages(body))
            elif u.path == "/api/forecast":
                self._send(200, api_forecast(body))
            elif u.path == "/api/gate":
                self._send(200, api_gate(body))
            elif u.path == "/api/save":
                self._send(200, {"ok": True, "total": save()})
            elif u.path == "/api/publish":
                self._send(200, publish())
            else:
                self._send(404, {"err": "not found"})
        except Exception as e:
            self._send(500, {"err": str(e)})


def main():
    port = 8765
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    load()
    srv = HTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}"
    print(f"لوحة الأدمن تعمل: {url}  (أحداث: {len(STATE['data']['rows'])})  — Ctrl+C للإيقاف")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nتوقفت اللوحة.")


if __name__ == "__main__":
    main()
