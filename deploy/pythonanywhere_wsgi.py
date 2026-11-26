# Modelo do arquivo WSGI para o PythonAnywhere.
# No painel: aba Web -> link "WSGI configuration file" -> apague o conteudo e cole este,
# trocando SEU_USUARIO e as duas chaves. Depois clique em "Reload".
import os
import sys

PROJETO = "/home/SEU_USUARIO/mostratalento"
if PROJETO not in sys.path:
    sys.path.insert(0, PROJETO)

# Senha do painel de metricas (/admin?key=...) e chave da sessao.
# Use valores seus; nao suba este arquivo preenchido para o GitHub.
os.environ["ADMIN_KEY"] = "troque-pela-senha-do-painel"
os.environ["SECRET_KEY"] = "troque-por-uma-chave-longa-e-aleatoria"

# Banco e fotos ficam em PROJETO/data (persistente no PythonAnywhere).
os.environ.setdefault("DATA_DIR", os.path.join(PROJETO, "data"))

from app import app as application  # noqa: E402
