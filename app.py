"""MostraTalento - MVP (Flask + SQLite)

Cadastro guiado -> vitrine publica com botao do WhatsApp -> guia do MEI,
com coleta de metricas embutida (eventos + feedback) e painel em /admin.
"""
import csv
import glob
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

from flask import (Flask, Response, abort, g, redirect, render_template,
                   request, send_file, send_from_directory, session, url_for)
from PIL import Image, ImageDraw, ImageFont, ImageOps
from werkzeug.middleware.proxy_fix import ProxyFix

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
UPLOADS = os.path.join(DATA, "uploads")
OG_DIR = os.path.join(DATA, "og")
DB_PATH = os.path.join(DATA, "mostratalento.db")
FONTES = os.path.join(BASE, "static", "fonts")
os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(OG_DIR, exist_ok=True)

app = Flask(__name__)
# Respeita https/host repassados por tunel (cloudflared/ngrok) ou hospedagem,
# para que os links gerados e a imagem de previa saiam com https.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=365)  # lembra a vitrine no celular por 1 ano

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
N_PASSOS = 6

# ----------------------------------------------------------------------------
# Opcoes do cadastro
# ----------------------------------------------------------------------------
# Sugestoes do campo de profissao. Nao e uma lista fechada: o trabalhador pode
# escrever qualquer profissao. Ordem: as mais comuns entre autonomos primeiro.
PROFISSOES = [
    # casa e cuidado
    "Diarista", "Faxineiro(a)", "Passadeira", "Lavadeira", "Cozinheiro(a)", "Babá",
    "Cuidador(a) de idosos", "Acompanhante hospitalar", "Jardineiro(a)", "Piscineiro", "Caseiro(a)",
    # beleza
    "Manicure e pedicure", "Cabeleireiro(a)", "Barbeiro(a)", "Trancista", "Maquiador(a)",
    "Designer de sobrancelha", "Extensão de cílios", "Depilador(a)", "Esteticista", "Massagista",
    "Tatuador(a)",
    # obras e reparos
    "Pedreiro", "Servente de obra", "Mestre de obras", "Pintor(a)", "Eletricista", "Encanador",
    "Gesseiro", "Azulejista", "Telhadista", "Marceneiro", "Carpinteiro", "Serralheiro", "Soldador",
    "Vidraceiro", "Montador de móveis", "Pequenos reparos (marido de aluguel)", "Chaveiro",
    "Desentupidor", "Dedetizador", "Técnico de ar-condicionado", "Técnico de refrigeração",
    "Técnico de eletrodomésticos", "Técnico de máquina de lavar", "Instalador de câmeras",
    # veiculos e transporte
    "Mecânico(a)", "Mecânico(a) de motos", "Eletricista automotivo", "Borracheiro", "Funileiro e pintor de carro",
    "Lavador(a) de carros", "Motorista", "Motorista de aplicativo", "Mototaxista", "Motoboy",
    "Entregador(a)", "Frete e mudança",
    # comida
    "Doces e salgados", "Boleiro(a)", "Salgadeiro(a)", "Marmitas e quentinhas", "Tapioqueiro(a)",
    "Lanches", "Açaí", "Churrasqueiro(a)", "Garçom / Garçonete", "Buffet para festas",
    # costura, artesanato e vendas
    "Costureiro(a)", "Consertos de roupa", "Sapateiro(a)", "Artesão / Artesã", "Crochê e tricô",
    "Revendedor(a) de cosméticos", "Vendedor(a) autônomo(a)", "Vendedor(a) ambulante",
    # tecnologia e criacao
    "Técnico de celular", "Técnico de informática", "Técnico de internet e TV", "Designer gráfico",
    "Social media", "Editor(a) de vídeo", "Fotógrafo(a)", "Criador(a) de sites",
    # educacao, eventos e outros
    "Professor(a) particular", "Reforço escolar", "Personal trainer", "Professor(a) de música",
    "Músico(a)", "DJ", "Animador(a) de festas", "Decorador(a) de festas", "Cerimonialista",
    "Banho e tosa", "Passeador(a) de cães", "Adestrador(a)",
]
# Palavras do dia a dia que tambem encontram a profissao na busca (ex.: "unha" -> Manicure)
SINONIMOS = {
    "Diarista": ["limpeza", "faxina", "doméstica", "empregada"], "Faxineiro(a)": ["limpeza", "faxina"],
    "Passadeira": ["passar roupa"], "Lavadeira": ["lavar roupa"], "Cozinheiro(a)": ["comida", "cozinha"],
    "Babá": ["criança", "cuidar de criança"], "Cuidador(a) de idosos": ["idoso", "cuidadora"],
    "Jardineiro(a)": ["jardim", "grama", "poda"], "Piscineiro": ["piscina"],
    "Manicure e pedicure": ["unha", "unhas", "gel", "esmalte", "pé"],
    "Cabeleireiro(a)": ["cabelo", "salão", "escova", "corte", "progressiva", "mechas"],
    "Barbeiro(a)": ["barba", "corte masculino"], "Trancista": ["trança", "box braids"],
    "Maquiador(a)": ["maquiagem", "make"], "Designer de sobrancelha": ["sobrancelha", "henna"],
    "Extensão de cílios": ["cílios", "lash"], "Depilador(a)": ["depilação", "cera"],
    "Esteticista": ["estética", "limpeza de pele"], "Massagista": ["massagem"], "Tatuador(a)": ["tatuagem", "tattoo"],
    "Pedreiro": ["obra", "construção", "reforma", "alvenaria"], "Mestre de obras": ["obra", "reforma"],
    "Pintor(a)": ["pintura", "parede"], "Eletricista": ["luz", "elétrica", "tomada", "fiação", "chuveiro"],
    "Encanador": ["cano", "hidráulica", "vazamento", "torneira"], "Gesseiro": ["gesso", "drywall", "forro"],
    "Azulejista": ["azulejo", "piso", "cerâmica", "porcelanato"], "Telhadista": ["telhado", "telha", "goteira"],
    "Marceneiro": ["móveis", "madeira", "armário"], "Serralheiro": ["portão", "grade", "ferro"],
    "Soldador": ["solda"], "Vidraceiro": ["vidro", "box", "janela"], "Montador de móveis": ["montagem"],
    "Pequenos reparos (marido de aluguel)": ["conserto", "reparo", "faz tudo"], "Chaveiro": ["chave", "fechadura"],
    "Desentupidor": ["entupido", "esgoto"], "Dedetizador": ["dedetização", "barata", "cupim"],
    "Técnico de ar-condicionado": ["ar condicionado", "split", "climatização"],
    "Técnico de refrigeração": ["geladeira", "freezer"], "Técnico de eletrodomésticos": ["conserto", "fogão"],
    "Técnico de máquina de lavar": ["lavadora"], "Instalador de câmeras": ["câmera", "segurança", "cftv"],
    "Mecânico(a)": ["carro", "oficina", "conserto de carro"], "Mecânico(a) de motos": ["moto", "oficina"],
    "Borracheiro": ["pneu"], "Funileiro e pintor de carro": ["lanternagem", "funilaria"],
    "Lavador(a) de carros": ["lava jato", "lavagem"], "Motorista de aplicativo": ["uber", "99"],
    "Mototaxista": ["moto"], "Motoboy": ["moto", "entrega"], "Entregador(a)": ["entrega", "delivery"],
    "Frete e mudança": ["carreto", "mudança", "frete"],
    "Doces e salgados": ["bolo", "confeitaria", "docinho", "salgadinho", "festa"],
    "Boleiro(a)": ["bolo", "confeitaria"], "Marmitas e quentinhas": ["marmita", "quentinha", "comida", "almoço"],
    "Lanches": ["sanduíche", "hambúrguer", "lanchonete"], "Garçom / Garçonete": ["evento", "festa"],
    "Costureiro(a)": ["costura", "roupa"], "Consertos de roupa": ["ajuste", "barra", "costura"],
    "Sapateiro(a)": ["sapato", "conserto"], "Artesão / Artesã": ["artesanato"],
    "Revendedor(a) de cosméticos": ["avon", "natura", "boticário", "perfume"],
    "Vendedor(a) ambulante": ["camelô", "rua", "praia"], "Técnico de celular": ["celular", "tela", "conserto"],
    "Técnico de informática": ["computador", "notebook", "pc", "formatação"],
    "Técnico de internet e TV": ["antena", "wi-fi", "internet"], "Designer gráfico": ["design", "logo", "arte"],
    "Social media": ["instagram", "redes sociais"], "Editor(a) de vídeo": ["vídeo", "edição"],
    "Fotógrafo(a)": ["foto", "fotografia", "ensaio"], "Criador(a) de sites": ["site", "programador"],
    "Professor(a) particular": ["aula", "reforço"], "Reforço escolar": ["aula", "escola", "dever de casa"],
    "Personal trainer": ["academia", "treino"], "Professor(a) de música": ["aula de música", "violão"],
    "Animador(a) de festas": ["festa infantil", "recreação"], "Decorador(a) de festas": ["decoração", "festa"],
    "Banho e tosa": ["pet", "cachorro", "gato"], "Passeador(a) de cães": ["pet", "cachorro"],
    "Adestrador(a)": ["pet", "cachorro"],
}
EXPERIENCIA = [("<1", "Menos de 1 ano"), ("1-2", "1 a 2 anos"), ("3-5", "3 a 5 anos"),
               ("6-10", "6 a 10 anos"), ("10+", "Mais de 10 anos")]
