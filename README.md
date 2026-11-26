# MostraTalento — MVP

Cadastro guiado → vitrine pública com botão do WhatsApp → guia do MEI, com coleta de métricas embutida.
Cobre os requisitos RF01–RF08 e RFN01–RFN09 do relatório (RF09–RF11, o Selo de Confiança, ficam fora do MVP).

## Rodar no seu computador

```bash
pip install -r requirements.txt
python app.py            # abre em http://localhost:5000
```

Variáveis opcionais: `ADMIN_KEY` (senha do painel), `SECRET_KEY`, `PORT`, `DATA_DIR` (onde ficam banco e fotos).

## Colocar na internet para o teste com os 10 usuários

O teste precisa de uma URL que abra no celular de cada participante. Opções rápidas:

- **Túnel temporário (mais rápido):** com o app rodando, `cloudflared tunnel --url http://localhost:5000`
  (ou `ngrok http 5000`). Gera um link https. Só funciona com o seu computador ligado.
- **Hospedagem gratuita/barata:** Render, Railway ou PythonAnywhere. Comando de start: `gunicorn app:app`.
  Configure `ADMIN_KEY` e `SECRET_KEY` e um disco persistente apontado por `DATA_DIR`
  (sem isso, banco e fotos somem a cada deploy).

## Como coletar as métricas no teste

1. Entregue a cada participante um link com o ID dele: `https://SEU-LINK/?u=U01`, `?u=U02` … `?u=U10`.
   O ID é anônimo e identifica o participante nos gráficos e nos CSVs (sem nome).
2. O app registra sozinho: início/passos/conclusão do cadastro, tempo, vitrine gerada,
   link copiado/compartilhado, clique no WhatsApp, abertura do guia e de cada pergunta.
3. No fim do fluxo o participante responde o feedback (nota 1–5, “enviaria o link?”, “guia útil?”, “o que foi difícil?”).
4. Painel: `https://SEU-LINK/admin?key=SUA_SENHA` — cartões contra as metas, funil, uso e notas.
   Dá para tirar print (são as evidências) ou baixar os CSVs.
5. Para testar sem sujar os números, use IDs que começam com `teste` (ex.: `?u=teste1`).

As metas (80% conclusão, ≤ 5 min, nota ≥ 4 etc.) estão no dicionário `METAS` no início do `app.py`.

## Arquivos

- `app.py` — rotas, banco SQLite, métricas e painel
- `templates/`, `static/` — telas mobile-first (sem dependências externas, para carregar rápido em 4G)
- `test_fluxo.py` — teste automático do fluxo completo (`python test_fluxo.py`)

## Pendências antes do teste

- Conferir os valores do DAS e as regras do guia do MEI no Portal do Empreendedor (conteúdo em `GUIA`, no `app.py`).
- O termo de autorização de imagem/voz é em papel/PDF, separado do app.
- Trocar `ADMIN_KEY` e `SECRET_KEY` antes de publicar.
