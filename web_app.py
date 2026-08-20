import html
import secrets
from datetime import datetime, timezone
from pathlib import Path

import discord
from aiohttp import web

from config import GUILD_ID, DISCORD_INVITE_URL
from database.db import (
    create_external_application,
    get_external_application_by_token,
    get_open_external_application_for_discord,
    get_setting,
    delete_external_application,
)
from cogs.external_applications import ExternalApplicationReviewView


ROOT = Path(__file__).resolve().parent
LOGO_PATH = ROOT / "web_static" / "logo.png"

RULES = [
    ("الالتزام بالزي الرسمي", "يجب الالتزام بالزي الرسمي المعتمد للمطعم طوال فترة العمل."),
    ("منع الأعمال الإجرامية بالزي الرسمي", "يُمنع منعًا باتًا القيام بأي عمل إجرامي أثناء ارتداء الزي الرسمي للمطعم، وأي مخالفة لذلك يترتب عليها الفصل من العمل."),
    ("احترام الزبائن وحسن التعامل", "يُمنع التعامل بقلة أدب أو حدة مع أي زبون، وأي تجاوز يثبت على الموظف قد يترتب عليه الفصل الفوري من العمل."),
    ("التعامل مع المشاكل", "في حال حدوث مشكلة أو سوء تفاهم مع أحد الزبائن، يجب الرجوع إلى المشرف المسؤول فورًا وتجنب الدخول في جدال أو تصعيد المشكلة."),
    ("تمثيل المطعم", "أسلوبك وتعاملك مع العميل يعكسان صورتك وصورة Bean Machine، لذلك يجب المحافظة دائمًا على التعامل المحترم والاحترافي."),
    ("الوجبات المجانية للموظفين", "يحق لكل موظف الحصول على 10 وجبات مجانية فقط، ويُمنع تجاوز العدد المحدد أو إساءة استخدام هذه الصلاحية."),
    ("منع البيع المجاني", "يُمنع منعًا باتًا تقديم أو بيع المنتجات مجانًا خارج الصلاحيات المسموحة، وأي شخص يثبت قيامه بذلك يترتب عليه الباند من المدينة."),
    ("الالتزام بالأسعار الرسمية", "يجب الالتزام بالأسعار الرسمية المعتمدة من إدارة المطعم، ويُمنع البيع بسعر أعلى أو أقل من السعر المحدد."),
    ("المطعم منطقة آمنة", "يُعتبر المطعم منطقة آمنة، ويُمنع التهديد أو القتل أو القيام بأي أعمال عدائية داخل منطقة المطعم."),
    ("التعامل مع المخالفات", "عند مشاهدة أي مخالفة من موظف أو مواطن، يجب رفع الأمر إلى الإدارة وعدم الرد على المخالفة بمخالفة أخرى، ومن يحاول معالجة الخطأ بالخطأ يتحمل مسؤولية مخالفته أيضًا."),
    ("استغلال الصلاحيات", "يُمنع استغلال الوظيفة أو صلاحيات الموظف لتحقيق منفعة شخصية أو منح امتيازات غير مصرح بها للآخرين."),
    ("تسجيل الدخول والخروج", "يجب تسجيل الدخول عند بدء العمل وتسجيل الخروج عند الانتهاء، ويُمنع تسجيل الدخول دون ممارسة العمل فعليًا."),
    ("التلاعب بالفواتير", "يُمنع إنشاء فواتير وهمية أو تكرار نفس الفاتورة بهدف زيادة النقاط أو الإحصائيات، وأي تلاعب يعرّض الموظف للعقوبة."),
    ("الالتزام بتعليمات الإدارة", "يجب الالتزام بتوجيهات المشرفين والإدارة المتعلقة بسير العمل، وفي حال وجود اعتراض يتم رفعه للإدارة بالطريقة المخصصة دون تعطيل العمل."),
]

