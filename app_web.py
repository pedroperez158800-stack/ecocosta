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
app.config["MAX_FORM_MEMORY_SIZE"] = 8 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

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
    for sql in ["ALTER TABLE usuarios ADD COLUMN foto_perfil TEXT", "ALTER TABLE usuarios ADD COLUMN bio TEXT",
        "CREATE TABLE IF NOT EXISTS apoyos (reporte_id INTEGER, usuario_id INTEGER, PRIMARY KEY (reporte_id, usuario_id))",
        "CREATE TABLE IF NOT EXISTS actividad (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL, tipo TEXT NOT NULL, descripcion TEXT NOT NULL, fecha TEXT DEFAULT (datetime('now','localtime')))"]:
        try: q(sql, commit=True)
        except Exception: pass

def nivel(p):
    for lim, n in [(50, "🌱 Semilla"), (150, "🌿 Brote"), (350, "🌳 Árbol"), (700, "🌲 Guardián")]:
        if p < lim: return n
    return "🌎 EcoHéroe"

def log(uid, tipo, desc):
    if uid and uid > 0:
        q("INSERT INTO actividad (usuario_id,tipo,descripcion) VALUES (?,?,?)", (uid, tipo, desc), commit=True)

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
            log(r[0], "login", "Inició sesión")
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
    sig = next((l for l in (50, 150, 350, 700) if pts < l), None)
    pend = q("SELECT COUNT(*) FROM reportes WHERE estado='Pendiente'", one=True)[0]
    return render_template("inicio.html", pts=pts, nivel=nivel(pts), consejo=random.choice(CONSEJOS), sig=sig, pend=pend)

@app.route("/reportar", methods=["GET", "POST"])
def reportar():
    if staff(): return redirect("/panel")
    if request.method == "POST":
        f = request.form
        if not f["direccion"].strip() or not f["desc"].strip():
            flash("Completa dirección y descripción"); return redirect("/reportar")
        lat = float(f["lat"]) if f.get("lat") else None
        lon = float(f["lon"]) if f.get("lon") else None
        foto = f["foto"] if f.get("foto", "").startswith("data:image/") else None
        q("INSERT INTO reportes (usuario_id,lugar,descripcion,categoria,foto_path,lat,lon) VALUES (?,?,?,?,?,?,?)",
          (session["uid"], f"{f['mun']} - {f['direccion'].strip()}", f["desc"].strip(), f["cat"], foto, lat, lon),
          commit=True)
        q("UPDATE usuarios SET puntos=puntos+10 WHERE id=?", (session["uid"],), commit=True)
        log(session["uid"], "reporte", f"Envió un reporte: {f['cat']} (+10 pts)")
        flash("✔ Reporte enviado · +10 puntos")
        return redirect("/mis-reportes")
    return render_template("reportar.html", cats=CATS, muns=MUNICIPIOS)