EXP_LABEL = dict(EXPERIENCIA)
DIAS = [("seg", "Seg"), ("ter", "Ter"), ("qua", "Qua"), ("qui", "Qui"),
        ("sex", "Sex"), ("sab", "Sáb"), ("dom", "Dom")]
DIA_IDX = {c: i for i, (c, _) in enumerate(DIAS)}
MEI_OPCOES = [("sim", "Sim, já tenho"), ("quero", "Ainda não, mas quero abrir"), ("nao", "Não tenho")]

app.jinja_env.globals.update(
    PROFISSOES=PROFISSOES, SINONIMOS=SINONIMOS, EXPERIENCIA=EXPERIENCIA, DIAS=DIAS, MEI_OPCOES=MEI_OPCOES, N_PASSOS=N_PASSOS,
    MAX_FOTOS=MAX_FOTOS,
)

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

# Colunas acrescentadas depois da primeira versao (migracao automatica de bancos antigos)
NOVAS_COLUNAS = {
    "foto_perfil": "TEXT",
    "experiencia": "TEXT NOT NULL DEFAULT ''",
    "dias": "TEXT NOT NULL DEFAULT ''",
    "horario": "TEXT NOT NULL DEFAULT ''",
    "domicilio": "INTEGER",
    "mei": "TEXT NOT NULL DEFAULT ''",
    "atualizado_em": "REAL",
    "cidade": "TEXT NOT NULL DEFAULT ''",
    "bairro": "TEXT NOT NULL DEFAULT ''",
}


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
        existentes = {r[1] for r in db.execute("PRAGMA table_info(trabalhadores)")}
        for col, tipo in NOVAS_COLUNAS.items():
            if col not in existentes:
                db.execute(f"ALTER TABLE trabalhadores ADD COLUMN {col} {tipo}")


