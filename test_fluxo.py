"""Teste do fluxo completo com o test client do Flask (usa banco temporario)."""
import io
import os
import re
import sqlite3
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image  # noqa: E402

import app as mt  # noqa: E402

c = mt.app.test_client()


def foto(cor, tam=(1600, 1200)):
    buf = io.BytesIO()
    Image.new("RGB", tam, cor).save(buf, "JPEG")
    buf.seek(0)
    return buf


def ok(cond, msg):
    print(("OK   " if cond else "FALHA"), msg)
    if not cond:
        sys.exit(1)


# utilitarios
ok(mt.formata_dias("seg,ter,qua,qui,sex") == "Seg a Sex", "dias: Seg a Sex")
ok(mt.formata_dias("seg,qua,sex") == "Seg, Qua e Sex", "dias: Seg, Qua e Sex")
ok(mt.formata_dias("seg,ter,qua,qui,sex,sab,dom") == "Todos os dias", "dias: todos")
ok(mt.formata_dias("seg,ter,sab") == "Seg, Ter e Sáb", "dias: grupos curtos")
ok(mt.formata_dias("") == "", "dias: vazio")

# paginas basicas
for rota in ["/", "/guia-mei"]:
    ok(c.get(rota + "?u=U01").status_code == 200, f"GET {rota}")
r = c.get("/cadastro?u=U01")
ok(r.status_code == 200 and b"data-stepper" in r.data, "GET /cadastro com stepper")
ok(b'id="ocupacao"' in r.data and b"data-sugestoes" in r.data and b"ocupacao_opcao" not in r.data, "profissao em campo de busca")
ok(len(mt.PROFISSOES) >= 80 and len(set(mt.PROFISSOES)) == len(mt.PROFISSOES), f"{len(mt.PROFISSOES)} sugestoes de profissao, sem repeticao")
ok(set(mt.SINONIMOS) <= set(mt.PROFISSOES), "palavras-chave apontam para profissoes da lista")
ok(r.data.count(b'class="passo"') == mt.N_PASSOS == 6, "6 passos")

# validacao (e volta no passo certo)
r = c.post("/cadastro", data={"nome": "Joao", "whatsapp": "85 99999-0000", "cidade": "Fortaleza"})
ok(r.status_code == 400 and b'data-inicio="1"' in r.data and "Escreva o seu bairro".encode() in r.data, "bairro obrigatorio, passo 1")
r = c.post("/cadastro", data={"nome": "Joao", "whatsapp": "85 99999-0000", "cidade": "Fortaleza", "bairro": "Centro"})
ok(r.status_code == 400 and b'data-inicio="2"' in r.data and "Escreva a sua profissão".encode() in r.data, "profissao obrigatoria, passo 2")
h = c.get("/cadastro").data.decode()
ordem = [h.index(x) for x in ['id="nome"', 'id="whatsapp"', 'id="cidade"', 'id="bairro"', 'id="ocupacao"', 'name="experiencia"', 'name="mei"',
                               'name="servico_titulo"', 'name="domicilio"', 'name="dias"', 'name="foto_perfil"', 'name="fotos"', 'id="consentimento"']]
ok(ordem == sorted(ordem), "ordem: dados, profissao/MEI, servicos/atendimento, foto de perfil, fotos do trabalho, previa")
ok("Qual a sua profissão?" in h and "O que você faz?" not in h, "pergunta 'Qual a sua profissão?'")
r = c.post("/cadastro", data={"nome": "Joao"})
ok(r.status_code == 400 and "O WhatsApp precisa ter DDD".encode() in r.data, "validacao de campos obrigatorios")
ok(b'data-inicio="1"' in r.data, "erro de WhatsApp volta ao passo 1")
r = c.post("/cadastro", data={"nome": "Joao", "ocupacao": "Eletricista", "cidade": "Fortaleza", "bairro": "Centro",
                              "whatsapp": "85 99999-0000", "servico_titulo": ["X"], "servico_desc": [""]})
ok(r.status_code == 400 and b'data-inicio="6"' in r.data, "falta de consentimento volta ao passo 6")
r = c.post("/cadastro", data={"nome": "Joao", "ocupacao": "   "})
ok(r.status_code == 400 and b'data-inicio="1"' in r.data, "profissao so com espacos e rejeitada")

