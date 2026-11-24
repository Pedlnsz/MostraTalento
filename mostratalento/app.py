"""MostraTalento - MVP (Flask + SQLite)

Cadastro guiado -> vitrine publica com botao do WhatsApp -> guia do MEI,
com coleta de metricas embutida (eventos + feedback) e painel em /admin.
"""
import csv
import io
import os
import re
import secrets
import sqlite3
import statistics
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from flask import (Flask, Response, abort, g, jsonify, redirect,
                   render_template, request, send_from_directory, session,
                   url_for)
from PIL import Image, ImageOps

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
UPLOADS = os.path.join(DATA, "uploads")
DB_PATH = os.path.join(DATA, "mostratalento.db")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

ADMIN_KEY = os.environ.get("ADMIN_KEY", "mostratalento")
# Participantes cujo ID comeca com este prefixo (ex.: ?u=teste1) ficam fora das metricas.
EXCLUDE_PREFIX = "teste"
TZ = timezone(timedelta(hours=-3))  # America/Fortaleza

# Metas das metricas de sucesso (ajuste conforme a secao 5 do relatorio)
METAS = {
    "taxa_conclusao": 80.0,   # % de quem inicia e conclui o cadastro
    "tempo_cadastro": 300.0,  # segundos (RFN02: ate 5 minutos)
    "nota_facilidade": 4.0,   # media 1-5
    "intencao_compartilhar": 70.0,  # % que enviaria o link a um cliente
    "guia_util": 70.0,        # % que achou o guia do MEI util
}

EVENTOS_CLIENTE = {
    "link_copiado", "link_compartilhado_whatsapp", "cadastro_passo",
    "guia_mei_pergunta", "guia_mei_gov_clicado", "feedback_aberto",
}

MAX_FOTOS = 6
MAX_SERVICOS = 5

# ----------------------------------------------------------------------------
# Banco de dados
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS trabalhadores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    edit_token TEXT UNIQUE NOT NULL,
    nome TEXT NOT NULL,
    ocupacao TEXT NOT NULL,
    regiao TEXT NOT NULL,
    whatsapp TEXT NOT NULL,
    consentimento INTEGER NOT NULL DEFAULT 0,
    pid TEXT,
    criado_em REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS servicos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trabalhador_id INTEGER NOT NULL REFERENCES trabalhadores(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS fotos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trabalhador_id INTEGER NOT NULL REFERENCES trabalhadores(id) ON DELETE CASCADE,
    arquivo TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid TEXT NOT NULL,
    evento TEXT NOT NULL,
    extra TEXT,
    trabalhador_id INTEGER,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid TEXT NOT NULL,
    trabalhador_id INTEGER,
    facilidade INTEGER NOT NULL,
    enviaria_link TEXT NOT NULL,
    guia_util TEXT NOT NULL,
    dificuldade TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eventos_pid ON eventos(pid, ts);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(SCHEMA)


init_db()


# ----------------------------------------------------------------------------
# Participante anonimo + registro de eventos
# ----------------------------------------------------------------------------
@app.before_request
def identificar_participante():
    if request.endpoint in ("static", "fotos"):
        return
    u = request.args.get("u", "").strip()
    if u:
        # permite rotular participantes do teste: ?u=U01 ... ?u=U10
        session["pid"] = re.sub(r"[^A-Za-z0-9_-]", "", u)[:20] or session.get("pid")
        session.permanent = True
    if not session.get("pid"):
        session["pid"] = "P" + secrets.token_hex(3).upper()
        session.permanent = True


def pid():
    return session.get("pid", "anon")


def log(evento, trabalhador_id=None, extra=None):
    db = get_db()
    db.execute(
        "INSERT INTO eventos (pid, evento, extra, trabalhador_id, ts) VALUES (?,?,?,?,?)",
        (pid(), evento, None if extra is None else str(extra), trabalhador_id, time.time()),
    )
    db.commit()


@app.route("/e", methods=["POST"])
def beacon():
    """Eventos disparados no navegador (copiar link, passos do cadastro etc.)."""
    data = request.get_json(silent=True, force=True) or {}
    evento = data.get("evento")
    if evento not in EVENTOS_CLIENTE:
        return ("", 204)
    trabalhador_id = None
    slug = data.get("slug")
    if slug:
        row = get_db().execute("SELECT id FROM trabalhadores WHERE slug=?", (slug,)).fetchone()
        trabalhador_id = row["id"] if row else None
    log(evento, trabalhador_id, data.get("extra"))
    return ("", 204)


# ----------------------------------------------------------------------------
# Utilitarios
# ----------------------------------------------------------------------------
ALFABETO = "abcdefghjkmnpqrstuvwxyz23456789"


def novo_slug():
    db = get_db()
    while True:
        s = "".join(secrets.choice(ALFABETO) for _ in range(6))
        if not db.execute("SELECT 1 FROM trabalhadores WHERE slug=?", (s,)).fetchone():
            return s


def normaliza_whatsapp(txt):
    d = re.sub(r"\D", "", txt or "")
    if d.startswith("55") and len(d) in (12, 13):
        return d
    if len(d) in (10, 11):
        return "55" + d
    return None


def formata_whatsapp(d):
    n = d[2:] if d.startswith("55") else d
    if len(n) == 11:
        return f"({n[:2]}) {n[2:7]}-{n[7:]}"
    return f"({n[:2]}) {n[2:6]}-{n[6:]}"


app.jinja_env.filters["fone"] = formata_whatsapp


def salva_foto(file_storage):
    try:
        img = Image.open(file_storage.stream)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1000, 1000))
        nome = uuid.uuid4().hex + ".jpg"
        img.save(os.path.join(UPLOADS, nome), "JPEG", quality=80, optimize=True)
        return nome
    except Exception:
        return None