init_db()


# ----------------------------------------------------------------------------
# Participante anonimo + registro de eventos
# ----------------------------------------------------------------------------
@app.before_request
def identificar_participante():
    if request.endpoint in ("static", "fotos", "og_imagem"):
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


# ----------------------------------------------------------------------------
# "Minha vitrine": o celular lembra o link de edicao (sem login nem senha)
# ----------------------------------------------------------------------------
def lembrar(token):
    minhas = [x for x in session.get("minhas", []) if x != token]
    session["minhas"] = ([token] + minhas)[:5]
    session.permanent = True


def esquecer(token):
    session["minhas"] = [x for x in session.get("minhas", []) if x != token]


@app.context_processor
def menu():
    return {"tem_vitrine": bool(session.get("minhas"))}


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


def formata_dias(codigos):
    """'seg,ter,qua,qui,sex' -> 'Seg a Sex'; 'seg,qua,sex' -> 'Seg, Qua e Sex'."""
    idx = sorted({DIA_IDX[c] for c in (codigos or "").split(",") if c in DIA_IDX})
    if not idx:
        return ""
    if len(idx) == 7:
        return "Todos os dias"
    grupos, atual = [], [idx[0]]
    for i in idx[1:]:
        if i == atual[-1] + 1:
            atual.append(i)
        else:
            grupos.append(atual)
            atual = [i]
    grupos.append(atual)
    partes = []
    for gr in grupos:
        if len(gr) >= 3:
            partes.append(f"{DIAS[gr[0]][1]} a {DIAS[gr[-1]][1]}")
        else:
            partes.extend(DIAS[i][1] for i in gr)
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]


def experiencia_texto(cod):
    return f"{EXP_LABEL[cod]} de experiência" if cod in EXP_LABEL else ""


app.jinja_env.filters.update(fone=formata_whatsapp, dias=formata_dias, experiencia=experiencia_texto)


def salva_foto(file_storage, quadrada=False):
    try:
        img = Image.open(file_storage.stream)
        img = ImageOps.exif_transpose(img).convert("RGB")
        if quadrada:
            img = ImageOps.fit(img, (600, 600), Image.LANCZOS)
        else:
            img.thumbnail((1000, 1000))
        nome = uuid.uuid4().hex + ".jpg"
        img.save(os.path.join(UPLOADS, nome), "JPEG", quality=80, optimize=True)
        return nome
    except Exception:
        return None


def apaga_arquivo(nome):
    if not nome:
        return
    try:
        os.remove(os.path.join(UPLOADS, os.path.basename(nome)))
    except OSError:
        pass


def apaga_og(slug):
    for f in glob.glob(os.path.join(OG_DIR, f"{slug}-*.jpg")):
        try:
            os.remove(f)
        except OSError:
            pass


def le_formulario(form):
    """Le e valida os campos de cadastro/edicao. Retorna (dados, erro, passo_do_erro)."""
    dom = form.get("domicilio")
    dados = {
        "nome": (form.get("nome") or "").strip()[:80],
        "ocupacao": re.sub(r"\s+", " ", form.get("ocupacao") or "").strip()[:60],
        "experiencia": form.get("experiencia") if form.get("experiencia") in EXP_LABEL else "",
        "cidade": re.sub(r"\s+", " ", form.get("cidade") or "").strip()[:40],
        "bairro": re.sub(r"\s+", " ", form.get("bairro") or "").strip()[:40],
        "whatsapp_raw": (form.get("whatsapp") or "").strip(),
        "domicilio": 1 if dom == "sim" else 0 if dom == "nao" else None,
        "dias": ",".join(c for c, _ in DIAS if c in form.getlist("dias")),
        "horario": (form.get("horario") or "").strip()[:40],
        "mei": form.get("mei") if form.get("mei") in dict(MEI_OPCOES) else "",
        "consentimento": 1 if form.get("consentimento") else 0,
    }
    servicos = []
    for t, d in zip(form.getlist("servico_titulo"), form.getlist("servico_desc")):
        t, d = t.strip()[:60], d.strip()[:200]
        if t:
            servicos.append({"titulo": t, "descricao": d})
    dados["servicos"] = servicos[:MAX_SERVICOS]
    dados["whatsapp"] = normaliza_whatsapp(dados["whatsapp_raw"])
    dados["regiao"] = ", ".join(x for x in (dados["bairro"], dados["cidade"]) if x)

    erro, passo = None, None
    if not dados["nome"]:
        erro, passo = "Escreva seu nome.", 1
    elif not dados["whatsapp"]:
        erro, passo = "O WhatsApp precisa ter DDD + número (ex.: 85 99999-9999).", 1
    elif not dados["cidade"]:
        erro, passo = "Escreva a sua cidade.", 1
    elif not dados["bairro"]:
        erro, passo = "Escreva o seu bairro.", 1
    elif not dados["ocupacao"]:
        erro, passo = "Escreva a sua profissão (ex.: eletricista, manicure, diarista).", 2
    elif not dados["servicos"]:
        erro, passo = "Cadastre pelo menos um serviço que você faz.", 3
    elif not dados["consentimento"]:
        erro, passo = "Para criar a vitrine, marque que você autoriza mostrar seu telefone e suas fotos.", N_PASSOS
    return dados, erro, passo