CSS = r"""
:root{--bg:#0a0806;--panel:#18110d;--panel2:#21170f;--gold:#e7bc82;--gold2:#a66e3d;--cream:#f6ead9;--muted:#b9a58f;--ok:#76c18e;--bad:#d87373}
*{box-sizing:border-box}body{margin:0;color:var(--cream);font-family:Tahoma,Arial,sans-serif;background:radial-gradient(circle at 50% -10%,rgba(132,77,35,.22),transparent 32%),radial-gradient(circle at 8% 35%,rgba(83,46,22,.22),transparent 24%),radial-gradient(circle at 92% 38%,rgba(83,46,22,.18),transparent 24%),var(--bg);min-height:100vh}
body:before,body:after{content:"";position:fixed;z-index:-1;width:360px;height:360px;border-radius:50%;background:radial-gradient(ellipse at center,rgba(128,75,36,.15),transparent 65%);filter:blur(18px)}body:before{left:-120px;top:180px}body:after{right:-120px;top:300px}.wrap{width:min(1180px,92%);margin:auto}.header{padding-top:28px}.nav{height:92px;border:1px solid rgba(202,151,93,.24);border-radius:18px;display:flex;align-items:center;justify-content:space-between;padding:0 22px;background:linear-gradient(180deg,rgba(27,19,14,.96),rgba(16,11,8,.94));box-shadow:0 20px 50px #0007}.brand{display:flex;align-items:center;gap:14px}.brand img{width:58px;height:58px;object-fit:contain}.brand b{font-size:22px;letter-spacing:1.4px;color:var(--gold)}.navlinks{display:flex;gap:34px;color:#d6c6b5;font-size:15px}.navlinks a{text-decoration:none;color:inherit}.navlinks a:hover{color:var(--gold)}.top-btn{border:1px solid var(--gold2);background:transparent;color:var(--cream);padding:13px 28px;border-radius:13px;font-weight:700;cursor:pointer;text-decoration:none}.hero{text-align:center;padding:56px 0 26px}.hero img{width:180px;filter:drop-shadow(0 18px 25px #0008)}.hero h1{font-size:52px;letter-spacing:2px;color:var(--gold);margin:12px 0 12px}.divider{display:flex;align-items:center;justify-content:center;gap:14px;margin:18px auto;width:min(500px,90%)}.divider:before,.divider:after{content:"";height:1px;flex:1;background:linear-gradient(90deg,transparent,var(--gold2))}.divider:after{background:linear-gradient(90deg,var(--gold2),transparent)}.bean{font-size:22px;color:var(--gold)}.hero h2{margin:8px 0 6px;font-size:28px;color:var(--gold)}.hero p{color:var(--muted);font-size:17px}.choice-grid{display:grid;grid-template-columns:1fr 1fr;gap:42px;max-width:760px;margin:28px auto 70px}.choice{background:linear-gradient(180deg,rgba(28,20,15,.96),rgba(20,14,10,.98));border:1px solid rgba(202,151,93,.35);border-radius:22px;padding:30px 28px 26px;box-shadow:inset 0 0 30px rgba(216,162,96,.03),0 20px 50px #0006}.icon{width:82px;height:82px;margin:0 auto 18px;border-radius:50%;border:1px solid rgba(202,151,93,.35);display:grid;place-items:center;font-size:32px;color:var(--gold)}.choice h3{font-size:26px;margin:0 0 8px;text-align:center}.choice p{text-align:center;color:var(--muted);line-height:1.9;min-height:72px}.btn{display:inline-block;width:100%;border:0;border-radius:12px;padding:15px 18px;background:linear-gradient(90deg,#dba96e,#f0c98f);color:#201309;font-weight:800;font-size:17px;cursor:pointer;text-decoration:none;text-align:center}.btn.secondary{background:transparent;color:var(--cream);border:1px solid rgba(202,151,93,.35)}.section{padding:48px 0 70px}.section-head{text-align:center;margin-bottom:28px}.section-head img{width:90px}.section-head h2{font-size:34px;color:var(--gold);margin:10px 0 6px}.section-head p{color:var(--muted)}.rules{display:grid;grid-template-columns:1fr 1fr;gap:14px}.rule{display:grid;grid-template-columns:54px 1fr;gap:14px;padding:18px;background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid #38271c;border-radius:16px}.num{width:48px;height:48px;border-radius:13px;display:grid;place-items:center;border:1px solid #59412f;color:var(--gold);font-weight:700}.rule h3{margin:1px 0 7px;font-size:18px}.rule p{margin:0;color:var(--muted);line-height:1.75}.agree{margin:24px 0;display:flex;gap:10px;align-items:flex-start;background:#17100c;border:1px solid #3a291d;padding:18px;border-radius:15px}.agree input{width:auto;margin-top:5px;accent-color:var(--gold2)}.form-card,.status-card{max-width:800px;margin:auto;background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid #46301f;border-radius:22px;padding:28px;box-shadow:0 20px 55px #0007}.field{margin:0 0 18px}.field label{display:block;font-weight:700;margin-bottom:8px}.field small{display:block;color:var(--muted);margin-top:7px}input,textarea,select{width:100%;background:#0d0907;color:white;border:1px solid #4a3526;border-radius:11px;padding:13px;font:inherit;outline:none}textarea{min-height:110px;resize:vertical}.actions{display:flex;gap:12px;margin-top:22px}.actions .btn{width:auto;flex:1}.status-card{text-align:center;padding:52px 34px}.status-card>img{width:110px}.status-card h2{font-size:36px;margin:8px 0;color:var(--gold)}.status-card p{color:var(--muted);font-size:17px;line-height:1.8}.code{font:800 34px monospace;direction:ltr;background:#0d0907;border:1px solid #4a3526;border-radius:13px;padding:18px;margin:18px 0;color:var(--gold)}.alert{max-width:800px;margin:0 auto 20px;padding:15px;border-radius:12px;border:1px solid #603636;background:#261313;color:#f0b0b0}.track-code{font:700 20px monospace;direction:ltr;color:var(--gold)}footer{border-top:1px solid rgba(202,151,93,.12);padding:30px 0;color:#8c7b6a;text-align:center}@media(max-width:820px){.navlinks{display:none}.choice-grid,.rules{grid-template-columns:1fr}.hero h1{font-size:38px}.nav{height:auto;padding:14px}.top-btn{padding:11px 15px}}
"""