def apaga_arquivo(nome):
    try:
        os.remove(os.path.join(UPLOADS, os.path.basename(nome)))
    except OSError:
        pass


def le_formulario(form):
    """Le e valida os campos comuns de cadastro/edicao. Retorna (dados, erro)."""
    dados = {
        "nome": (form.get("nome") or "").strip()[:80],
        "ocupacao": (form.get("ocupacao") or "").strip()[:60],
        "regiao": (form.get("regiao") or "").strip()[:80],
        "whatsapp_raw": (form.get("whatsapp") or "").strip(),
        "consentimento": 1 if form.get("consentimento") else 0,
    }
    titulos = form.getlist("servico_titulo")
    descs = form.getlist("servico_desc")
    servicos = []
    for t, d in zip(titulos, descs):
        t, d = t.strip()[:60], d.strip()[:200]
        if t:
            servicos.append({"titulo": t, "descricao": d})
    dados["servicos"] = servicos[:MAX_SERVICOS]
    dados["whatsapp"] = normaliza_whatsapp(dados["whatsapp_raw"])

    erro = None
    if not dados["nome"]:
        erro = "Escreva seu nome."
    elif not dados["ocupacao"]:
        erro = "Diga o que você faz (ex.: eletricista, manicure)."
    elif not dados["regiao"]:
        erro = "Diga onde você atende (bairro ou cidade)."
    elif not dados["whatsapp"]:
        erro = "O WhatsApp precisa ter DDD + número (ex.: 85 99999-9999)."
    elif not dados["servicos"]:
        erro = "Cadastre pelo menos um serviço que você faz."
    elif not dados["consentimento"]:
        erro = "Para criar a vitrine, marque que você autoriza mostrar seu telefone e suas fotos."
    return dados, erro


# ----------------------------------------------------------------------------
# Paginas publicas
# ----------------------------------------------------------------------------
@app.route("/")
def home():
    log("home_visitada")
    return render_template("home.html")


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    db = get_db()
    if request.method == "GET":
        log("cadastro_iniciado")
        return render_template("cadastro.html", v={"servicos": [{}]}, erro=None)

    dados, erro = le_formulario(request.form)
    if erro:
        log("cadastro_erro", extra=erro)
        if not dados["servicos"]:
            dados["servicos"] = [{}]
        return render_template("cadastro.html", v=dados, erro=erro), 400

    slug, token = novo_slug(), secrets.token_urlsafe(16)
    cur = db.execute(
        "INSERT INTO trabalhadores (slug, edit_token, nome, ocupacao, regiao, whatsapp,"
        " consentimento, pid, criado_em) VALUES (?,?,?,?,?,?,?,?,?)",
        (slug, token, dados["nome"], dados["ocupacao"], dados["regiao"], dados["whatsapp"],
         dados["consentimento"], pid(), time.time()),
    )
    tid = cur.lastrowid
    for s in dados["servicos"]:
        db.execute("INSERT INTO servicos (trabalhador_id, titulo, descricao) VALUES (?,?,?)",
                   (tid, s["titulo"], s["descricao"]))
    for f in request.files.getlist("fotos")[:MAX_FOTOS]:
        if f and f.filename:
            nome = salva_foto(f)
            if nome:
                db.execute("INSERT INTO fotos (trabalhador_id, arquivo) VALUES (?,?)", (tid, nome))
    db.commit()
    log("cadastro_concluido", tid)
    log("pagina_gerada", tid)
    return redirect(url_for("pronto", slug=slug, t=token))