# cadastro completo, com os campos novos
dados = {
    "nome": "Joao da Silva", "ocupacao": "Eletricista", "experiencia": "6-10",
    "cidade": "Fortaleza", "bairro": "Aldeota", "whatsapp": "(85) 99999-1234", "domicilio": "sim",
    "dias": ["seg", "ter", "qua", "qui", "sex", "sab"], "horario": "8h às 18h", "mei": "sim",
    "consentimento": "1",
    "servico_titulo": ["Instalacao de chuveiro", "Troca de fiacao"],
    "servico_desc": ["Chuveiro eletrico e a gas", ""],
    "foto_perfil": (foto("green", (800, 1200)), "rosto.jpg"),
    "fotos": [(foto("red"), "a.jpg"), (foto("blue"), "b.jpg")],
}
r = c.post("/cadastro", data=dados, content_type="multipart/form-data")
ok(r.status_code == 302, "cadastro redireciona")
loc = r.headers["Location"]
m = re.match(r"/pronto/(\w+)\?t=([^&]+)", loc)
ok(bool(m), f"redireciona para pagina pronta ({loc})")
slug, token = m.group(1), m.group(2)
ok(len(slug) == 6, "link curto de 6 caracteres")

r = c.get(loc)
ok(r.status_code == 200 and f"/v/{slug}".encode() in r.data, "pagina pronta mostra o link")
ok(f"/og/{slug}.jpg".encode() in r.data, "pagina pronta mostra a previa do WhatsApp")
ok(c.get(f"/pronto/{slug}?t=errado").status_code == 404, "pagina pronta exige token")
ok("novo=1" in loc and b"Pronto! Sua vitrine" in c.get(loc).data, "pagina pronta de vitrine nova")
r = c.get("/minha-vitrine")
ok(r.status_code == 302 and f"/pronto/{slug}?t={token}" in r.headers["Location"], "Minha vitrine leva a vitrine deste celular")
ok(b"<h1>Minha vitrine</h1>" in c.get(r.headers["Location"]).data, "pagina Minha vitrine sem o titulo de recem-criada")
outro = mt.app.test_client()
r = outro.get("/minha-vitrine")
ok(r.status_code == 200 and "Não encontramos uma vitrine".encode() in r.data, "outro celular nao ve a vitrine")
outro.get(f"/editar/{token}")
ok(outro.get("/minha-vitrine").status_code == 302, "abrir o link de edicao num celular novo passa a lembrar")
outro.post(f"/esquecer/{token}")
ok(outro.get("/minha-vitrine").status_code == 200, "esquecer neste celular funciona")
ok(c.get("/minha-vitrine").status_code == 302, "esquecer num celular nao afeta o outro")
ok(b'href="/minha-vitrine"' in c.get("/").data, "menu tem Minha vitrine")
ok("Você está vendo sua vitrine".encode() in c.get(f"/v/{slug}").data, "dono ve faixa Voltar/Enviar na vitrine")
ok("Você está vendo sua vitrine".encode() not in mt.app.test_client().get(f"/v/{slug}").data, "cliente nao ve a faixa do dono")

r = c.get(f"/v/{slug}")
html = r.data.decode()
ok(r.status_code == 200 and "Joao da Silva" in html and "Chamar no WhatsApp" in html, "vitrine publica")
ok("6 a 10 anos de experiência" in html, "selo de experiencia")
ok("MEI formalizado" in html, "selo MEI")
ok("Seg a Sáb · 8h às 18h" in html, "dias e horario formatados")
ok("Atende em domicílio" in html and "Atende em Aldeota, Fortaleza" in html, "atende em domicilio e regiao montada de bairro + cidade")
ok('class="avatar-foto"' in html, "foto de perfil na vitrine")
ok(html.count('loading="lazy"') == 2, "vitrine mostra as 2 fotos de trabalho")
og = re.search(r'property="og:image" content="([^"]+)"', html).group(1)
ok(og.startswith("http://localhost/og/"), f"og:image absoluto ({og})")

# previa do WhatsApp (imagem gerada)
r = c.get(og.replace("http://localhost", ""))
ok(r.status_code == 200 and r.mimetype == "image/jpeg", "imagem de previa gerada")
im = Image.open(io.BytesIO(r.data))
ok(im.size == (1200, 630) and len(r.data) < 300_000, f"previa 1200x630 e leve ({len(r.data)//1024} KB)")
with open(os.path.join(mt.DATA, "og_teste.jpg"), "wb") as fh:
    fh.write(r.data)

# https atras de tunel (ProxyFix)
r = c.get(f"/v/{slug}", headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "abc.trycloudflare.com"})
ok(f'content="https://abc.trycloudflare.com/og/{slug}.jpg'.encode() in r.data, "og:image usa https do tunel")