def shell(content: str, show_nav: bool = True) -> str:
    nav = """
    <div class="navlinks">
      <a href="/">الرئيسية</a><a href="/rules">القوانين</a><a href="/apply">التقديم</a><a href="/track">متابعة الطلب</a>
    </div>
    """ if show_nav else ""
    top_button = '<a class="top-btn" href="/rules">تقديم الآن</a>' if show_nav else ''
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bean Machine | Recruitment</title><style>{CSS}</style></head>
    <body><header class="header"><div class="wrap nav"><div class="brand"><img src="/static/logo.png"><b>BEAN MACHINE</b></div>{nav}{top_button}</div></header>{content}<footer><div class="wrap">Bean Machine Recruitment System</div></footer></body></html>'''


def rules_cards() -> str:
    return "".join(
        f'<div class="rule"><div class="num">{i:02}</div><div><h3>{html.escape(title)}</h3><p>{html.escape(desc)}</p></div></div>'
        for i, (title, desc) in enumerate(RULES, 1)
    )


def status_html(row) -> str:
    status = row[10]
    tracking = html.escape(row[11])
    if status == "pending":
        body = f'''<main><div class="wrap section"><div class="status-card"><img src="/static/logo.png"><h2>طلبك قيد المراجعة</h2><p>تم استلام طلبك بنجاح. عند اتخاذ قرار من الإدارة ستتغير حالته هنا تلقائيًا.</p><p>رمز المتابعة:</p><div class="track-code">{tracking}</div><p style="font-size:13px">يتم تحديث الحالة تلقائيًا.</p></div></div></main><script>setTimeout(()=>location.reload(),15000)</script>'''
    elif status == "rejected":
        body = f'''<main><div class="wrap section"><div class="status-card"><img src="/static/logo.png"><h2 style="color:var(--bad)">تم رفض الطلب</h2><p>تمت مراجعة طلبك من الإدارة وكانت النتيجة الرفض.</p><p>رمز المتابعة:</p><div class="track-code">{tracking}</div></div></div></main>'''
    elif status in ("accepted", "redeemed"):
        code = html.escape(row[12] or "")
        invite = html.escape(DISCORD_INVITE_URL, quote=True)
        invite_button = f'<a class="btn" href="{invite}" target="_blank" rel="noopener">دخول سيرفر Discord</a>' if invite else '<p>رابط السيرفر غير متاح حاليًا. تواصل مع الإدارة.</p>'
        used = '<p style="color:var(--ok)">تم استخدام رقم القبول وفتح تذكرتك في الدسكورد.</p>' if status == "redeemed" else ''
        body = f'''<main><div class="wrap section"><div class="status-card"><img src="/static/logo.png"><h2 style="color:var(--ok)">تم قبول طلبك</h2><p>انضم إلى السيرفر، ثم توجه إلى لوحة التقديم واضغط <b>طلب انضمام</b> وأدخل رقم القبول التالي. سيتحقق البوت من Discord ID ويفتح لك تذكرة خاصة مع الإدارة.</p><div class="code">{code}</div>{invite_button}{used}</div></div></main>'''
    else:
        body = '<main><div class="wrap section"><div class="status-card"><h2>حالة الطلب غير معروفة</h2></div></div></main>'
    return shell(body, show_nav=False)


async def static_logo(request):
    return web.FileResponse(LOGO_PATH)


async def home(request):
    token = request.cookies.get("bm_application")
    if token:
        row = await get_external_application_by_token(token)
        if row:
            return web.Response(text=status_html(row), content_type="text/html")

    content = '''<main><div class="wrap"><section class="hero"><img src="/static/logo.png"><h1>BEAN MACHINE</h1><div class="divider"><span class="bean">◒</span></div><h2>مرحبًا بك في عائلة بن مشين</h2><p>ابدأ رحلتك معنا وكن جزءًا من فريقنا.</p></section><section class="choice-grid"><article class="choice"><div class="icon">♙</div><h3>تقديم جديد</h3><p>اقرأ قوانين العمل ثم أكمل نموذج التقديم وأرسل طلبك للإدارة.</p><a class="btn" href="/rules">ابدأ التقديم ←</a></article><article class="choice"><div class="icon">▤</div><h3>متابعة طلب سابق</h3><p>استخدم رمز المتابعة إذا فتحت الموقع من جهاز أو متصفح مختلف.</p><a class="btn" href="/track">تابع طلبك ←</a></article></section></div></main>'''
    return web.Response(text=shell(content), content_type="text/html")


async def rules_page(request):
    token = request.cookies.get("bm_application")
    if token and await get_external_application_by_token(token):
        raise web.HTTPFound("/")

    content = f'''<main><div class="wrap section"><div class="section-head"><img src="/static/logo.png"><h2>قوانين Bean Machine</h2><p>اقرأ جميع البنود قبل متابعة التقديم.</p></div><div class="rules">{rules_cards()}</div><form method="post" action="/agree"><label class="agree"><input type="checkbox" name="agree" required> أقر بأنني قرأت جميع قوانين Bean Machine وأوافق على الالتزام بها، وأتحمل مسؤولية أي مخالفة تصدر مني.</label><div style="max-width:420px;margin:auto"><button class="btn" type="submit">أوافق وأكمل التقديم</button></div></form></div></main>'''
    return web.Response(text=shell(content), content_type="text/html")


async def agree(request):
    data = await request.post()
    if data.get("agree") != "on":
        raise web.HTTPFound("/rules")
    response = web.HTTPFound("/apply")
    response.set_cookie("bm_rules", "accepted", max_age=1800, httponly=True, samesite="Lax")
    return response


async def apply_page(request):
    token = request.cookies.get("bm_application")
    if token and await get_external_application_by_token(token):
        raise web.HTTPFound("/")
    if request.cookies.get("bm_rules") != "accepted":
        raise web.HTTPFound("/rules")

    error = request.query.get("error")
    alert = f'<div class="alert">{html.escape(error)}</div>' if error else ""
    content = f'''<main><div class="wrap section">{alert}<form class="form-card" method="post" action="/apply"><div class="section-head"><img src="/static/logo.png"><h2>نموذج التقديم</h2><p>جاوب بوضوح؛ إجاباتك تذهب مباشرة للإدارة.</p></div><div class="field"><label>Discord ID</label><input name="discord_id" inputmode="numeric" pattern="[0-9]{{15,22}}" maxlength="22" required placeholder="123456789012345678"><small>رقم القبول النهائي سيكون مربوطًا بهذا الحساب.</small></div><div class="field"><label>ليش حاب تنضم إلى Bean Machine؟</label><textarea name="reason" maxlength="1000" required></textarea></div><div class="field"><label>كم ساعة تقدر تشتغل باليوم؟</label><input name="daily_hours" maxlength="100" required></div><div class="field"><label>وش الأوقات اللي غالبًا تكون متواجد فيها؟</label><input name="availability" maxlength="200" required></div><div class="field"><label>هل سبق واشتغلت في مطعم أو وظيفة داخل المدينة؟ إذا نعم، اذكرها.</label><textarea name="previous_experience" maxlength="1000" required></textarea></div><div class="field"><label>كيف تتصرف لو واجهت زبون متعصب أو قليل أدب؟</label><textarea name="difficult_customer" maxlength="1000" required></textarea></div><div class="field"><label>هل أنت مستعد للالتزام بأنظمة المطعم واللبس الرسمي؟</label><select name="uniform_commitment" required><option value="">اختر</option><option value="نعم">نعم</option><option value="لا">لا</option></select></div><div class="field"><label>هل قرأت جميع قوانين العمل وتوافق عليها؟</label><select name="rules_agreement" required><option value="">اختر</option><option value="نعم">نعم</option><option value="لا">لا</option></select></div><div class="actions"><a class="btn secondary" href="/rules">رجوع</a><button class="btn" type="submit">إرسال الطلب</button></div></form></div></main>'''
    return web.Response(text=shell(content), content_type="text/html")


async def submit_application(request):
    if request.cookies.get("bm_rules") != "accepted":
        raise web.HTTPFound("/rules")

    data = await request.post()
    discord_raw = str(data.get("discord_id", "")).strip()
    if not discord_raw.isdigit() or not (15 <= len(discord_raw) <= 22):
        raise web.HTTPFound("/apply?error=Discord+ID+غير+صحيح")
    discord_id = int(discord_raw)

    keys = [
        "reason", "daily_hours", "availability", "previous_experience",
        "difficult_customer", "uniform_commitment", "rules_agreement",
    ]
    answers = {key: str(data.get(key, "")).strip() for key in keys}
    if not all(answers.values()):
        raise web.HTTPFound("/apply?error=يرجى+تعبئة+جميع+الحقول")
    if answers["uniform_commitment"] != "نعم" or answers["rules_agreement"] != "نعم":
        raise web.HTTPFound("/apply?error=يجب+الموافقة+على+الأنظمة+لإرسال+الطلب")

    # Prevent multiple active website applications for the same Discord account.
    existing = await get_open_external_application_for_discord(GUILD_ID, discord_id)
    if existing:
        response = web.HTTPFound("/")
        response.set_cookie("bm_application", existing[11], max_age=31536000, httponly=True, samesite="Lax")
        return response

    bot = request.app["bot"]
    guild = bot.get_guild(GUILD_ID)
    review_id = await get_setting(GUILD_ID, "application_review")
    channel = guild.get_channel(int(review_id)) if guild and review_id else None
    if not isinstance(channel, discord.TextChannel):
        raise web.HTTPFound("/apply?error=التقديم+غير+متاح+مؤقتًا.+تواصل+مع+الإدارة")

    tracking_token = f"BM-T-{secrets.token_hex(8).upper()}"
    application_id = await create_external_application(
        GUILD_ID,
        discord_id,
        answers,
        tracking_token,
        datetime.now(timezone.utc).isoformat(),
    )

    embed = discord.Embed(
        title="طلب تقديم جديد من الموقع",
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Discord ID", value=f"`{discord_id}`\n<@{discord_id}>", inline=False)
    embed.add_field(name="ليش حاب تنضم إلى Bean Machine؟", value=answers["reason"][:1024], inline=False)
    embed.add_field(name="كم ساعة تقدر تشتغل باليوم؟", value=answers["daily_hours"][:1024], inline=False)
    embed.add_field(name="أوقات التواجد", value=answers["availability"][:1024], inline=False)
    embed.add_field(name="الخبرة السابقة", value=answers["previous_experience"][:1024], inline=False)
    embed.add_field(name="التعامل مع زبون متعصب", value=answers["difficult_customer"][:1024], inline=False)
    embed.add_field(name="الالتزام بالأنظمة واللبس", value=answers["uniform_commitment"], inline=True)
    embed.add_field(name="قراءة القوانين والموافقة", value=answers["rules_agreement"], inline=True)
    embed.add_field(name="رمز المتابعة", value=f"`{tracking_token}`", inline=False)
    embed.set_footer(text=f"Web Application #{application_id}")
    try:
        await channel.send(
            embed=embed,
            view=ExternalApplicationReviewView(application_id),
        )
    except discord.HTTPException:
        await delete_external_application(application_id)
        raise web.HTTPFound("/apply?error=تعذر+إرسال+الطلب+للإدارة.+حاول+مرة+أخرى")

    response = web.HTTPFound("/")
    response.set_cookie("bm_application", tracking_token, max_age=31536000, httponly=True, samesite="Lax")
    response.del_cookie("bm_rules")
    return response


async def track_page(request):
    token = request.cookies.get("bm_application")
    if token:
        row = await get_external_application_by_token(token)
        if row:
            return web.Response(text=status_html(row), content_type="text/html")

    error = request.query.get("error")
    alert = f'<div class="alert">{html.escape(error)}</div>' if error else ""
    content = f'''<main><div class="wrap section">{alert}<form class="form-card" method="post" action="/track"><div class="section-head"><img src="/static/logo.png"><h2>متابعة الطلب</h2><p>إذا فتحت الموقع من متصفح آخر، أدخل رمز المتابعة الذي ظهر لك بعد التقديم.</p></div><div class="field"><label>رمز المتابعة</label><input name="tracking_token" maxlength="40" required placeholder="BM-T-..."></div><button class="btn" type="submit">عرض حالة الطلب</button></form></div></main>'''
    return web.Response(text=shell(content), content_type="text/html")


async def track_submit(request):
    data = await request.post()
    token = str(data.get("tracking_token", "")).strip().upper()
    row = await get_external_application_by_token(token)
    if not row:
        raise web.HTTPFound("/track?error=رمز+المتابعة+غير+صحيح")
    response = web.HTTPFound("/")
    response.set_cookie("bm_application", token, max_age=31536000, httponly=True, samesite="Lax")
    return response


async def start_web_server(bot, port: int):
    app = web.Application(client_max_size=1024 * 1024)
    app["bot"] = bot
    app.router.add_get("/static/logo.png", static_logo)
    app.router.add_get("/", home)
    app.router.add_get("/rules", rules_page)
    app.router.add_post("/agree", agree)
    app.router.add_get("/apply", apply_page)
    app.router.add_post("/apply", submit_application)
    app.router.add_get("/track", track_page)
    app.router.add_post("/track", track_submit)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner
