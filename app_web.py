"""EcoCosta web (Flask). Misma base de datos y lógica que App.py, interfaz para celular.
Correr:  pip install flask  ->  python app_web.py  ->  abrir http://localhost:5000
"""
import sqlite3, hashlib, os, random
from flask import Flask, request, session, redirect, render_template, flash
from jinja2 import DictLoader

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ecocosta.db")
CATS = ["Basura / Escombros", "Contaminación del agua", "Quema de residuos",
        "Vertimiento ilegal", "Deforestación", "Otro"]
MUNICIPIOS = ["Fundación", "Aracataca"]
ESTADOS = ["Pendiente", "En proceso", "Resuelto"]
CONSEJOS = [
    ("♻️", "Separa tus residuos", "Organiza tu basura en orgánica, plástico, papel y vidrio."),
    ("🛍️", "Reduce las bolsas plásticas", "Usa bolsas reutilizables al hacer mercado."),
    ("🌱", "Composta en casa", "Los residuos orgánicos pueden convertirse en abono."),
    ("🔋", "Dispón bien las pilas", "Llévalas a puntos de recolección, nunca a la basura común."),
    ("💧", "Protege las fuentes de agua", "No arrojes basura cerca de quebradas ni ríos."),
]
INSIGNIAS = [("🌱", "Primera semilla", "Envía tu primer reporte", 1, "rep"),
             ("🌿", "Guardián activo", "Envía 5 reportes", 5, "rep"),
             ("🌳", "Árbol de la comunidad", "Envía 10 reportes", 10, "rep"),
             ("🏅", "50 puntos", "Acumula 50 puntos", 50, "pts"),
             ("🌎", "EcoHéroe", "Acumula 350 puntos", 350, "pts")]

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ecocosta-dev")

def q(sql, args=(), one=False, commit=False):
    con = sqlite3.connect(DB)
    cur = con.execute(sql, args)
    rows = cur.fetchone() if one else cur.fetchall()
    if commit: con.commit()
    con.close()
    return rows

