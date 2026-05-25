from flask import Flask, render_template_string, jsonify, request
import random
import json
import os
import uuid
from threading import Lock

app = Flask(__name__)

DB_FILE = 'bingo_data.json'
data_lock = Lock()

def cargar_datos():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        "sesion_id": str(uuid.uuid4()),
        "ronda_actual": 1,
        "precio_carton": 10.0,
        "porc_linea": 30,
        "porc_bingo": 60,
        "porc_casa": 10,
        "jugadores_activos": {},
        "jugadores_historicos": {},
        "saldos": {},
        "saldo_casa": 0.0,
        "chat": [],
        "historial_8_rondas": [None] * 8
    }

def guardar_datos(datos):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)

sesion = cargar_datos()

def generar_carton():
    nums = []
    nums.extend(sorted(random.sample(range(1, 31), 5)))
    nums.extend(sorted(random.sample(range(31, 61), 5)))
    nums.extend(sorted(random.sample(range(61, 91), 5)))
    return {"id": str(random.randint(10000, 99999)), "numeros": nums}

def estado_inicial_ronda():
    bolas = list(range(1, 91))
    random.shuffle(bolas)
    return {
        "bolas_sacadas": [], "bolas_disponibles": bolas, "ultima": None,
        "ganador_linea_id": None, "ganador_linea_nombre": None,
        "ganador_bingo_id": None, "ganador_bingo_nombre": None,
        "linea_pagada": False, "bingo_pagada": False
    }

juego = estado_inicial_ronda()

# ====================== RUTAS API ======================
@app.route('/')
def index():
    es_admin = request.args.get('admin') == '123'
    return render_template_string(HTML_BASE, es_admin=es_admin)

@app.route('/api/estado')
def estado():
    u = request.args.get('u')
    with data_lock:
        saldo = sesion["saldos"].get(u, 100.0)
        return jsonify({
            "juego": juego,
            "jugadores_activos": sesion["jugadores_activos"],
            "chat": sesion["chat"],
            "sesion_id": sesion["sesion_id"],
            "ronda_actual": sesion["ronda_actual"],
            "historial": sesion["historial_8_rondas"],
            "precio_carton": sesion["precio_carton"],
            "porc_linea": sesion["porc_linea"],
            "porc_bingo": sesion["porc_bingo"],
            "porc_casa": sesion["porc_casa"],
            "saldo_casa": sesion["saldo_casa"],
            "mis_cartones": sesion["jugadores_activos"].get(u, []),
            "mi_saldo": saldo
        })

@app.route('/api/mis_cartones')
def mis_cartones():
    u = request.args.get('u')
    if not u: return jsonify({"cartones": []})
    with data_lock:
        if u not in sesion["jugadores_activos"]:
            saldo_actual = sesion["saldos"].get(u, 100.0)
            costo = sesion["precio_carton"] * 2
            if saldo_actual < costo:
                return jsonify({"error": "Saldo insuficiente"})
            cartones = [generar_carton() for _ in range(2)]
            sesion["jugadores_activos"][u] = cartones
            sesion["saldos"][u] = round(saldo_actual - costo, 2)
            if u not in sesion["jugadores_historicos"]:
                sesion["jugadores_historicos"][u] = []
            sesion["jugadores_historicos"][u].extend(cartones)
            guardar_datos(sesion)
        return jsonify({"cartones": sesion["jugadores_activos"][u], "saldo": sesion["saldos"].get(u, 100.0)})

@app.route('/api/config_sesion')
def config_sesion():
    if request.args.get('admin') != '123':
        return jsonify({"error": "No autorizado"}), 403
    with data_lock:
        try:
            sesion["precio_carton"] = float(request.args.get('precio', 1.0))
            guardar_datos(sesion)
            return jsonify({"ok": True})
        except:
            return jsonify({"error": "Datos inválidos"})