def trabalhador_por_slug(slug):
    t = get_db().execute("SELECT * FROM trabalhadores WHERE slug=?", (slug,)).fetchone()
    if not t:
        abort(404)
    return t


def trabalhador_por_token(token):
    t = get_db().execute("SELECT * FROM trabalhadores WHERE edit_token=?", (token,)).fetchone()
    if not t:
        abort(404)
    return t


def carrega_vitrine(t):
    db = get_db()
    servicos = db.execute("SELECT * FROM servicos WHERE trabalhador_id=? ORDER BY id", (t["id"],)).fetchall()
    fotos = db.execute("SELECT * FROM fotos WHERE trabalhador_id=? ORDER BY id", (t["id"],)).fetchall()
    return servicos, fotos


@app.route("/pronto/<slug>")
def pronto(slug):
    t = trabalhador_por_slug(slug)
    if request.args.get("t") != t["edit_token"]:
        abort(404)
    link = url_for("vitrine", slug=slug, _external=True)
    texto = f"Oi! Conheça meu trabalho e fale comigo direto pelo WhatsApp: {link}"
    return render_template(
        "pronto.html", t=t, link=link,
        wa_share="https://wa.me/?text=" + quote(texto),
        edit_link=url_for("editar", token=t["edit_token"], _external=True),
    )


@app.route("/v/<slug>")
def vitrine(slug):
    t = trabalhador_por_slug(slug)
    servicos, fotos = carrega_vitrine(t)
    log("vitrine_visualizada", t["id"])
    return render_template("vitrine.html", t=t, servicos=servicos, fotos=fotos)


@app.route("/w/<slug>")
def whatsapp(slug):
    """Registra o clique e abre a conversa no WhatsApp do trabalhador."""
    t = trabalhador_por_slug(slug)
    log("whatsapp_clicado", t["id"])
    msg = f"Olá, {t['nome'].split()[0]}! Vi sua vitrine e gostaria de um orçamento."
    return redirect(f"https://wa.me/{t['whatsapp']}?text={quote(msg)}")


@app.route("/fotos/<path:nome>")
def fotos(nome):
    resp = send_from_directory(UPLOADS, os.path.basename(nome))
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


# ----------------------------------------------------------------------------
# Editar / remover (RF08)
# ----------------------------------------------------------------------------
@app.route("/editar/<token>", methods=["GET", "POST"])
def editar(token):
    t = trabalhador_por_token(token)
    db = get_db()
    servicos, fotos_atuais = carrega_vitrine(t)

    if request.method == "GET":
        v = dict(t)
        v["servicos"] = [dict(s) for s in servicos] or [{}]
        v["whatsapp_raw"] = formata_whatsapp(t["whatsapp"])
        return render_template("editar.html", t=t, v=v, fotos=fotos_atuais, erro=None)

    dados, erro = le_formulario(request.form)
    if erro:
        v = dict(dados)
        v["servicos"] = dados["servicos"] or [{}]
        return render_template("editar.html", t=t, v=v, fotos=fotos_atuais, erro=erro), 400

    db.execute("UPDATE trabalhadores SET nome=?, ocupacao=?, regiao=?, whatsapp=?, consentimento=? WHERE id=?",
               (dados["nome"], dados["ocupacao"], dados["regiao"], dados["whatsapp"],
                dados["consentimento"], t["id"]))
    db.execute("DELETE FROM servicos WHERE trabalhador_id=?", (t["id"],))
    for s in dados["servicos"]:
        db.execute("INSERT INTO servicos (trabalhador_id, titulo, descricao) VALUES (?,?,?)",
                   (t["id"], s["titulo"], s["descricao"]))
    remover = {int(x) for x in request.form.getlist("remover_foto") if x.isdigit()}
    for f in fotos_atuais:
        if f["id"] in remover:
            apaga_arquivo(f["arquivo"])
            db.execute("DELETE FROM fotos WHERE id=?", (f["id"],))
    restantes = len(fotos_atuais) - len(remover & {f["id"] for f in fotos_atuais})
    for f in request.files.getlist("fotos"):
        if restantes >= MAX_FOTOS:
            break
        if f and f.filename:
            nome = salva_foto(f)
            if nome:
                db.execute("INSERT INTO fotos (trabalhador_id, arquivo) VALUES (?,?)", (t["id"], nome))
                restantes += 1
    db.commit()
    log("perfil_editado", t["id"])
    return redirect(url_for("pronto", slug=t["slug"], t=t["edit_token"]))