def init_db():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        puntos INTEGER DEFAULT 0, nivel TEXT DEFAULT 'Semilla');
    CREATE TABLE IF NOT EXISTS reportes (id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL, lugar TEXT NOT NULL, descripcion TEXT NOT NULL,
        categoria TEXT DEFAULT 'General', foto_path TEXT, lat REAL, lon REAL,
        estado TEXT DEFAULT 'Pendiente', fecha TEXT DEFAULT (datetime('now','localtime')));
    CREATE TABLE IF NOT EXISTS respuestas_admin (id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporte_id INTEGER NOT NULL UNIQUE, respuesta TEXT NOT NULL, visto INTEGER DEFAULT 0,
        fecha TEXT DEFAULT (datetime('now','localtime')));""")
    con.commit(); con.close()

def nivel(p):
    for lim, n in [(50, "🌱 Semilla"), (150, "🌿 Brote"), (350, "🌳 Árbol"), (700, "🌲 Guardián")]:
        if p < lim: return n
    return "🌎 EcoHéroe"

def pw(p): return hashlib.sha256(p.encode()).hexdigest()
def logged(): return "uid" in session
def staff(): return session.get("rol") in ("admin", "interaseo")

@app.before_request
def guard():
    if request.endpoint not in ("login", "registro", "static", "manifest", "sw", "icono") and not logged():
        return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u, p = request.form["u"].strip(), request.form["p"]
        if (u, p) == ("admin", "admin123"):
            session.update(uid=0, user="admin", rol="admin")
        elif (u, p) == ("interaseo", "interaseo123"):
            session.update(uid=-1, user="interaseo", rol="interaseo")
        else:
            r = q("SELECT id FROM usuarios WHERE username=? AND password=?", (u, pw(p)), one=True)
            if not r:
                flash("Usuario o contraseña incorrectos"); return redirect("/login")
            session.update(uid=r[0], user=u, rol="user")
        return redirect("/")
    return render_template("login.html")

@app.route("/registro", methods=["POST"])
def registro():
    u, p = request.form["u"].strip(), request.form["p"]
    if not u or not p:
        flash("Completa usuario y contraseña")
    else:
        try:
            q("INSERT INTO usuarios (username,password) VALUES (?,?)", (u, pw(p)), commit=True)
            flash("Cuenta creada, ya puedes iniciar sesión")
        except sqlite3.IntegrityError:
            flash("Ese usuario ya existe")
    return redirect("/login")

@app.route("/salir")
def salir():
    session.clear(); return redirect("/login")

@app.route("/")
def inicio():
    pts = (q("SELECT puntos FROM usuarios WHERE id=?", (session["uid"],), one=True) or [0])[0]
    return render_template("inicio.html", pts=pts, nivel=nivel(pts), consejo=random.choice(CONSEJOS))

@app.route("/reportar", methods=["GET", "POST"])
def reportar():
    if staff(): return redirect("/panel")
    if request.method == "POST":
        f = request.form
        if not f["direccion"].strip() or not f["desc"].strip():
            flash("Completa dirección y descripción"); return redirect("/reportar")
        lat = float(f["lat"]) if f.get("lat") else None
        lon = float(f["lon"]) if f.get("lon") else None
        q("INSERT INTO reportes (usuario_id,lugar,descripcion,categoria,lat,lon) VALUES (?,?,?,?,?,?)",
          (session["uid"], f"{f['mun']} - {f['direccion'].strip()}", f["desc"].strip(), f["cat"], lat, lon),
          commit=True)
        q("UPDATE usuarios SET puntos=puntos+10 WHERE id=?", (session["uid"],), commit=True)
        flash("✔ Reporte enviado · +10 puntos")
        return redirect("/mis-reportes")
    return render_template("reportar.html", cats=CATS, muns=MUNICIPIOS)

@app.route("/mis-reportes")
def mis_reportes():
    rows = q("SELECT r.lugar,r.descripcion,r.categoria,r.fecha,r.estado,ra.respuesta FROM reportes r "
             "LEFT JOIN respuestas_admin ra ON ra.reporte_id=r.id WHERE r.usuario_id=? "
             "ORDER BY r.fecha DESC LIMIT 20", (session["uid"],))
    q("UPDATE respuestas_admin SET visto=1 WHERE reporte_id IN "
      "(SELECT id FROM reportes WHERE usuario_id=?)", (session["uid"],), commit=True)
    return render_template("mis.html", rows=rows)

@app.route("/logros")
def logros():
    uid = session["uid"]
    nrep = q("SELECT COUNT(*) FROM reportes WHERE usuario_id=?", (uid,), one=True)[0]
    pts = (q("SELECT puntos FROM usuarios WHERE id=?", (uid,), one=True) or [0])[0]
    ins = [(i, n, d, u, (nrep if t == "rep" else pts) >= u) for i, n, d, u, t in INSIGNIAS]
    rank = q("SELECT u.username,u.puntos,COUNT(r.id) FROM usuarios u LEFT JOIN reportes r "
             "ON r.usuario_id=u.id GROUP BY u.id ORDER BY u.puntos DESC, COUNT(r.id) DESC LIMIT 10")
    return render_template("logros.html", ins=ins, rank=rank)

@app.route("/panel")
def panel():
    if not staff(): return redirect("/")
    rows = q("SELECT r.id,r.lugar,r.descripcion,r.categoria,r.fecha,r.estado,u.username,ra.respuesta "
             "FROM reportes r JOIN usuarios u ON r.usuario_id=u.id "
             "LEFT JOIN respuestas_admin ra ON ra.reporte_id=r.id ORDER BY r.fecha DESC LIMIT 100")
    return render_template("panel.html", rows=rows, estados=ESTADOS)

@app.route("/panel/<int:rid>", methods=["POST"])
def panel_update(rid):
    if not staff(): return redirect("/")
    q("UPDATE reportes SET estado=? WHERE id=?", (request.form["estado"], rid), commit=True)
    if request.form.get("resp", "").strip():
        q("INSERT INTO respuestas_admin (reporte_id,respuesta,visto) VALUES (?,?,0) ON CONFLICT(reporte_id) "
          "DO UPDATE SET respuesta=excluded.respuesta, visto=0", (rid, request.form["resp"].strip()), commit=True)
    flash("Reporte actualizado")
    return redirect("/panel")

import zlib, struct, json
from flask import Response

@app.route("/manifest.json")
def manifest():
    ic = [{"src": f"/icono/{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": "any maskable"} for n in (192, 512)]
    return Response(json.dumps({"name": "EcoCosta", "short_name": "EcoCosta", "start_url": "/", "scope": "/",
        "display": "standalone", "background_color": "#0B0F0A", "theme_color": "#0B0F0A", "icons": ic}),
        mimetype="application/manifest+json")

@app.route("/sw.js")
def sw():
    return Response("self.addEventListener('install',e=>self.skipWaiting());"
                    "self.addEventListener('fetch',e=>{});", mimetype="application/javascript")

@app.route("/icono/<int:n>.png")
def icono(n):
    n = 512 if n > 192 else 192
    c = n / 2; rows = b""
    for y in range(n):
        row = b"\x00"
        for x in range(n):
            d = ((x - c) ** 2 + (y - c) ** 2) ** .5
            hoja = ((x - c) / (n * .30)) ** 2 + ((y - c) / (n * .18)) ** 2 < 1 and abs((x - c) - (y - c) * .9) < n * .30
            row += b"\xf0\xfd\xf4" if hoja else (b"\x4a\xde\x80" if d < n * .40 else b"\x0b\x0f\x0a")
        rows += row
    def ch(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) + \
          ch(b"IDAT", zlib.compress(rows, 9)) + ch(b"IEND", b"")
    return Response(png, mimetype="image/png")

T = {
"base.html": """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>EcoCosta</title><link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0B0F0A"><link rel="apple-touch-icon" href="/icono/192.png"><meta name="apple-mobile-web-app-capable" content="yes"><style>
:root{--bg:#0B0F0A;--card:#172113;--bd:#2A3D24;--ac:#4ADE80;--t1:#F0FDF4;--t2:#A7C3A0;--gold:#FCD34D;--warn:#FB923C}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t1);font:16px system-ui,sans-serif;padding:16px 14px 80px;max-width:560px;margin:auto}
h1{font-size:22px;color:var(--ac)}h2{font-size:17px;margin:18px 0 8px}.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:14px;margin:10px 0}
input,select,textarea,button{width:100%;padding:12px;margin:6px 0;border-radius:10px;border:1px solid var(--bd);background:#111A0F;color:var(--t1);font:inherit}
button{background:var(--ac);color:#08210f;font-weight:700;border:0}button.sec{background:#1E2D19;color:var(--t1)}
.muted{color:var(--t2);font-size:14px}.tag{font-size:12px;padding:2px 8px;border-radius:99px;background:#1E2D19;color:var(--warn)}
.msg{background:#1E2D19;border-left:4px solid var(--ac);padding:10px;border-radius:8px;margin:8px 0}
nav{position:fixed;bottom:0;left:0;right:0;display:flex;background:#111A0F;border-top:1px solid var(--bd)}
nav a{flex:1;text-align:center;padding:12px 4px;color:var(--t2);text-decoration:none;font-size:13px}nav a b{display:block;font-size:20px}
.off{opacity:.35}</style></head><body>
{% with m = get_flashed_messages() %}{% for x in m %}<div class="msg">{{x}}</div>{% endfor %}{% endwith %}
{% block c %}{% endblock %}
{% if session.uid is defined %}<nav><a href="/"><b>🏠</b>Inicio</a>
{% if session.rol=='user' %}<a href="/reportar"><b>📝</b>Reportar</a><a href="/mis-reportes"><b>📋</b>Mis reportes</a><a href="/logros"><b>🏆</b>Logros</a>
{% else %}<a href="/panel"><b>🛠️</b>Panel</a><a href="/logros"><b>🏆</b>Ranking</a>{% endif %}
<a href="/salir"><b>🚪</b>Salir</a></nav>{% endif %}<script>if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js')</script></body></html>""",
"login.html": """{% extends 'base.html' %}{% block c %}<h1>🌿 EcoCosta</h1><p class="muted">Reportes ambientales · Fundación y Aracataca</p>
<form method="post" class="card"><input name="u" placeholder="Usuario" required><input name="p" type="password" placeholder="Contraseña" required>
<button>Iniciar sesión</button><button class="sec" formaction="/registro">Crear cuenta</button></form>{% endblock %}""",
"inicio.html": """{% extends 'base.html' %}{% block c %}<h1>Hola, {{session.user}} 👋</h1>
{% if session.rol=='user' %}<div class="card"><div style="font-size:28px;color:var(--gold)">🏅 {{pts}} pts</div><div class="muted">Nivel: {{nivel}}</div></div>
<a href="/reportar"><button>📝 Nuevo reporte (+10 pts)</button></a>{% else %}<a href="/panel"><button>🛠️ Ir al panel de reportes</button></a>{% endif %}
<h2>Consejo del día</h2><div class="card"><b>{{consejo[0]}} {{consejo[1]}}</b><p class="muted">{{consejo[2]}}</p></div>{% endblock %}""",
"reportar.html": """{% extends 'base.html' %}{% block c %}<h1>📝 Nuevo reporte</h1><form method="post" class="card">
<select name="mun">{% for m in muns %}<option>{{m}}</option>{% endfor %}</select>
<input name="direccion" placeholder="Dirección o barrio" required>
<select name="cat">{% for c in cats %}<option>{{c}}</option>{% endfor %}</select>
<textarea name="desc" rows="4" placeholder="Describe el problema" required></textarea>
<input type="hidden" name="lat" id="lat"><input type="hidden" name="lon" id="lon">
<button type="button" class="sec" onclick="gps()">📍 Usar mi ubicación</button><div class="muted" id="gpsmsg">Sin ubicación GPS (opcional)</div>
<button>Enviar reporte</button></form>
<script>function gps(){navigator.geolocation.getCurrentPosition(function(p){lat.value=p.coords.latitude;lon.value=p.coords.longitude;
gpsmsg.textContent='✔ Ubicación guardada: '+p.coords.latitude.toFixed(5)+', '+p.coords.longitude.toFixed(5)},
function(){gpsmsg.textContent='No se pudo obtener la ubicación (revisa el permiso)'})}</script>{% endblock %}""",
"mis.html": """{% extends 'base.html' %}{% block c %}<h1>📋 Mis reportes</h1>{% for r in rows %}<div class="card">
<span class="tag">{{r[4]}}</span> <span class="tag">{{r[2]}}</span><p><b>{{r[0]}}</b></p><p class="muted">{{r[1]}}</p><div class="muted">{{r[3]}}</div>
{% if r[5] %}<div class="msg"><b>Respuesta:</b> {{r[5]}}</div>{% endif %}</div>{% else %}<p class="muted">Aún no has enviado reportes.</p>{% endfor %}{% endblock %}""",
"logros.html": """{% extends 'base.html' %}{% block c %}{% if session.rol=='user' %}<h1>🏆 Insignias</h1>{% for i in ins %}
<div class="card {{'' if i[4] else 'off'}}"><b>{{i[0]}} {{i[1]}}</b><div class="muted">{{i[2]}}</div></div>{% endfor %}{% endif %}
<h2>Ranking</h2>{% for r in rank %}<div class="card">{{loop.index}}. <b>{{r[0]}}</b> · 🏅 {{r[1]}} pts · {{r[2]}} reportes</div>{% endfor %}{% endblock %}""",
"panel.html": """{% extends 'base.html' %}{% block c %}<h1>🛠️ Panel de reportes</h1>{% for r in rows %}<div class="card">
<span class="tag">{{r[3]}}</span> <b>#{{r[0]}}</b> · {{r[6]}}<p><b>{{r[1]}}</b></p><p class="muted">{{r[2]}}</p>
<form method="post" action="/panel/{{r[0]}}"><select name="estado">{% for e in estados %}<option {{'selected' if e==r[5]}}>{{e}}</option>{% endfor %}</select>
<textarea name="resp" rows="2" placeholder="Respuesta al usuario">{{r[7] or ''}}</textarea><button>Guardar</button></form></div>
{% else %}<p class="muted">No hay reportes.</p>{% endfor %}{% endblock %}""",
}
app.jinja_loader = DictLoader(T)
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