# foto de perfil quadrada
db = sqlite3.connect(mt.DB_PATH)
fp = db.execute("SELECT foto_perfil FROM trabalhadores WHERE slug=?", (slug,)).fetchone()[0]
ok(Image.open(os.path.join(mt.UPLOADS, fp)).size == (600, 600), "foto de perfil recortada 600x600")

fotos_src = re.findall(r'src="(/fotos/[^"]+)" alt="Trabalho', html)
r2 = c.get(fotos_src[0])
ok(r2.status_code == 200 and r2.mimetype == "image/jpeg", "foto servida")
ok(max(Image.open(io.BytesIO(r2.data)).size) <= 1000, "foto redimensionada")

r = c.get(f"/w/{slug}")
ok(r.status_code == 302 and r.headers["Location"].startswith("https://wa.me/5585999991234"), "botao leva ao WhatsApp certo")

# "Outra" profissao + MEI "quero"
r = c.post("/cadastro", data={"nome": "Ana", "ocupacao": "Instrutora de  autoescola",
                              "cidade": "Fortaleza", "bairro": "Centro", "whatsapp": "85988887777", "mei": "quero", "consentimento": "1",
                              "servico_titulo": ["Cuidar de criancas"], "servico_desc": [""]},
           content_type="multipart/form-data")
ok(r.status_code == 302, "cadastro com profissao fora da lista")
r = c.get(r.headers["Location"])
ok("Você quer abrir seu MEI".encode() in r.data, "pagina pronta destaca o guia para quem quer MEI")
slug2 = re.search(rb"/v/(\w+)", r.data).group(1).decode()
h2 = c.get(f"/v/{slug2}").data.decode()
ok("Instrutora de autoescola" in h2 and "MEI formalizado" not in h2 and 'class="avatar"' in h2, "vitrine sem foto, sem selo MEI")
ok(c.get(f"/og/{slug2}.jpg").status_code == 200, "previa sem foto de perfil gerada")

# eventos do navegador
for ev, extra in [("cadastro_passo", "2"), ("cadastro_passo", "3"), ("cadastro_passo", "4"), ("cadastro_passo", "5"), ("cadastro_passo", "6"),
                  ("link_copiado", None), ("link_compartilhado_whatsapp", None),
                  ("guia_mei_pergunta", "quanto_custa"), ("evento_invalido", None)]:
    r = c.post("/e", json={"evento": ev, "extra": extra, "slug": slug})
    ok(r.status_code == 204, f"beacon {ev}")

# feedback
r = c.post("/feedback", data={"s": slug, "facilidade": "5", "enviaria_link": "sim", "guia_util": "sim",
                              "dificuldade": "Achei facil"})
ok(r.status_code == 200 and b"Muito obrigado" in r.data, "feedback salvo")
r = c.post("/feedback", data={"s": slug, "facilidade": "9"})
ok(r.status_code == 400, "feedback invalido rejeitado")

# admin
c2 = mt.app.test_client()
ok(c2.get("/admin").status_code == 403, "admin bloqueado sem chave")
ok(c2.get("/admin?key=errada").status_code == 403, "admin bloqueado com chave errada")
r = c2.get("/admin?key=" + mt.ADMIN_KEY)
ok(r.status_code == 200, "admin com chave correta")
txt = r.data.decode()
ok("Achei facil" in txt, "comentario aparece no painel")
ok("Querem abrir MEI" in txt and "Com foto de perfil" in txt, "painel mostra perfil e MEI")
ok("Passo 6: Prévia" in txt and "Passo 4: Foto de perfil" in txt, "funil com 6 passos")
for p in ["/admin/eventos.csv", "/admin/feedback.csv", "/admin/vitrines.csv"]:
    r = c2.get(p)
    ok(r.status_code == 200 and r.mimetype == "text/csv", f"export {p}")
vit_csv = c2.get("/admin/vitrines.csv").data.decode("utf-8-sig")
ok("Joao" not in vit_csv and "99999" not in vit_csv, "vitrines.csv sem nome nem telefone")
ok("Seg a Sáb" in vit_csv and "quero" in vit_csv, "vitrines.csv com perfil")
ev_csv = c2.get("/admin/eventos.csv").data.decode("utf-8-sig")
for ev in ["cadastro_iniciado", "cadastro_concluido", "pagina_gerada", "vitrine_visualizada",
           "whatsapp_clicado", "link_copiado", "guia_mei_pergunta", "feedback_enviado"]:
    ok(ev in ev_csv, f"evento registrado: {ev}")
ok("U01" in ev_csv, "participante rotulado U01")

with mt.app.test_request_context():
    m = mt.calcula_metricas()