@app.route("/remover/<token>", methods=["POST"])
def remover(token):
    t = trabalhador_por_token(token)
    db = get_db()
    for f in db.execute("SELECT arquivo FROM fotos WHERE trabalhador_id=?", (t["id"],)).fetchall():
        apaga_arquivo(f["arquivo"])
    log("perfil_removido", t["id"])
    db.execute("DELETE FROM trabalhadores WHERE id=?", (t["id"],))
    db.commit()
    return render_template("removido.html")


# ----------------------------------------------------------------------------
# Guia do MEI (RF07 / RFN04 / RFN05)
# ----------------------------------------------------------------------------
GUIA = {
    "atualizado_em": "novembro de 2026",
    "fonte": "Portal do Empreendedor (gov.br/empresas-e-negocios) e INSS",
    "das": [
        ("Comércio ou indústria", "R$ 81,05 (INSS) + R$ 1,00 (ICMS)", "R$ 82,05"),
        ("Prestação de serviços", "R$ 81,05 (INSS) + R$ 5,00 (ISS)", "R$ 86,05"),
        ("Comércio e serviços juntos", "R$ 81,05 + R$ 1,00 + R$ 5,00", "R$ 87,05"),
    ],
    "beneficios": [
        ("Aposentadoria por idade", "Renda de 1 salário mínimo depois dos 62 anos (mulher) ou 65 anos (homem), com o tempo mínimo de contribuição."),
        ("Auxílio-doença", "Renda de cerca de 1 salário mínimo enquanto você está afastado por doença ou acidente. Em geral precisa de 12 contribuições mensais (acidente e doenças graves não exigem)."),
        ("Salário-maternidade", "Renda de 1 salário mínimo por 120 dias em caso de parto, adoção ou guarda. Precisa estar com o DAS em dia."),
        ("Pensão por morte", "Renda para a sua família se você falecer, conforme as regras do INSS."),
        ("Auxílio-reclusão", "Apoio à família em caso de prisão do titular, conforme as regras do INSS."),
    ],
    "passos": [
        "Separe CPF, RG, comprovante de endereço (seu e do local de trabalho) e, se tiver, o número do recibo do último Imposto de Renda.",
        "Crie uma conta gov.br nível Prata ou Ouro. É o login que você vai usar em tudo.",
        "Entre só no site oficial: gov.br/empresas-e-negocios, clique em “Quero ser MEI” e depois em “Formalize-se”. Desconfie de qualquer endereço parecido.",
        "Preencha seus dados e escolha a atividade que mais combina com o que você faz.",
        "Revise e confirme. O CNPJ e o Certificado de MEI saem na hora, sem fila e sem custo.",
        "Depois de aberto: pague o DAS todo mês, entregue a declaração anual uma vez por ano e emita nota fiscal quando o cliente pedir.",
    ],
}


@app.route("/guia-mei")
def guia_mei():
    log("guia_mei_aberto")
    return render_template("guia.html", g=GUIA)