def valores_formulario(dados):
    v = dict(dados)
    v["servicos"] = dados.get("servicos") or [{}]
    v["dias_lista"] = (dados.get("dias") or "").split(",")
    return v


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
        return render_template("cadastro.html", v=valores_formulario({}), erro=None, passo=1)

    dados, erro, passo = le_formulario(request.form)
    if erro:
        log("cadastro_erro", extra=erro)
        return render_template("cadastro.html", v=valores_formulario(dados), erro=erro, passo=passo), 400

    slug, token, agora = novo_slug(), secrets.token_urlsafe(16), time.time()
    perfil = request.files.get("foto_perfil")
    foto_perfil = salva_foto(perfil, quadrada=True) if perfil and perfil.filename else None
    cur = db.execute(
        "INSERT INTO trabalhadores (slug, edit_token, nome, ocupacao, regiao, whatsapp, consentimento, pid,"
        " criado_em, atualizado_em, foto_perfil, experiencia, dias, horario, domicilio, mei, cidade, bairro)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (slug, token, dados["nome"], dados["ocupacao"], dados["regiao"], dados["whatsapp"],
         dados["consentimento"], pid(), agora, agora, foto_perfil, dados["experiencia"],
         dados["dias"], dados["horario"], dados["domicilio"], dados["mei"], dados["cidade"], dados["bairro"]),
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
    lembrar(token)
    return redirect(url_for("pronto", slug=slug, t=token, novo=1))


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


def versao(t):
    return int((t["atualizado_em"] or t["criado_em"]) * 1000)


@app.route("/pronto/<slug>")
def pronto(slug):
    t = trabalhador_por_slug(slug)
    if request.args.get("t") != t["edit_token"]:
        abort(404)
    lembrar(t["edit_token"])  # quem abre o link num celular novo passa a ter "Minha vitrine" nele
    link = url_for("vitrine", slug=slug, _external=True)
    texto = f"Oi! Conheça meu trabalho e fale comigo direto pelo WhatsApp: {link}"
    return render_template(
        "pronto.html", t=t, link=link,
        wa_share="https://wa.me/?text=" + quote(texto),
        edit_link=url_for("editar", token=t["edit_token"], _external=True),
        og=url_for("og_imagem", slug=slug, v=versao(t)),
        novo=bool(request.args.get("novo")),
    )


@app.route("/minha-vitrine")
def minha_vitrine():
    db = get_db()
    achadas = []
    for tok in session.get("minhas", []):
        t = db.execute("SELECT * FROM trabalhadores WHERE edit_token=?", (tok,)).fetchone()
        if t:
            achadas.append(t)
    session["minhas"] = [t["edit_token"] for t in achadas]  # limpa vitrines ja apagadas
    log("minha_vitrine_aberta", achadas[0]["id"] if achadas else None, extra=len(achadas))
    if len(achadas) == 1:
        t = achadas[0]
        return redirect(url_for("pronto", slug=t["slug"], t=t["edit_token"]))
    return render_template("minhas.html", vitrines=achadas)


@app.route("/esquecer/<token>", methods=["POST"])
def esquecer_celular(token):
    esquecer(token)
    return redirect(url_for("minha_vitrine"))


@app.route("/v/<slug>")
def vitrine(slug):
    t = trabalhador_por_slug(slug)
    servicos, fotos = carrega_vitrine(t)
    dono = t["edit_token"] in session.get("minhas", [])
    log("vitrine_visualizada", t["id"], extra="dono" if dono else None)
    link = url_for("vitrine", slug=slug, _external=True)
    wa_share = "https://wa.me/?text=" + quote(f"Oi! Conheça meu trabalho e fale comigo direto pelo WhatsApp: {link}")
    return render_template("vitrine.html", t=t, servicos=servicos, fotos=fotos, dono=dono, wa_share=wa_share,
                           voltar=url_for("pronto", slug=slug, t=t["edit_token"]) if dono else None,
                           og=url_for("og_imagem", slug=slug, v=versao(t), _external=True),
                           url=url_for("vitrine", slug=slug, _external=True))


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
# Imagem de previa do link (Open Graph) - o que aparece no WhatsApp
# ----------------------------------------------------------------------------
COR = {  # mesma paleta do style.css (azul del rey + azul acinzentado)
    "verde": (31, 60, 153), "ambar": (94, 127, 196), "zap": (11, 122, 62), "fundo": (221, 228, 239),
    "texto": (23, 32, 51), "suave": (77, 90, 112), "tag": (238, 242, 248), "verde_esc": (21, 42, 110),
    "ambar_claro": (230, 236, 248), "zap_claro": (223, 242, 230), "branco": (255, 255, 255),
    "logo": (201, 214, 238),
}