@app.route('/api/sacar')
def sacar():
    global juego
    with data_lock:
        if not juego["bolas_disponibles"] or juego["ganador_bingo_id"]:
            return jsonify({"ok": True})
        bola = juego["bolas_disponibles"].pop(0)
        juego["bolas_sacadas"].append(bola)
        juego["ultima"] = bola
        sacadas = set(juego["bolas_sacadas"])
        for nombre, carts in list(sesion["jugadores_activos"].items()):
            for c in carts:
                n = c["numeros"]
                if not juego["ganador_linea_id"]:
                    for fila in [n[0:5], n[5:10], n[10:15]]:
                        if all(x in sacadas for x in fila):
                            juego["ganador_linea_id"] = c["id"]
                            juego["ganador_linea_nombre"] = nombre
                            sesion["chat"].append({"u": "📢 SISTEMA", "m": f"¡LÍNEA! de {nombre} (Cartón {c['id']})"})
                            break
                if not juego["ganador_bingo_id"] and all(x in sacadas for x in n):
                    juego["ganador_bingo_id"] = c["id"]
                    juego["ganador_bingo_nombre"] = nombre
                    sesion["chat"].append({"u": "🏆 SISTEMA", "m": f"¡BINGO! de {nombre} (Cartón {c['id']})"})
        if (juego["ganador_linea_id"] and not juego.get("linea_pagada")) or (juego["ganador_bingo_id"] and not juego.get("bingo_pagada")):
            total_recaudado = len(sesion["jugadores_activos"]) * 2 * sesion["precio_carton"]
            premio_linea = round(total_recaudado * sesion["porc_linea"] / 100, 2)
            premio_bingo = round(total_recaudado * sesion["porc_bingo"] / 100, 2)
            premio_casa = round(total_recaudado * sesion["porc_casa"] / 100, 2)
            sesion["saldo_casa"] = round(sesion["saldo_casa"] + premio_casa, 2)
            if juego["ganador_linea_nombre"] and not juego.get("linea_pagada"):
                sesion["saldos"][juego["ganador_linea_nombre"]] = round(sesion["saldos"].get(juego["ganador_linea_nombre"], 100.0) + premio_linea, 2)
                juego["linea_pagada"] = True
            if juego["ganador_bingo_nombre"] and not juego.get("bingo_pagada"):
                sesion["saldos"][juego["ganador_bingo_nombre"]] = round(sesion["saldos"].get(juego["ganador_bingo_nombre"], 100.0) + premio_bingo, 2)
                juego["bingo_pagada"] = True
            idx = sesion["ronda_actual"] - 1
            if idx < 8:
                sesion["historial_8_rondas"][idx] = {
                    "l_n": juego["ganador_linea_nombre"] or "Nadie",
                    "l_id": juego["ganador_linea_id"] or "-",
                    "l_p": premio_linea,
                    "b_n": juego["ganador_bingo_nombre"] or "Nadie",
                    "b_id": juego["ganador_bingo_id"] or "-",
                    "b_p": premio_bingo
                }
        guardar_datos(sesion)
    return jsonify({"ok": True})

@app.route('/api/reset')
def reset():
    global juego
    with data_lock:
        for nombre in list(sesion["jugadores_activos"].keys()):
            saldo_actual = sesion["saldos"].get(nombre, 100.0)
            costo = sesion["precio_carton"] * 2
            if saldo_actual >= costo:
                sesion["jugadores_activos"][nombre] = [generar_carton() for _ in range(2)]
                sesion["saldos"][nombre] = round(saldo_actual - costo, 2)
        sesion["ronda_actual"] += 1
        sesion["sesion_id"] = str(uuid.uuid4())
        juego = estado_inicial_ronda()
        guardar_datos(sesion)
    return jsonify({"ok": True})