# ----------------------------------------------------------------------------
# Feedback do teste de usabilidade
# ----------------------------------------------------------------------------
@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    slug = request.values.get("s", "")
    row = get_db().execute("SELECT id FROM trabalhadores WHERE slug=?", (slug,)).fetchone()
    tid = row["id"] if row else None
    if request.method == "GET":
        log("feedback_aberto", tid)
        return render_template("feedback.html", slug=slug, erro=None)

    try:
        nota = int(request.form.get("facilidade", ""))
    except ValueError:
        nota = 0
    enviaria = request.form.get("enviaria_link")
    guia = request.form.get("guia_util")
    if nota not in range(1, 6) or enviaria not in ("sim", "nao") or guia not in ("sim", "nao", "nao_vi"):
        return render_template("feedback.html", slug=slug, erro="Responda as 3 primeiras perguntas, por favor."), 400
    db = get_db()
    db.execute(
        "INSERT INTO feedback (pid, trabalhador_id, facilidade, enviaria_link, guia_util, dificuldade, ts)"
        " VALUES (?,?,?,?,?,?,?)",
        (pid(), tid, nota, enviaria, guia, (request.form.get("dificuldade") or "").strip()[:500], time.time()),
    )
    db.commit()
    log("feedback_enviado", tid)
    return render_template("obrigado.html")


# ----------------------------------------------------------------------------
# Painel de metricas (/admin?key=...)
# ----------------------------------------------------------------------------
def exige_admin():
    key = request.args.get("key")
    if key:
        session["admin"] = key == ADMIN_KEY
    if not session.get("admin"):
        abort(403)


def calcula_metricas():
    db = get_db()
    ex = EXCLUDE_PREFIX + "%"
    eventos = db.execute("SELECT pid, evento, extra, ts FROM eventos WHERE pid NOT LIKE ? ORDER BY ts", (ex,)).fetchall()

    por_pid = {}
    for e in eventos:
        por_pid.setdefault(e["pid"], []).append(e)

    inicio, fim, passos = {}, {}, {2: set(), 3: set(), 4: set()}
    for p, evs in por_pid.items():
        for e in evs:
            if e["evento"] == "cadastro_iniciado" and p not in inicio:
                inicio[p] = e["ts"]
            elif e["evento"] == "cadastro_concluido" and p in inicio and p not in fim:
                fim[p] = e["ts"]
            elif e["evento"] == "cadastro_passo" and (e["extra"] or "").isdigit():
                n = int(e["extra"])
                if n in passos:
                    passos[n].add(p)

    def distintos(nome):
        return len({e["pid"] for e in eventos if e["evento"] == nome})

    iniciados, concluidos = len(inicio), len(fim)
    tempos = [fim[p] - inicio[p] for p in fim]
    perguntas = {}
    for e in eventos:
        if e["evento"] == "guia_mei_pergunta" and e["extra"]:
            perguntas[e["extra"]] = perguntas.get(e["extra"], 0) + 1

    fb = db.execute("SELECT * FROM feedback WHERE pid NOT LIKE ? ORDER BY ts", (ex,)).fetchall()
    n_fb = len(fb)

    def pct(parte, total):
        return round(100.0 * parte / total, 1) if total else 0.0

    notas = {i: sum(1 for f in fb if f["facilidade"] == i) for i in range(1, 6)}
    nomes_perguntas = {
        "o_que_e": "O que é o MEI?",
        "quanto_custa": "Quanto custa por mês?",
        "beneficios": "Quais benefícios do INSS eu ganho?",
        "nota_fiscal": "Posso emitir nota fiscal?",
        "passo_a_passo": "Como abrir o MEI sem cair em golpe?",
    }
    perguntas = {nomes_perguntas.get(k, k): v for k, v in perguntas.items()}
    m = {
        "participantes": len(por_pid),
        "iniciados": iniciados,
        "concluidos": concluidos,
        "taxa_conclusao": pct(concluidos, iniciados),
        "funil": [
            ("Abriram o cadastro", iniciados),
            ("Chegaram ao passo 2", len(passos[2])),
            ("Chegaram ao passo 3", len(passos[3])),
            ("Chegaram ao passo 4", len(passos[4])),
            ("Concluíram o cadastro", concluidos),
        ],
        "tempo_medio": round(statistics.mean(tempos), 1) if tempos else None,
        "tempo_mediano": round(statistics.median(tempos), 1) if tempos else None,
        "tempo_ate_5min": pct(sum(1 for t in tempos if t <= METAS["tempo_cadastro"]), len(tempos)),
        "n_tempos": len(tempos),
        "uso": [
            ("Vitrine gerada", distintos("pagina_gerada")),
            ("Copiaram o link", distintos("link_copiado")),
            ("Compartilharam no WhatsApp", distintos("link_compartilhado_whatsapp")),
            ("Abriram o Guia do MEI", distintos("guia_mei_aberto")),
            ("Abriram alguma pergunta do guia", distintos("guia_mei_pergunta")),
        ],
        "vitrine_views": sum(1 for e in eventos if e["evento"] == "vitrine_visualizada"),
        "whatsapp_cliques": sum(1 for e in eventos if e["evento"] == "whatsapp_clicado"),
        "perguntas": sorted(perguntas.items(), key=lambda x: -x[1]),
        "n_feedback": n_fb,
        "nota_media": round(statistics.mean(f["facilidade"] for f in fb), 2) if fb else None,
        "notas": notas,
        "intencao": pct(sum(1 for f in fb if f["enviaria_link"] == "sim"), n_fb),
        "guia_util": pct(sum(1 for f in fb if f["guia_util"] == "sim"),
                         sum(1 for f in fb if f["guia_util"] != "nao_vi")),
        "comentarios": [(f["pid"], f["dificuldade"]) for f in fb if f["dificuldade"]],
    }
    m["cartoes"] = [
        ("Taxa de conclusão do cadastro", f"{m['taxa_conclusao']}%", m["taxa_conclusao"] >= METAS["taxa_conclusao"] if iniciados else None, f"meta ≥ {METAS['taxa_conclusao']:.0f}%"),
        ("Tempo mediano de cadastro", f"{int(m['tempo_mediano'] // 60)}min {int(m['tempo_mediano'] % 60)}s" if tempos else "—", (m["tempo_mediano"] <= METAS["tempo_cadastro"]) if tempos else None, "meta ≤ 5 min"),
        ("Nota de facilidade (1–5)", f"{m['nota_media']}" if fb else "—", (m["nota_media"] >= METAS["nota_facilidade"]) if fb else None, f"meta ≥ {METAS['nota_facilidade']:.1f}"),
        ("Enviariam o link a um cliente", f"{m['intencao']}%" if fb else "—", (m["intencao"] >= METAS["intencao_compartilhar"]) if fb else None, f"meta ≥ {METAS['intencao_compartilhar']:.0f}%"),
        ("Acharam o guia do MEI útil", f"{m['guia_util']}%" if fb else "—", (m["guia_util"] >= METAS["guia_util"]) if fb else None, f"meta ≥ {METAS['guia_util']:.0f}%"),
    ]
    return m