def fonte(peso, tamanho):
    arq = {"regular": "Inter-Regular.otf", "semi": "Inter-SemiBold.otf", "extra": "Inter-ExtraBold.otf"}[peso]
    return ImageFont.truetype(os.path.join(FONTES, arq), tamanho)


def cabe(draw, texto, f, largura):
    """Corta o texto com reticencias para caber na largura."""
    if draw.textlength(texto, font=f) <= largura:
        return texto
    while texto and draw.textlength(texto + "…", font=f) > largura:
        texto = texto[:-1]
    return texto.rstrip() + "…"


def quebra(draw, texto, f, largura, max_linhas):
    palavras, linhas, atual = texto.split(), [], ""
    for p in palavras:
        teste = (atual + " " + p).strip()
        if draw.textlength(teste, font=f) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        linhas[-1] = cabe(draw, linhas[-1] + " …", f, largura)
    return [cabe(draw, linha, f, largura) for linha in linhas]


def pilula(draw, x, y, texto, f, fundo, cor, pad_x=22, alt=54, check=False):
    larg = draw.textlength(texto, font=f) + 2 * pad_x + (36 if check else 0)
    draw.rounded_rectangle((x, y, x + larg, y + alt), radius=alt // 2, fill=fundo)
    tx = x + pad_x
    if check:
        cy = y + alt / 2
        draw.line([(tx + 2, cy), (tx + 10, cy + 8), (tx + 24, cy - 8)], fill=cor, width=5, joint="curve")
        tx += 36
    bbox = draw.textbbox((0, 0), texto, font=f)
    draw.text((tx, y + (alt - (bbox[3] - bbox[1])) / 2 - bbox[1]), texto, font=f, fill=cor)
    return larg


def gera_og(t):
    W, H, RODAPE = 1200, 630, 112
    img = Image.new("RGB", (W, H), COR["fundo"])
    d = ImageDraw.Draw(img)

    # avatar
    lado, ax = 300, 72
    ay = (H - RODAPE - lado) // 2
    d.ellipse((ax - 8, ay - 8, ax + lado + 8, ay + lado + 8), fill=COR["ambar"])
    foto = None
    if t["foto_perfil"]:
        try:
            foto = ImageOps.fit(Image.open(os.path.join(UPLOADS, t["foto_perfil"])).convert("RGB"), (lado, lado))
        except Exception:
            foto = None
    if foto:
        mask = Image.new("L", (lado * 4, lado * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, lado * 4, lado * 4), fill=255)
        img.paste(foto, (ax, ay), mask.resize((lado, lado), Image.LANCZOS))
    else:
        d.ellipse((ax, ay, ax + lado, ay + lado), fill=COR["verde"])
        f = fonte("extra", 150)
        letra = t["nome"][:1].upper()
        bb = d.textbbox((0, 0), letra, font=f)
        d.text((ax + (lado - (bb[2] - bb[0])) / 2 - bb[0], ay + (lado - (bb[3] - bb[1])) / 2 - bb[1]),
               letra, font=f, fill=COR["branco"])

    # bloco de texto (centralizado na vertical)
    x0, larg = ax + lado + 64, W - (ax + lado + 64) - 64
    tam = 68
    while tam > 44:
        fn = fonte("extra", tam)
        linhas = quebra(d, t["nome"], fn, larg, 2)
        if len(linhas) == 1 or tam <= 52:
            break
        tam -= 4
    alt_nome = int(tam * 1.15) * len(linhas)
    f_tag, f_txt, f_pil = fonte("semi", 32), fonte("regular", 30), fonte("semi", 26)
    selos = []
    if t["experiencia"] in EXP_LABEL:
        selos.append((experiencia_texto(t["experiencia"]), COR["ambar_claro"], COR["texto"], False))
    if t["mei"] == "sim":
        selos.append(("MEI formalizado", COR["zap_claro"], COR["zap"], True))
    alt_total = alt_nome + 18 + 54 + 18 + 40 + (24 + 50 if selos else 0)
    y = (H - RODAPE - alt_total) // 2

    for linha in linhas:
        d.text((x0, y), linha, font=fn, fill=COR["texto"])
        y += int(tam * 1.15)
    y += 18
    pilula(d, x0, y, cabe(d, t["ocupacao"], f_tag, larg - 60), f_tag, COR["tag"], COR["verde_esc"])
    y += 54 + 18
    d.text((x0, y), cabe(d, "Atende em " + t["regiao"], f_txt, larg), font=f_txt, fill=COR["suave"])
    y += 40
    if selos:
        y += 24
        x = x0
        for texto, fundo, cor, check in selos:
            if x + d.textlength(texto, font=f_pil) + 80 > x0 + larg:
                break
            x += pilula(d, x, y, texto, f_pil, fundo, cor, pad_x=18, alt=50, check=check) + 12

    # rodape com a marca e o convite
    d.rectangle((0, H - RODAPE, W, H), fill=COR["verde"])
    f_marca = fonte("extra", 40)
    yb = H - RODAPE + (RODAPE - 48) // 2
    d.text((ax, yb), "Mostra", font=f_marca, fill=COR["branco"])
    d.text((ax + d.textlength("Mostra", font=f_marca), yb), "Talento", font=f_marca, fill=COR["logo"])
    f_bt = fonte("semi", 30)
    txt_bt = "Chamar no WhatsApp"
    lb = d.textlength(txt_bt, font=f_bt) + 56
    bx, by = W - 64 - lb, H - RODAPE + (RODAPE - 64) // 2
    d.rounded_rectangle((bx, by, bx + lb, by + 64), radius=14, fill=COR["zap"])
    bb = d.textbbox((0, 0), txt_bt, font=f_bt)
    d.text((bx + 28, by + (64 - (bb[3] - bb[1])) / 2 - bb[1]), txt_bt, font=f_bt, fill=COR["branco"])

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=86, optimize=True, progressive=True)
    return buf.getvalue()