ok(dict(m["mei"])["Já têm MEI"] == 1 and dict(m["mei"])["Querem abrir MEI"] == 1, "contagem de MEI")

# participante de teste fica fora das metricas
mt.app.test_client().get("/cadastro?u=teste1")
with mt.app.test_request_context():
    m2 = mt.calcula_metricas()
ok(m2["iniciados"] == m["iniciados"], "participante 'teste*' excluido das metricas")

# edicao
r = c.get(f"/editar/{token}")
ed = r.data.decode()
ok(r.status_code == 200 and "Joao da Silva" in ed and "remover_foto" in ed, "tela de edicao preenchida")
ok('value="Eletricista"' in ed, "edicao preenche a profissao")
ok('value="6-10" data-rotulo="6 a 10 anos" checked' in ed, "edicao marca a experiencia")
ok('value="sab" checked' in ed and 'value="dom" checked' not in ed, "edicao marca os dias")
ok("(85) 99999-1234" in ed, "edicao mostra o WhatsApp formatado")
og_antes = c.get(f"/v/{slug}").data.decode()
id_foto = re.search(r'name="remover_foto" value="(\d+)"', ed).group(1)
r = c.post(f"/editar/{token}", data={
    "nome": "Joao S.", "ocupacao": "Eletricista", "cidade": "Caucaia", "bairro": "Centro", "whatsapp": "85 98888-0000",
    "consentimento": "1", "servico_titulo": ["Quadro de luz"], "servico_desc": [""],
    "remover_foto": [id_foto], "remover_foto_perfil": "1", "mei": "nao",
}, content_type="multipart/form-data")
ok(r.status_code == 302, "edicao salva")
h = c.get(f"/v/{slug}").data.decode()
ok("Joao S." in h and "Quadro de luz" in h and h.count('loading="lazy"') == 1, "vitrine reflete a edicao (1 foto removida)")
ok('class="avatar-foto"' not in h and "MEI formalizado" not in h and "experiência" not in h, "edicao removeu foto de perfil, MEI e experiencia")
og_novo = re.search(r'property="og:image" content="([^"]+)"', h).group(1)
ok(og_novo != re.search(r'property="og:image" content="([^"]+)"', og_antes).group(1), "previa do WhatsApp muda apos edicao")

# remocao
n_arq = len(os.listdir(mt.UPLOADS))
r = c.post(f"/remover/{token}")
ok(r.status_code == 200 and b"apagada" in r.data, "remocao confirma")
ok(c.get(f"/v/{slug}").status_code == 404, "vitrine removida some")
r = c.get("/minha-vitrine")
ok(r.status_code == 302 and slug not in r.headers["Location"] and slug2 in r.headers["Location"], "vitrine apagada sai de Minha vitrine (fica a outra deste celular)")
ok(len(os.listdir(mt.UPLOADS)) < n_arq, "arquivos de foto apagados do disco")
ok(not [f for f in os.listdir(mt.OG_DIR) if f.startswith(slug)], "previa do WhatsApp apagada")

# migracao de banco antigo (sem as colunas novas)
d_antigo = tempfile.mkdtemp()
with sqlite3.connect(os.path.join(d_antigo, "x.db")) as dbx:
    dbx.execute("CREATE TABLE trabalhadores (id INTEGER PRIMARY KEY, slug TEXT, edit_token TEXT, nome TEXT, ocupacao TEXT,"
                " regiao TEXT, whatsapp TEXT, consentimento INTEGER, pid TEXT, criado_em REAL)")
old = mt.DB_PATH
mt.DB_PATH = os.path.join(d_antigo, "x.db")
mt.init_db()
cols = {r[1] for r in sqlite3.connect(mt.DB_PATH).execute("PRAGMA table_info(trabalhadores)")}
mt.DB_PATH = old
ok(set(mt.NOVAS_COLUNAS) <= cols, "migracao adiciona colunas novas em banco antigo")

# nenhum emoji no codigo da interface
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
base = os.path.dirname(os.path.abspath(__file__))
com_emoji = []
for pasta in ("templates", "static"):
    for raiz, _, arqs in os.walk(os.path.join(base, pasta)):
        for a in arqs:
            if a.endswith((".html", ".js", ".css")):
                if EMOJI.search(open(os.path.join(raiz, a), encoding="utf-8").read()):
                    com_emoji.append(a)
ok(not com_emoji and not EMOJI.search(open(os.path.join(base, "app.py"), encoding="utf-8").read()), f"sem emojis na interface {com_emoji}")

print("\nTodos os testes passaram.")
print("OG:", os.path.join(mt.DATA, "og_teste.jpg"))