@app.route('/api/nueva_sesion')
def nueva_sesion():
    global sesion, juego
    with data_lock:
        precio_actual = sesion.get("precio_carton", 10.0)
        sesion = {
            "sesion_id": str(uuid.uuid4()),
            "ronda_actual": 1,
            "precio_carton": precio_actual,
            "porc_linea": 30,
            "porc_bingo": 60,
            "porc_casa": 10,
            "jugadores_activos": {},
            "jugadores_historicos": {},
            "saldos": {},
            "saldo_casa": 0,
            "chat": [],
            "historial_8_rondas": [None] * 8
        }
        juego = estado_inicial_ronda()
        guardar_datos(sesion)
    return jsonify({"ok": True})

@app.route('/api/retirarse')
def retirarse():
    u = request.args.get('u')
    if not u: return jsonify({"ok": False})
    with data_lock:
        if u in sesion["jugadores_activos"]:
            del sesion["jugadores_activos"][u]
            sesion["chat"].append({"u": "🚪 SISTEMA", "m": f"{u} ha abandonado la partida."})
            guardar_datos(sesion)
            return jsonify({"ok": True})
    return jsonify({"ok": False})

@app.route('/api/chat')
def chat():
    u = request.args.get('u')
    m = request.args.get('m')
    if u and m:
        with data_lock:
            sesion["chat"].append({"u": u, "m": m})
            if len(sesion["chat"]) > 50:
                sesion["chat"].pop(0)
            guardar_datos(sesion)
    return jsonify({"ok": True})