@app.route("/mis-reportes")
def mis_reportes():
    rows = q("SELECT r.lugar,r.descripcion,r.categoria,r.fecha,r.estado,ra.respuesta,r.foto_path,r.id FROM reportes r "
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

@app.route("/comunidad")
def comunidad():
    uid, qs = session["uid"], request.args.get("q", "").strip()
    w, a = "", [uid]
    if qs:
        w = "WHERE r.lugar LIKE ? OR r.descripcion LIKE ? OR r.categoria LIKE ? "; a += [f"%{qs}%"] * 3
    rows = q("SELECT r.id,r.lugar,r.descripcion,r.categoria,r.estado,r.fecha,r.foto_path,u.username,"
             "(SELECT COUNT(*) FROM apoyos x WHERE x.reporte_id=r.id),"
             "(SELECT COUNT(*) FROM apoyos x WHERE x.reporte_id=r.id AND x.usuario_id=?),r.usuario_id "
             "FROM reportes r JOIN usuarios u ON u.id=r.usuario_id " + w + "ORDER BY r.id DESC LIMIT 30", a)
    return render_template("comunidad.html", rows=rows, qs=qs, uid=uid)

@app.route("/apoyar/<int:rid>", methods=["POST"])
def apoyar(rid):
    if staff(): return redirect("/comunidad")
    r = q("SELECT usuario_id FROM reportes WHERE id=?", (rid,), one=True)
    if r and r[0] != session["uid"]:
        try:
            q("INSERT INTO apoyos VALUES (?,?)", (rid, session["uid"]), commit=True)
            q("UPDATE usuarios SET puntos=puntos+2 WHERE id=?", (r[0],), commit=True)
            log(r[0], "apoyo", f"{session['user']} apoyó tu reporte #{rid} (+2 pts)")
            log(session["uid"], "apoyo", f"Apoyaste el reporte #{rid}")
        except sqlite3.IntegrityError:
            pass
    return redirect(request.referrer or "/comunidad")

@app.route("/eliminar/<int:rid>", methods=["POST"])
def eliminar(rid):
    uid = session["uid"]
    r = q("SELECT estado FROM reportes WHERE id=? AND usuario_id=?", (rid, uid), one=True)
    if r and r[0] == "Pendiente":
        for t in ("reportes WHERE id", "respuestas_admin WHERE reporte_id", "apoyos WHERE reporte_id"):
            q(f"DELETE FROM {t}=?", (rid,), commit=True)
        q("UPDATE usuarios SET puntos=MAX(puntos-10,0) WHERE id=?", (uid,), commit=True)
        log(uid, "reporte", f"Eliminó su reporte #{rid}"); flash("Reporte eliminado")
    else:
        flash("Solo puedes eliminar reportes pendientes")
    return redirect("/mis-reportes")

@app.route("/consejos")
def consejos():
    return render_template("consejos.html", cs=CONSEJOS)

@app.route("/usuarios")
def usuarios():
    if not staff(): return redirect("/")
    rows = q("SELECT u.username,u.puntos,COUNT(r.id) FROM usuarios u LEFT JOIN reportes r ON r.usuario_id=u.id "
             "GROUP BY u.id ORDER BY u.puntos DESC")
    return render_template("usuarios.html", rows=[(n, p, c, nivel(p)) for n, p, c in rows])

@app.route("/demo", methods=["POST"])
def demo():
    if not staff(): return redirect("/")
    if q("SELECT 1 FROM usuarios WHERE username='maria_ecolover'", one=True):
        flash("Los datos de ejemplo ya estaban cargados"); return redirect("/")
    ids = []
    for u in ("maria_ecolover", "juan_verde", "sofia_costa"):
        q("INSERT INTO usuarios (username,password) VALUES (?,?)", (u, pw("1234")), commit=True)
        ids.append(q("SELECT id FROM usuarios WHERE username=?", (u,), one=True)[0])
    datos = [(0, "Fundación - Calle 12 con Carrera 5", "Montón de escombros bloqueando el andén", "Basura / Escombros", 10.5208, -74.1836, "Pendiente"),
             (1, "Fundación - Río Fundación, sector puente", "Vertimiento de aguas residuales al río", "Vertimiento ilegal", 10.5255, -74.1900, "En proceso"),
             (2, "Aracataca - Barrio Centro", "Quema de basura en lote baldío", "Quema de residuos", 10.5919, -74.1895, "Pendiente"),
             (0, "Aracataca - Vía a Sevilla", "Tala de árboles sin permiso", "Deforestación", 10.5850, -74.2000, "Resuelto"),
             (1, "Fundación - Barrio Obrero", "Agua estancada con residuos en el caño", "Contaminación del agua", 10.5160, -74.1890, "En proceso"),
             (2, "Fundación - Parque Principal", "Basura acumulada tras el fin de semana", "Basura / Escombros", 10.5230, -74.1850, "Resuelto")]
    for i, lugar, desc, cat, la, lo, est in datos:
        q("INSERT INTO reportes (usuario_id,lugar,descripcion,categoria,lat,lon,estado) VALUES (?,?,?,?,?,?,?)",
          (ids[i], lugar, desc, cat, la, lo, est), commit=True)
        q("UPDATE usuarios SET puntos=puntos+10 WHERE id=?", (ids[i],), commit=True)
    for (rid,) in q("SELECT id FROM reportes WHERE estado='Resuelto'"):
        q("INSERT OR IGNORE INTO respuestas_admin (reporte_id,respuesta) VALUES (?,?)",
          (rid, "Atendido por la cuadrilla de Interaseo. ¡Gracias por reportar!"), commit=True)
    flash("✔ Datos de ejemplo cargados (usuarios de prueba con clave 1234)")
    return redirect("/")

@app.route("/mapa")
def mapa():
    pts = [dict(lugar=l, cat=c, estado=e, lat=la, lon=lo) for l, c, e, la, lo in
           q("SELECT lugar,categoria,estado,lat,lon FROM reportes WHERE lat IS NOT NULL AND lon IS NOT NULL ORDER BY id DESC LIMIT 300")]
    return render_template("mapa.html", pts=pts)

@app.route("/exportar.csv")
def exportar():
    if not staff(): return redirect("/")
    import csv, io
    o = io.StringIO(); w = csv.writer(o)
    w.writerow(["id", "usuario", "lugar", "categoria", "estado", "fecha", "descripcion", "lat", "lon"])
    w.writerows(q("SELECT r.id,u.username,r.lugar,r.categoria,r.estado,r.fecha,r.descripcion,r.lat,r.lon "
                  "FROM reportes r JOIN usuarios u ON u.id=r.usuario_id ORDER BY r.id"))
    return Response("\ufeff" + o.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=reportes_ecocosta.csv"})

ICONOS = {"login": "🔑", "reporte": "📝", "perfil": "👤", "respuesta": "💬", "estado": "🔄", "apoyo": "👍"}

@app.route("/stats")
def stats():
    w, a = ("", ()) if staff() else ("WHERE usuario_id=?", (session["uid"],))
    tot = q(f"SELECT COUNT(*) FROM reportes {w}", a, one=True)[0]
    est = dict(q(f"SELECT estado,COUNT(*) FROM reportes {w} GROUP BY estado", a))
    cat = q(f"SELECT categoria,COUNT(*) c FROM reportes {w} GROUP BY categoria ORDER BY c DESC", a)
    dia = q(f"SELECT date(fecha),COUNT(*) FROM reportes {w} GROUP BY date(fecha) ORDER BY date(fecha) DESC LIMIT 7", a)[::-1]
    return render_template("stats.html", tot=tot, est=est, estados=ESTADOS, cat=cat, dia=dia,
                           tasa=int(est.get("Resuelto", 0) * 100 / tot) if tot else 0, mc=max([n for _, n in cat] or [1]), md=max([n for _, n in dia] or [1]))

@app.route("/actividad")
def actividad():
    if staff():
        rows = q("SELECT a.tipo,a.descripcion,a.fecha,u.username FROM actividad a "
                 "LEFT JOIN usuarios u ON u.id=a.usuario_id ORDER BY a.id DESC LIMIT 30")
    else:
        rows = q("SELECT tipo,descripcion,fecha,NULL FROM actividad WHERE usuario_id=? ORDER BY id DESC LIMIT 20",
                 (session["uid"],))
    return render_template("actividad.html", rows=[(ICONOS.get(t, "•"), d, f, u) for t, d, f, u in rows])

@app.context_processor
def avisos():
    n = 0
    if session.get("rol") == "user":
        n = q("SELECT COUNT(*) FROM respuestas_admin ra JOIN reportes r ON ra.reporte_id=r.id "
              "WHERE r.usuario_id=? AND ra.visto=0", (session["uid"],), one=True)[0]
    return {"nuevas": n}

@app.route("/perfil", methods=["GET", "POST"])
def perfil():
    if staff(): return redirect("/")
    uid = session["uid"]
    if request.method == "POST":
        if request.form.get("foto", "").startswith("data:image/"):
            q("UPDATE usuarios SET foto_perfil=? WHERE id=?", (request.form["foto"], uid), commit=True)
        q("UPDATE usuarios SET bio=? WHERE id=?", (request.form.get("bio", "").strip()[:300], uid), commit=True)
        log(uid, "perfil", "Actualizó su perfil"); flash("Perfil actualizado"); return redirect("/perfil")
    foto, bio, pts = q("SELECT foto_perfil,bio,puntos FROM usuarios WHERE id=?", (uid,), one=True)
    nrep = q("SELECT COUNT(*) FROM reportes WHERE usuario_id=?", (uid,), one=True)[0]
    return render_template("perfil.html", foto=foto, bio=bio or "", pts=pts, nivel=nivel(pts), nrep=nrep)

@app.route("/panel")
def panel():
    if not staff(): return redirect("/")
    est, cat = request.args.get("estado", ""), request.args.get("cat", "")
    w, a = [], []
    if est in ESTADOS: w.append("r.estado=?"); a.append(est)
    if cat in CATS: w.append("r.categoria=?"); a.append(cat)
    rows = q("SELECT r.id,r.lugar,r.descripcion,r.categoria,r.fecha,r.estado,u.username,ra.respuesta,r.foto_path "
             "FROM reportes r JOIN usuarios u ON r.usuario_id=u.id "
             "LEFT JOIN respuestas_admin ra ON ra.reporte_id=r.id " + ("WHERE " + " AND ".join(w) + " " if w else "") +
             "ORDER BY r.fecha DESC LIMIT 100", a)
    return render_template("panel.html", rows=rows, estados=ESTADOS, cats=CATS, est=est, cat=cat)

@app.route("/panel/<int:rid>", methods=["POST"])
def panel_update(rid):
    if not staff(): return redirect("/")
    q("UPDATE reportes SET estado=? WHERE id=?", (request.form["estado"], rid), commit=True)
    if request.form.get("resp", "").strip():
        q("INSERT INTO respuestas_admin (reporte_id,respuesta,visto) VALUES (?,?,0) ON CONFLICT(reporte_id) "
          "DO UPDATE SET respuesta=excluded.respuesta, visto=0", (rid, request.form["resp"].strip()), commit=True)
    dueno = (q("SELECT usuario_id FROM reportes WHERE id=?", (rid,), one=True) or [0])[0]
    log(dueno, "estado", f"Tu reporte #{rid} ahora está: {request.form['estado']}")
    if request.form.get("resp", "").strip(): log(dueno, "respuesta", f"Respondieron tu reporte #{rid}")
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
<meta name="viewport" content="width=device-width,initial-scale=1"><title>EcoCosta</title><script>try{document.documentElement.dataset.theme=localStorage.getItem('t')||'dark'}catch(e){}</script><link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0B0F0A"><link rel="apple-touch-icon" href="/icono/192.png"><meta name="apple-mobile-web-app-capable" content="yes"><style>
:root{--bg:#0B0F0A;--card:#172113;--bd:#2A3D24;--ac:#4ADE80;--t1:#F0FDF4;--t2:#A7C3A0;--gold:#FCD34D;--warn:#FB923C;--c2:#1E2D19;--in:#111A0F}
html[data-theme=light]{--bg:#F4FAF3;--card:#FFFFFF;--bd:#CFE3CB;--ac:#16A34A;--t1:#10230F;--t2:#4B6B47;--gold:#B45309;--warn:#C2410C;--c2:#E4F2E1;--in:#F1F8EF}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t1);font:16px system-ui,sans-serif;padding:44px 14px 80px;max-width:560px;margin:auto}
h1{font-size:22px;color:var(--ac)}h2{font-size:17px;margin:18px 0 8px}.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:14px;margin:10px 0}
input,select,textarea,button{width:100%;padding:12px;margin:6px 0;border-radius:10px;border:1px solid var(--bd);background:var(--in);color:var(--t1);font:inherit}
button{background:var(--ac);color:#08210f;font-weight:700;border:0}button.sec{background:var(--c2);color:var(--t1)}
.muted{color:var(--t2);font-size:14px}.tag{font-size:12px;padding:2px 8px;border-radius:99px;background:var(--c2);color:var(--warn)}
.msg{background:var(--c2);border-left:4px solid var(--ac);padding:10px;border-radius:8px;margin:8px 0}
nav{position:fixed;bottom:0;left:0;right:0;display:flex;overflow-x:auto;background:var(--in);border-top:1px solid var(--bd)}
nav a{flex:1 0 auto;min-width:68px;text-align:center;padding:12px 4px;color:var(--t2);text-decoration:none;font-size:13px}nav a b{display:block;font-size:20px}
.off{opacity:.35}</style></head><body>
<button onclick="tema()" style="position:fixed;top:8px;right:8px;width:auto;padding:6px 10px;margin:0;z-index:9;background:var(--card);color:var(--t1);border:1px solid var(--bd)">🌓</button>
{% with m = get_flashed_messages() %}{% for x in m %}<div class="msg">{{x}}</div>{% endfor %}{% endwith %}
{% block c %}{% endblock %}
{% if session.uid is defined %}<nav><a href="/"><b>🏠</b>Inicio</a>
{% if session.rol=='user' %}<a href="/reportar"><b>📝</b>Reportar</a><a href="/comunidad"><b>👥</b>Comunidad</a><a href="/mis-reportes"><b>📋{% if nuevas %}<span style="background:#EF4444;border-radius:99px;font-size:11px;padding:1px 6px;vertical-align:top">{{nuevas}}</span>{% endif %}</b>Mis reportes</a><a href="/logros"><b>🏆</b>Logros</a><a href="/perfil"><b>👤</b>Perfil</a><a href="/stats"><b>📊</b>Stats</a><a href="/actividad"><b>🕒</b>Actividad</a><a href="/mapa"><b>🗺️</b>Mapa</a>
{% else %}<a href="/panel"><b>🛠️</b>Panel</a><a href="/comunidad"><b>👥</b>Comunidad</a><a href="/usuarios"><b>🧑‍🤝‍🧑</b>Usuarios</a><a href="/stats"><b>📊</b>Stats</a><a href="/actividad"><b>🕒</b>Actividad</a><a href="/mapa"><b>🗺️</b>Mapa</a><a href="/logros"><b>🏆</b>Ranking</a>{% endif %}
<a href="/salir"><b>🚪</b>Salir</a></nav>{% endif %}<script>function tema(){var d=document.documentElement,n=d.dataset.theme=='light'?'dark':'light';d.dataset.theme=n;try{localStorage.setItem('t',n)}catch(e){}}
function foto(i,t,p){var f=i.files[0];if(!f)return;var r=new FileReader();r.onload=function(e){var im=new Image();
im.onload=function(){var s=Math.min(1,800/Math.max(im.width,im.height)),c=document.createElement('canvas');c.width=im.width*s;c.height=im.height*s;
c.getContext('2d').drawImage(im,0,0,c.width,c.height);var d=c.toDataURL('image/jpeg',.7);document.getElementById(t).value=d;
var v=document.getElementById(p);v.src=d;v.style.display='block'};im.src=e.target.result};r.readAsDataURL(f)}
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js')</script></body></html>""",
"login.html": """{% extends 'base.html' %}{% block c %}<h1>🌿 EcoCosta</h1><p class="muted">Reportes ambientales · Fundación y Aracataca</p>
<form method="post" class="card"><input name="u" placeholder="Usuario" required><input name="p" type="password" placeholder="Contraseña" required>
<button>Iniciar sesión</button><button class="sec" formaction="/registro">Crear cuenta</button></form>{% endblock %}""",
"inicio.html": """{% extends 'base.html' %}{% block c %}<h1>Hola, {{session.user}} 👋</h1>{% if nuevas %}<a href="/mis-reportes" style="text-decoration:none;color:inherit"><div class="msg">🔔 Tienes {{nuevas}} respuesta(s) nueva(s) a tus reportes</div></a>{% endif %}
{% if session.rol=='user' %}<div class="card"><div style="font-size:28px;color:var(--gold)">🏅 {{pts}} pts</div><div class="muted">Nivel: {{nivel}}</div>{% if sig %}<div style="background:var(--c2);border-radius:6px;margin:8px 0 4px"><div style="width:{{(pts*100/sig)|int}}%;background:var(--ac);height:10px;border-radius:6px"></div></div><div class="muted">{{sig-pts}} pts para el siguiente nivel</div>{% endif %}</div>
<a href="/reportar"><button>📝 Nuevo reporte (+10 pts)</button></a>{% else %}<div class="card">📥 <b>{{pend}}</b> reportes pendientes de atender</div><form method="post" action="/demo"><button class="sec">🧪 Cargar datos de ejemplo</button></form><a href="/panel"><button>🛠️ Ir al panel de reportes</button></a>{% endif %}
<h2>Consejo del día <a href="/consejos" style="font-size:13px;color:var(--ac)">ver todos</a></h2><div class="card"><b>{{consejo[0]}} {{consejo[1]}}</b><p class="muted">{{consejo[2]}}</p></div>{% endblock %}""",
"reportar.html": """{% extends 'base.html' %}{% block c %}<h1>📝 Nuevo reporte</h1><form method="post" class="card">
<select name="mun">{% for m in muns %}<option>{{m}}</option>{% endfor %}</select>
<input name="direccion" placeholder="Dirección o barrio" required>
<select name="cat">{% for c in cats %}<option>{{c}}</option>{% endfor %}</select>
<textarea name="desc" rows="4" placeholder="Describe el problema" required></textarea>
<input type="hidden" name="lat" id="lat"><input type="hidden" name="lon" id="lon">
<button type="button" class="sec" onclick="gps()">📍 Usar mi ubicación</button><div class="muted" id="gpsmsg">Sin ubicación GPS (opcional)</div>
<div class="muted">📷 Foto (opcional)</div><input type="file" accept="image/*" onchange="foto(this,'foto','prev')">
<input type="hidden" name="foto" id="foto"><img id="prev" style="display:none;width:100%;border-radius:10px"><button>Enviar reporte</button></form>
<script>function gps(){navigator.geolocation.getCurrentPosition(function(p){lat.value=p.coords.latitude;lon.value=p.coords.longitude;
gpsmsg.textContent='✔ Ubicación guardada: '+p.coords.latitude.toFixed(5)+', '+p.coords.longitude.toFixed(5)},
function(){gpsmsg.textContent='No se pudo obtener la ubicación (revisa el permiso)'})}</script>{% endblock %}""",
"mis.html": """{% extends 'base.html' %}{% block c %}<h1>📋 Mis reportes</h1>{% for r in rows %}<div class="card">
<span class="tag">{{r[4]}}</span> <span class="tag">{{r[2]}}</span><p><b>{{r[0]}}</b></p><p class="muted">{{r[1]}}</p><div class="muted">{{r[3]}}</div>{% if r[6] %}<img src="{{r[6]}}" style="width:100%;border-radius:10px;margin-top:8px">{% endif %}
{% if r[4]=='Pendiente' %}<form method="post" action="/eliminar/{{r[7]}}" onsubmit="return confirm('¿Eliminar este reporte?')"><button class="sec">🗑️ Eliminar</button></form>{% endif %}{% if r[5] %}<div class="msg"><b>Respuesta:</b> {{r[5]}}</div>{% endif %}</div>{% else %}<p class="muted">Aún no has enviado reportes.</p>{% endfor %}{% endblock %}""",
"logros.html": """{% extends 'base.html' %}{% block c %}{% if session.rol=='user' %}<h1>🏆 Insignias</h1>{% for i in ins %}
<div class="card {{'' if i[4] else 'off'}}"><b>{{i[0]}} {{i[1]}}</b><div class="muted">{{i[2]}}</div></div>{% endfor %}{% endif %}
<h2>Ranking</h2>{% for r in rank %}<div class="card">{{loop.index}}. <b>{{r[0]}}</b> · 🏅 {{r[1]}} pts · {{r[2]}} reportes</div>{% endfor %}{% endblock %}""",
"perfil.html": """{% extends 'base.html' %}{% block c %}<h1>👤 Mi perfil</h1><form method="post" class="card" style="text-align:center">
<img id="prev" src="{{foto or ''}}" style="{{'' if foto else 'display:none;'}}width:120px;height:120px;border-radius:50%;object-fit:cover;border:3px solid var(--ac)">
{% if not foto %}<div style="font-size:64px">🌿</div>{% endif %}<h2>{{session.user}}</h2><div class="muted">{{nivel}} · 🏅 {{pts}} pts · {{nrep}} reportes</div>
<input type="file" accept="image/*" onchange="foto(this,'foto','prev')"><input type="hidden" name="foto" id="foto">
<textarea name="bio" rows="3" maxlength="300" placeholder="Cuéntanos algo sobre ti">{{bio}}</textarea><button>Guardar perfil</button></form>{% endblock %}""",
"stats.html": """{% extends 'base.html' %}{% block c %}<h1>📊 Estadísticas</h1>
<div style="display:flex;gap:8px;flex-wrap:wrap"><div class="card" style="flex:1;min-width:70px;text-align:center"><div style="font-size:26px;color:var(--ac)">{{tot}}</div><div class="muted">Total</div></div>
{% for e in estados %}<div class="card" style="flex:1;min-width:70px;text-align:center"><div style="font-size:26px">{{est.get(e,0)}}</div><div class="muted">{{e}}</div></div>{% endfor %}</div>
<div class="card">✅ Tasa de resolución: <b>{{tasa}}%</b></div><h2>Por categoría</h2><div class="card">{% for c,n in cat %}<div class="muted">{{c}} · {{n}}</div><div style="background:var(--c2);border-radius:6px;margin:3px 0 10px"><div style="width:{{(n*100/mc)|int}}%;background:var(--ac);height:10px;border-radius:6px"></div></div>{% else %}<span class="muted">Sin datos</span>{% endfor %}</div>
<h2>Últimos días</h2><div class="card">{% for c,n in dia %}<div class="muted">{{c}} · {{n}}</div><div style="background:var(--c2);border-radius:6px;margin:3px 0 10px"><div style="width:{{(n*100/md)|int}}%;background:var(--ac);height:10px;border-radius:6px"></div></div>{% else %}<span class="muted">Sin datos</span>{% endfor %}</div>{% endblock %}""",
"actividad.html": """{% extends 'base.html' %}{% block c %}<h1>🕒 Actividad</h1>{% for r in rows %}<div class="card">{{r[0]}} {% if r[3] %}<b>{{r[3]}}</b>: {% endif %}{{r[1]}}
<div class="muted">{{r[2]}}</div></div>{% else %}<p class="muted">Todavía no hay actividad.</p>{% endfor %}{% endblock %}""",
"mapa.html": """{% extends 'base.html' %}{% block c %}<h1>🗺️ Mapa de reportes</h1>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css">
<div id="map" style="height:62vh;border-radius:14px;border:1px solid var(--bd)"></div>
<div class="muted" style="margin-top:8px">🔴 Pendiente · 🟠 En proceso · 🟢 Resuelto · {{pts|length}} reportes con ubicación</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>
<script>var P={{pts|tojson}},C={Pendiente:'#EF4444','En proceso':'#F59E0B',Resuelto:'#22C55E'};
var m=L.map('map').setView([10.52,-74.19],12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(m);
var g=[];P.forEach(function(p){var d=document.createElement('div');d.innerText=p.cat+' · '+p.estado+' — '+p.lugar;
L.circleMarker([p.lat,p.lon],{radius:9,color:'#fff',weight:2,fillColor:C[p.estado]||'#888',fillOpacity:.95}).addTo(m).bindPopup(d);g.push([p.lat,p.lon])});
if(g.length)m.fitBounds(g,{padding:[30,30],maxZoom:16});</script>{% endblock %}""",
"comunidad.html": """{% extends 'base.html' %}{% block c %}<h1>👥 Comunidad</h1>
<form method="get" class="card"><input name="q" value="{{qs}}" placeholder="🔍 Buscar por lugar, categoría o texto"><button>Buscar</button></form>
{% for r in rows %}<div class="card"><span class="tag">{{r[4]}}</span> <span class="tag">{{r[3]}}</span><p><b>{{r[1]}}</b></p><p class="muted">{{r[2]}}</p>
{% if r[6] %}<img src="{{r[6]}}" style="width:100%;border-radius:10px">{% endif %}<div class="muted">por {{r[7]}} · {{r[5]}}</div>
<div style="display:flex;gap:8px;align-items:center"><b>👍 {{r[8]}}</b>
{% if session.rol=='user' and r[10]!=uid and not r[9] %}<form method="post" action="/apoyar/{{r[0]}}" style="flex:1"><button class="sec">👍 Yo también lo vi</button></form>
{% elif r[9] %}<span class="muted">✔ Ya lo apoyaste</span>{% endif %}</div></div>{% else %}<p class="muted">No se encontraron reportes.</p>{% endfor %}{% endblock %}""",
"consejos.html": """{% extends 'base.html' %}{% block c %}<h1>🌱 Consejos ambientales</h1>{% for c in cs %}<div class="card"><b>{{c[0]}} {{c[1]}}</b><p class="muted">{{c[2]}}</p></div>{% endfor %}{% endblock %}""",
"usuarios.html": """{% extends 'base.html' %}{% block c %}<h1>🧑‍🤝‍🧑 Usuarios</h1>{% for r in rows %}<div class="card"><b>{{r[0]}}</b> · {{r[3]}}<div class="muted">🏅 {{r[1]}} pts · {{r[2]}} reportes</div></div>{% else %}<p class="muted">Aún no hay usuarios.</p>{% endfor %}{% endblock %}""",
"panel.html": """{% extends 'base.html' %}{% block c %}<h1>🛠️ Panel de reportes</h1><form method="get" class="card"><select name="estado" onchange="this.form.submit()"><option value="">Todos los estados</option>{% for e in estados %}<option {{'selected' if e==est}}>{{e}}</option>{% endfor %}</select>
<select name="cat" onchange="this.form.submit()"><option value="">Todas las categorías</option>{% for c in cats %}<option {{'selected' if c==cat}}>{{c}}</option>{% endfor %}</select>
<a href="/exportar.csv"><button type="button" class="sec">⬇️ Exportar a CSV</button></a></form>{% for r in rows %}<div class="card">
<span class="tag">{{r[3]}}</span> <b>#{{r[0]}}</b> · {{r[6]}}<p><b>{{r[1]}}</b></p><p class="muted">{{r[2]}}</p>{% if r[8] %}<img src="{{r[8]}}" style="width:100%;border-radius:10px">{% endif %}
<form method="post" action="/panel/{{r[0]}}"><select name="estado">{% for e in estados %}<option {{'selected' if e==r[5]}}>{{e}}</option>{% endfor %}</select>
<textarea name="resp" rows="2" placeholder="Respuesta al usuario">{{r[7] or ''}}</textarea><button>Guardar</button></form></div>
{% else %}<p class="muted">No hay reportes.</p>{% endfor %}{% endblock %}""",
}
app.jinja_loader = DictLoader(T)
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