@app.route("/admin")
def admin():
    exige_admin()
    return render_template("admin.html", m=calcula_metricas(), prefixo=EXCLUDE_PREFIX)


def csv_response(nome, cabecalho, linhas):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cabecalho)
    w.writerows(linhas)
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nome}"})


def iso(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d %H:%M:%S")


@app.route("/admin/eventos.csv")
def export_eventos():
    exige_admin()
    rows = get_db().execute("SELECT pid, evento, extra, trabalhador_id, ts FROM eventos ORDER BY ts").fetchall()
    return csv_response("eventos.csv", ["participante", "evento", "extra", "trabalhador_id", "data_hora"],
                        [(r["pid"], r["evento"], r["extra"], r["trabalhador_id"], iso(r["ts"])) for r in rows])


@app.route("/admin/feedback.csv")
def export_feedback():
    exige_admin()
    rows = get_db().execute("SELECT * FROM feedback ORDER BY ts").fetchall()
    return csv_response("feedback.csv",
                        ["participante", "facilidade_1a5", "enviaria_link", "guia_util", "dificuldade", "data_hora"],
                        [(r["pid"], r["facilidade"], r["enviaria_link"], r["guia_util"], r["dificuldade"], iso(r["ts"])) for r in rows])


@app.errorhandler(404)
def nao_encontrado(_e):
    return render_template("erro.html", titulo="Página não encontrada",
                           msg="Esse link não existe ou foi removido."), 404


@app.errorhandler(403)
def proibido(_e):
    return render_template("erro.html", titulo="Acesso restrito", msg="Esta página é só para a equipe."), 403


@app.errorhandler(413)
def grande_demais(_e):
    return render_template("erro.html", titulo="Arquivo muito grande",
                           msg="As fotos ficaram pesadas demais. Tente enviar menos fotos."), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=bool(os.environ.get("DEBUG")))