@app.route("/og/<slug>.jpg")
def og_imagem(slug):
    t = trabalhador_por_slug(slug)
    caminho = os.path.join(OG_DIR, f"{slug}-{versao(t)}.jpg")
    if not os.path.exists(caminho):
        apaga_og(slug)
        with open(caminho, "wb") as fh:
            fh.write(gera_og(t))
    resp = send_file(caminho, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=3600"
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
        lembrar(t["edit_token"])
        v = dict(t)
        v["servicos"] = [dict(s) for s in servicos]
        v["whatsapp_raw"] = formata_whatsapp(t["whatsapp"])
        if not v.get("cidade") and not v.get("bairro"):
            v["bairro"] = t["regiao"]  # vitrine criada antes de cidade/bairro separados
        return render_template("editar.html", t=t, v=valores_formulario(v), fotos=fotos_atuais, erro=None)

    dados, erro, _passo = le_formulario(request.form)
    if erro:
        return render_template("editar.html", t=t, v=valores_formulario(dados), fotos=fotos_atuais, erro=erro), 400

    foto_perfil = t["foto_perfil"]
    novo_perfil = request.files.get("foto_perfil")
    if novo_perfil and novo_perfil.filename:
        nome = salva_foto(novo_perfil, quadrada=True)
        if nome:
            apaga_arquivo(foto_perfil)
            foto_perfil = nome
    elif request.form.get("remover_foto_perfil"):
        apaga_arquivo(foto_perfil)
        foto_perfil = None

    db.execute(
        "UPDATE trabalhadores SET nome=?, ocupacao=?, regiao=?, whatsapp=?, consentimento=?, experiencia=?,"
        " dias=?, horario=?, domicilio=?, mei=?, foto_perfil=?, atualizado_em=?, cidade=?, bairro=? WHERE id=?",
        (dados["nome"], dados["ocupacao"], dados["regiao"], dados["whatsapp"], dados["consentimento"],
         dados["experiencia"], dados["dias"], dados["horario"], dados["domicilio"], dados["mei"],
         foto_perfil, time.time(), dados["cidade"], dados["bairro"], t["id"]))
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
    apaga_og(t["slug"])
    log("perfil_editado", t["id"])
    return redirect(url_for("pronto", slug=t["slug"], t=t["edit_token"]))


@app.route("/remover/<token>", methods=["POST"])
def remover(token):
    t = trabalhador_por_token(token)
    db = get_db()
    for f in db.execute("SELECT arquivo FROM fotos WHERE trabalhador_id=?", (t["id"],)).fetchall():
        apaga_arquivo(f["arquivo"])
    apaga_arquivo(t["foto_perfil"])
    apaga_og(t["slug"])
    log("perfil_removido", t["id"])
    esquecer(t["edit_token"])
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

    inicio, fim = {}, {}
    passos = {n: set() for n in range(2, N_PASSOS + 1)}
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

    nomes_perguntas = {
        "o_que_e": "O que é o MEI?",
        "quanto_custa": "Quanto custa por mês?",
        "beneficios": "Quais benefícios do INSS eu ganho?",
        "nota_fiscal": "Posso emitir nota fiscal?",
        "passo_a_passo": "Como abrir o MEI sem cair em golpe?",
    }
    perguntas = {nomes_perguntas.get(k, k): v for k, v in perguntas.items()}

    vit = db.execute("SELECT * FROM trabalhadores WHERE pid IS NULL OR pid NOT LIKE ?", (ex,)).fetchall()
    n_vit = len(vit)
    nomes_passos = {2: "Profissão", 3: "Serviços", 4: "Foto de perfil", 5: "Fotos do trabalho",
                    6: "Prévia (Veja como ficou)"}

    notas = {i: sum(1 for f in fb if f["facilidade"] == i) for i in range(1, 6)}
    m = {
        "participantes": len(por_pid),
        "iniciados": iniciados,
        "concluidos": concluidos,
        "taxa_conclusao": pct(concluidos, iniciados),
        "funil": [("Abriram o cadastro", iniciados)]
                 + [(f"Passo {n}: {nomes_passos[n]}", len(passos[n])) for n in range(2, N_PASSOS + 1)]
                 + [("Concluíram o cadastro", concluidos)],
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
        "n_vitrines": n_vit,
        "perfil": [
            ("Com foto de perfil", sum(1 for t in vit if t["foto_perfil"])),
            ("Informaram tempo de experiência", sum(1 for t in vit if t["experiencia"])),
            ("Informaram dias de atendimento", sum(1 for t in vit if t["dias"])),
            ("Atendem a domicílio", sum(1 for t in vit if t["domicilio"] == 1)),
        ],
        "mei": [
            ("Já têm MEI", sum(1 for t in vit if t["mei"] == "sim")),
            ("Querem abrir MEI", sum(1 for t in vit if t["mei"] == "quero")),
            ("Não têm MEI", sum(1 for t in vit if t["mei"] == "nao")),
            ("Não responderam", sum(1 for t in vit if not t["mei"])),
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


@app.route("/admin/vitrines.csv")
def export_vitrines():
    """Perfil das vitrines, sem nome nem telefone (para o relatorio)."""
    exige_admin()
    rows = get_db().execute("SELECT * FROM trabalhadores ORDER BY criado_em").fetchall()
    return csv_response(
        "vitrines.csv",
        ["participante", "ocupacao", "experiencia", "dias", "a_domicilio", "mei", "tem_foto_perfil", "criado_em"],
        [(r["pid"], r["ocupacao"], EXP_LABEL.get(r["experiencia"], ""), formata_dias(r["dias"]),
          {1: "sim", 0: "nao"}.get(r["domicilio"], ""), r["mei"], "sim" if r["foto_perfil"] else "nao",
          iso(r["criado_em"])) for r in rows])


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