# ====================== HTML & JAVASCRIPT ======================
HTML_BASE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Bingo Pro - BWD</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #0a1321; color: white; margin: 0; text-align: center; }
        .header { background: #1a2338; padding: 10px; position: sticky; top: 0; z-index: 100; border-bottom: 4px solid #00d4ff; }
        .banner { font-size: 3.8em; font-weight: 900; margin: 8px 0; min-height: 80px; color: #ff3366; }
        .wallet { background: linear-gradient(135deg, #1e3a8a, #3b82f6); padding: 15px; border-radius: 12px; margin: 12px auto; max-width: 360px; font-size: 1.5em; font-weight: bold; }
        .casa-balance { background: linear-gradient(135deg, #7f1d1d, #dc2626); padding: 14px; border-radius: 12px; margin: 12px auto; max-width: 360px; font-size: 1.5em; font-weight: bold; }
        .tablero { display: grid; grid-template-columns: repeat(10, 1fr); gap: 4px; background: #000; padding: 10px; border-radius: 12px; max-width: 380px; margin: 15px auto; }
        .bola-tab { width: 28px; height: 28px; background: #1f2937; color: #94a3b8; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.8em; }
        .bola-tab.active { background: #22d3ee; color: black; }
        .bola-tab.last { background: #facc15 !important; color: black; box-shadow: 0 0 12px #facc15; }
        .carton-wrapper { background: #1e2937; padding: 12px; border-radius: 12px; margin: 12px auto; border: 2px solid #22d3ee; max-width: 360px; position: relative; }
        .grid-carton { display: grid; grid-template-columns: repeat(5, 1fr); gap: 5px; }
        .cell { background: #334155; height: 45px; display: flex; align-items: center; justify-content: center; border-radius: 6px; font-weight: bold; font-size: 1.25em; }
        .cell.match { background: #facc15 !important; color: black !important; }
        .label-premio { position: absolute; top: 38%; left: 50%; transform: translate(-50%, -50%) rotate(-12deg); display: none; font-size: 3.2em; font-weight: 900; z-index: 20; text-shadow: 4px 4px 10px #000; }
        .blink { animation: parpadeo 0.8s infinite; }
        @keyframes parpadeo { 0%,100% {opacity:1} 50% {opacity:0.35} }
        .btn { padding: 12px; margin: 5px 3px; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; transition: all 0.1s; }
        .btn:active { transform: scale(0.95); }
        .admin-panel { background: #1e2937; margin: 10px auto; padding: 15px; border-radius: 12px; max-width: 760px; border: 3px solid #f43f5e; }
        table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.9em; }
        th, td { border: 1px solid #444; padding: 8px; text-align: center; }
        th { background: #0f172a; }
        #chat-box { height: 180px; overflow-y:auto; padding:10px; background:#0f172a; border-radius:8px; text-align:left; }
        #chat-box div { color: white; margin: 4px 0; }
    </style>
</head>
<body>
    <div id="login-overlay" style="position:fixed;inset:0;background:#0a1321;z-index:3000;display:flex;flex-direction:column;align-items:center;justify-content:center;">
        <div style="background:#1e2937;padding:35px;border-radius:18px;border:3px solid #22d3ee;">
            <h1>BINGO PRO</h1>
            <input type="text" id="user-name" placeholder="Tu nombre" style="padding:12px;width:260px;font-size:1.1em;border-radius:8px;"><br><br>
            <button class="btn" style="background:#22c55e;width:260px;" onclick="confirmarNombre()">ENTRAR AL JUEGO</button>
        </div>
    </div>

    <div class="header">
        <div id="info-ronda" style="color:#67e8f9;">RONDA 1/8</div>
        <div id="pantalla-bola" class="banner">BINGO</div>
    </div>

    {% if es_admin %}
    <div class="admin-panel">
        <h2>Panel Administrador</h2>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
            <div><small>Precio</small><input id="precio" type="number" step="0.1" style="width:100%;padding:6px;"></div>
            <div><small>% Línea</small><input id="linea" type="number" value="30" style="width:100%;padding:6px;"></div>
            <div><small>% Bingo</small><input id="bingo" type="number" value="60" style="width:100%;padding:6px;"></div>
            <div><small>% Casa</small><input id="casa" type="number" value="10" style="width:100%;padding:6px;"></div>
        </div>
        <button class="btn" style="background:#06b6d4;width:100%;margin:8px 0;" onclick="guardarConfig()">Guardar Configuración</button>
        
        <div class="casa-balance">Casa: <span id="saldo-casa">0.00</span> BWD</div>

        <div style="display:flex; gap:8px; margin:10px 0;">
            <button id="btn-cantar" class="btn" style="background:#ef4444;flex:1;padding:16px;" onclick="sacarBola()">🎤 CANTAR NÚMERO</button>
            <button id="btn-auto" class="btn" style="background:#eab308;flex:1;padding:16px;" onclick="toggleAuto()">▶ AUTO</button>
        </div>

        <button class="btn" style="background:#22c55e;width:49%;" onclick="reiniciarRonda()">SIGUIENTE RONDA</button>
        <button class="btn" style="background:#ef4444;width:49%;" onclick="nuevaSesion()">NUEVA SESIÓN</button>

        <h3>Historial 8 Rondas (BWD)</h3>
        <table id="historial-tabla">
            <thead><tr><th>R</th><th>Línea</th><th>Bingo</th></tr></thead>
            <tbody></tbody>
        </table>

        <h3>Jugadores en Vivo</h3>
        <div id="jugadores-vivos" style="background:#0f172a;padding:10px;border-radius:8px;text-align:left;"></div>
    </div>
    {% else %}
    <div class="wallet" id="wallet">BWD: <span id="saldo">100.00</span></div>
    {% endif %}

    <div id="mis-cartones"></div>

    <div id="chat-container" style="max-width:420px;margin:15px auto;background:#1e2937;padding:8px;border-radius:10px;">
        <div id="chat-box"></div>
        <div style="display:flex;margin-top:6px;">
            <input id="chat-input" placeholder="Mensaje..." style="flex:1;padding:12px;background:#334155;color:white;border:none;border-radius:8px 0 0 8px;">
            <button class="btn" style="background:#22d3ee;border-radius:0 8px 8px 0;" onclick="enviarMsg()">ENVIAR</button>
        </div>
    </div>

    <div class="tablero" id="tablero-gen"></div>

    <div style="max-width:400px;margin:15px auto;">
        <button class="btn" style="background:#ef4444;width:100%;" onclick="retirarseJugador()">🚪 ME RETIRO</button>
    </div>

    <script>
        let esAdmin = {{ 'true' if es_admin else 'false' }};
        let miNombre = esAdmin ? "ADMIN" : (localStorage.getItem('bingo-nombre') || "");
        let miSesionId = null;
        let lastBola = null;
        let vocalizadoLinea = false;
        let vocalizadoBingo = false;
        let autoInterval = null;

        function hablar(texto) {
            if ('speechSynthesis' in window) {
                const u = new SpeechSynthesisUtterance(texto);
                u.lang = 'es-ES';
                u.rate = 0.95;
                speechSynthesis.speak(u);
            }
        }

        function confirmarNombre() {
            let n = document.getElementById('user-name').value.trim();
            if (n) {
                localStorage.setItem('bingo-nombre', n);
                miNombre = n;
                document.getElementById('login-overlay').style.display = 'none';
                actualizar();
            } else {
                alert("Por favor escribe tu nombre");
            }
        }

        function toggleAuto() {
            const btn = document.getElementById('btn-auto');
            if (autoInterval) {
                clearInterval(autoInterval);
                autoInterval = null;
                btn.textContent = "▶ AUTO";
                btn.style.background = "#eab308";
            } else {
                autoInterval = setInterval(sacarBola, 4000);
                btn.textContent = "⏹ DETENER";
                btn.style.background = "#ef4444";
            }
        }

        async function enviarMsg() {
            let input = document.getElementById('chat-input');
            if (input.value.trim() && miNombre) {
                await fetch(`/api/chat?u=${encodeURIComponent(miNombre)}&m=${encodeURIComponent(input.value)}`);
                input.value = "";
            }
        }

        async function guardarConfig() {
            const precioVal = document.getElementById('precio').value;
            const p = new URLSearchParams({admin:'123', precio: precioVal});
            await fetch('/api/config_sesion?' + p);
            alert("✅ Configuración guardada: " + precioVal + " BWD");
        }

        async function sacarBola() {
            const btn = document.getElementById('btn-cantar');
            btn.style.transform = 'scale(0.92)';
            await fetch('/api/sacar');
            setTimeout(() => btn.style.transform = 'scale(1)', 150);
        }

        async function reiniciarRonda() { 
            if(confirm("¿Pasar a la siguiente ronda?")) await fetch('/api/reset'); 
        }

        async function nuevaSesion() { 
            if(confirm("¿Iniciar NUEVA SESIÓN completa?")) {
                await fetch('/api/nueva_sesion');
                location.reload();
            }
        }

        async function retirarseJugador() {
            if(confirm("¿Seguro que quieres retirarte? Perderás tus cartones actuales.")) {
                const res = await fetch(`/api/retirarse?u=${encodeURIComponent(miNombre)}`);
                const data = await res.json();
                if(data.ok) {
                    localStorage.removeItem('bingo-nombre');
                    location.reload();
                }
            }
        }

        async function actualizar() {
            if(!esAdmin && !miNombre) {
                document.getElementById('login-overlay').style.display = 'flex';
                return;
            }
            document.getElementById('login-overlay').style.display = 'none';

            const res = await fetch(`/api/estado?u=${encodeURIComponent(miNombre)}`);
            const data = await res.json();

            if(miSesionId && data.sesion_id !== miSesionId) location.reload();
            miSesionId = data.sesion_id;

            if(!esAdmin) document.getElementById('saldo').textContent = parseFloat(data.mi_saldo || 100).toFixed(2);
            
            if(esAdmin) {
                document.getElementById('saldo-casa').textContent = parseFloat(data.saldo_casa || 0).toFixed(2);
                const inputPrecio = document.getElementById('precio');
                if (document.activeElement !== inputPrecio) {
                    inputPrecio.value = data.precio_carton;
                }
            }

            const banner = document.getElementById('pantalla-bola');
            banner.innerHTML = data.juego.ultima || 'BINGO';

            if (data.juego.ultima && data.juego.ultima !== lastBola) {
                hablar(data.juego.ultima.toString());
                lastBola = data.juego.ultima;
            }

            if (data.juego.ganador_linea_id && !vocalizadoLinea) {
                hablar(`Línea para ${data.juego.ganador_linea_nombre}`);
                vocalizadoLinea = true;
            }
            if (data.juego.ganador_bingo_id && !vocalizadoBingo) {
                hablar(`Bingo para ${data.juego.ganador_bingo_nombre}`);
                vocalizadoBingo = true;
            }

            if (!esAdmin && document.getElementById('mis-cartones').children.length === 0 && miNombre) {
                const resC = await fetch(`/api/mis_cartones?u=${encodeURIComponent(miNombre)}`);
                const dc = await resC.json();
                if(dc.cartones) {
                    let html = "";
                    dc.cartones.forEach(c => {
                        html += `<div class="carton-wrapper">
                            <div class="label-premio blink" id="linea-${c.id}" style="color:#22c55e">¡LÍNEA!</div>
                            <div class="label-premio blink" id="bingo-${c.id}" style="color:#ff00ff">¡BINGO!</div>
                            <div style="color:#67e8f9;">Serial: ${c.id}</div>
                            <div class="grid-carton">${c.numeros.map(n => `<div class="cell" data-num="${n}">${n}</div>`).join('')}</div>
                        </div>`;
                    });
                    document.getElementById('mis-cartones').innerHTML = html;
                }
            }

            let t = "";
            for(let i=1; i<=90; i++) {
                let clase = data.juego.bolas_sacadas.includes(i) ? "active" : "";
                if(i === data.juego.ultima) clase += " last";
                t += `<div class="bola-tab ${clase}">${i}</div>`;
            }
            document.getElementById('tablero-gen').innerHTML = t;

            document.querySelectorAll('.cell').forEach(cell => {
                if(data.juego.bolas_sacadas.includes(parseInt(cell.dataset.num))) cell.classList.add('match');
            });

            if(data.juego.ganador_linea_id) document.getElementById(`linea-${data.juego.ganador_linea_id}`)?.setAttribute('style','display:block;color:#22c55e');
            if(data.juego.ganador_bingo_id) document.getElementById(`bingo-${data.juego.ganador_bingo_id}`)?.setAttribute('style','display:block;color:#ff00ff');

            document.getElementById('info-ronda').innerText = `RONDA ${data.ronda_actual}/8`;

            const chatBox = document.getElementById('chat-box');
            chatBox.innerHTML = data.chat.map(m => `<div><b>${m.u}:</b> ${m.m}</div>`).join('');
            chatBox.scrollTop = chatBox.scrollHeight;

            if(esAdmin){
                let tbody = "";
                data.historial.forEach((r, i) => {
                    if(r){
                        tbody += `<tr><td>${i+1}</td>
                        <td style="color:#22c55e">${r.l_n} (${r.l_id}) - ${parseFloat(r.l_p||0).toFixed(2)}</td>
                        <td style="color:#ff00ff">${r.b_n} (${r.b_id}) - ${parseFloat(r.b_p||0).toFixed(2)}</td></tr>`;
                    } else {
                        tbody += `<tr><td>${i+1}</td><td>-</td><td>-</td></tr>`;
                    }
                });
                document.querySelector('#historial-tabla tbody').innerHTML = tbody;

                let vivos = "";
                for (let [nom, carts] of Object.entries(data.jugadores_activos)) {
                    vivos += `<div><b>${nom}</b> → ${carts.map(c => c.id).join(", ")}</div>`;
                }
                document.getElementById('jugadores-vivos').innerHTML = vivos || "Sin jugadores activos";
            }
        }

        setInterval(actualizar, 1400);
        actualizar();
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)