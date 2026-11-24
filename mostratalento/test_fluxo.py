"""Teste do fluxo completo com o test client do Flask (usa banco temporario)."""
import io
import os
import re
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image  # noqa: E402

import app as mt  # noqa: E402

c = mt.app.test_client()


def foto(cor):
    buf = io.BytesIO()
    Image.new("RGB", (1600, 1200), cor).save(buf, "JPEG")
    buf.seek(0)
    return buf


def ok(cond, msg):
    print(("OK   " if cond else "FALHA"), msg)
    if not cond:
        sys.exit(1)


# paginas basicas
for rota in ["/", "/guia-mei"]:
    ok(c.get(rota + "?u=U01").status_code == 200, f"GET {rota}")
r = c.get("/cadastro?u=U01")
ok(r.status_code == 200 and b"data-stepper" in r.data, "GET /cadastro com stepper")

# validacao
r = c.post("/cadastro", data={"nome": "Joao"})
ok(r.status_code == 400 and "Diga o que você faz".encode() in r.data, "validacao de campos obrigatorios")

# cadastro completo
dados = {
    "nome": "Joao da Silva", "ocupacao": "Eletricista", "regiao": "Aldeota, Fortaleza",
    "whatsapp": "(85) 99999-1234", "consentimento": "1",
    "servico_titulo": ["Instalacao de chuveiro", "Troca de fiacao"],
    "servico_desc": ["Chuveiro eletrico e a gas", ""],
    "fotos": [(foto("red"), "a.jpg"), (foto("blue"), "b.jpg")],
}
r = c.post("/cadastro", data=dados, content_type="multipart/form-data")
ok(r.status_code == 302, "cadastro redireciona")
loc = r.headers["Location"]
m = re.match(r"/pronto/(\w+)\?t=(.+)", loc)
ok(bool(m), f"redireciona para pagina pronta ({loc})")
slug, token = m.group(1), m.group(2)
ok(len(slug) == 6, "link curto de 6 caracteres")

r = c.get(loc)
ok(r.status_code == 200 and f"/v/{slug}".encode() in r.data, "pagina pronta mostra o link")
ok(c.get(f"/pronto/{slug}?t=errado").status_code == 404, "pagina pronta exige token")

r = c.get(f"/v/{slug}")
ok(r.status_code == 200 and b"Joao da Silva" in r.data and b"Chamar no WhatsApp" in r.data, "vitrine publica")
ok(r.data.count(b"<img") == 2, "vitrine mostra as 2 fotos")
fotos_src = re.findall(rb'src="(/fotos/[^"]+)"', r.data)
r2 = c.get(fotos_src[0].decode())
ok(r2.status_code == 200 and r2.mimetype == "image/jpeg", "foto servida")
im = Image.open(io.BytesIO(r2.data))
ok(max(im.size) <= 1000, f"foto redimensionada {im.size}")

r = c.get(f"/w/{slug}")
ok(r.status_code == 302 and r.headers["Location"].startswith("https://wa.me/5585999991234"), "botao leva ao WhatsApp certo")

# eventos do navegador
for ev, extra in [("cadastro_passo", "2"), ("cadastro_passo", "3"), ("cadastro_passo", "4"),
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
ok(c.get("/admin", environ_overrides={}).status_code in (200, 403), "admin responde")
c2 = mt.app.test_client()
ok(c2.get("/admin").status_code == 403, "admin bloqueado sem chave")
ok(c2.get("/admin?key=errada").status_code == 403, "admin bloqueado com chave errada")
r = c2.get("/admin?key=" + mt.ADMIN_KEY)
ok(r.status_code == 200, "admin com chave correta")
txt = r.data.decode()
ok("100.0%" in txt, "taxa de conclusao 100% no painel")
ok("Achei facil" in txt, "comentario aparece no painel")
for p in ["/admin/eventos.csv", "/admin/feedback.csv"]:
    r = c2.get(p)
    ok(r.status_code == 200 and r.mimetype == "text/csv", f"export {p}")
ev_csv = c2.get("/admin/eventos.csv").data.decode("utf-8-sig")
for ev in ["cadastro_iniciado", "cadastro_concluido", "pagina_gerada", "vitrine_visualizada",
           "whatsapp_clicado", "link_copiado", "guia_mei_pergunta", "feedback_enviado"]:
    ok(ev in ev_csv, f"evento registrado: {ev}")
ok("U01" in ev_csv, "participante rotulado U01")

# participante de teste fica fora das metricas
ct = mt.app.test_client()
ct.get("/cadastro?u=teste1")
m1 = mt.app.test_client()
m1.get("/admin?key=" + mt.ADMIN_KEY)
with mt.app.app_context(), mt.app.test_request_context():
    m = mt.calcula_metricas()
ok(m["iniciados"] == 1, "participante 'teste*' excluido das metricas")

# edicao
r = c.get(f"/editar/{token}")
ok(r.status_code == 200 and b"Joao da Silva" in r.data and b"remover_foto" in r.data, "tela de edicao preenchida")
r = c.post(f"/editar/{token}", data={
    "nome": "Joao S.", "ocupacao": "Eletricista", "regiao": "Centro", "whatsapp": "85 98888-0000",
    "consentimento": "1", "servico_titulo": ["Quadro de luz"], "servico_desc": [""],
    "remover_foto": [re.search(rb'value="(\d+)"', c.get(f"/editar/{token}").data).group(1).decode()],
}, content_type="multipart/form-data")
ok(r.status_code == 302, "edicao salva")
r = c.get(f"/v/{slug}")
ok(b"Joao S." in r.data and b"Quadro de luz" in r.data and r.data.count(b"<img") == 1, "vitrine reflete a edicao (1 foto removida)")

# remocao
n_arq = len(os.listdir(mt.UPLOADS))
r = c.post(f"/remover/{token}")
ok(r.status_code == 200 and b"apagada" in r.data, "remocao confirma")
ok(c.get(f"/v/{slug}").status_code == 404, "vitrine removida some")
ok(len(os.listdir(mt.UPLOADS)) < n_arq, "arquivos de foto apagados do disco")

print("\nTodos os testes passaram.")
