(function () {
  "use strict";

  // ---------------------------------------------------------------- metricas
  function beacon(evento, extra, slug) {
    var body = JSON.stringify({ evento: evento, extra: extra || null, slug: slug || null });
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon("/e", new Blob([body], { type: "application/json" }));
        return;
      }
    } catch (e) {}
    try { fetch("/e", { method: "POST", body: body, keepalive: true }); } catch (e) {}
  }

  document.addEventListener("click", function (ev) {
    var el = ev.target.closest("[data-evento]");
    if (el) beacon(el.getAttribute("data-evento"), el.getAttribute("data-extra"), el.getAttribute("data-slug"));

    var cp = ev.target.closest("[data-copiar]");
    if (cp) {
      var alvo = document.querySelector(cp.getAttribute("data-copiar"));
      if (!alvo) return;
      var texto = alvo.value || alvo.textContent;
      var feito = function () {
        var antes = cp.textContent;
        cp.textContent = "Copiado!";
        setTimeout(function () { cp.textContent = antes; }, 1800);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(texto).then(feito, function () { alvo.select(); document.execCommand("copy"); feito(); });
      } else {
        alvo.select(); try { document.execCommand("copy"); } catch (e) {}
        feito();
      }
    }
  });

  document.querySelectorAll("details[data-q]").forEach(function (d) {
    d.addEventListener("toggle", function () { if (d.open) beacon("guia_mei_pergunta", d.getAttribute("data-q")); });
  });

  // Icones (vem do <template id="tpl-icones"> gerado no servidor)
  function icone(nome, tam) {
    var tpl = document.getElementById("tpl-icones");
    var base = tpl && tpl.content.querySelector("[data-icone=" + nome + "] svg");
    if (!base) return document.createTextNode("");
    var svg = base.cloneNode(true);
    if (tam) { svg.setAttribute("width", tam); svg.setAttribute("height", tam); }
    return svg;
  }

  var form = document.querySelector("form[data-stepper], form.form-edicao");

  // ------------------------------------------------------- adicionar servico
  var lista = document.getElementById("servicos");
  var add = document.getElementById("add-servico");
  if (lista && add) {
    var maxServ = parseInt(lista.getAttribute("data-max") || "5", 10);
    var atualizaBotao = function () { add.style.display = lista.querySelectorAll(".serv").length >= maxServ ? "none" : ""; };
    add.addEventListener("click", function () {
      var itens = lista.querySelectorAll(".serv");
      if (itens.length >= maxServ) return;
      var novo = itens[0].cloneNode(true);
      novo.querySelectorAll("input,textarea").forEach(function (i) { i.value = ""; i.required = false; });
      lista.appendChild(novo);
      novo.querySelector("input").focus();
      atualizaBotao();
    });
    atualizaBotao();
  }

  // ------------------------------------------------- mascara do WhatsApp
  function formataFone(v) {
    var d = v.replace(/\D/g, "");
    if (d.indexOf("55") === 0 && d.length > 11) d = d.slice(2);
    d = d.slice(0, 11);
    if (d.length === 0) return "";
    if (d.length <= 2) return "(" + d;
    if (d.length <= 6) return "(" + d.slice(0, 2) + ") " + d.slice(2);
    if (d.length <= 10) return "(" + d.slice(0, 2) + ") " + d.slice(2, 6) + "-" + d.slice(6);
    return "(" + d.slice(0, 2) + ") " + d.slice(2, 7) + "-" + d.slice(7);
  }
  document.querySelectorAll("input[data-mascara=fone]").forEach(function (inp) {
    if (inp.value) inp.value = formataFone(inp.value);
    inp.addEventListener("input", function () { inp.value = formataFone(inp.value); });
  });

  // ----------------------------------------- lista de sugestoes (combobox)
  document.querySelectorAll("input[data-sugestoes]").forEach(function (inp) {
    var opcoes = [];
    try { opcoes = JSON.parse(inp.getAttribute("data-sugestoes")); } catch (e) {}
    var ul = document.getElementById(inp.getAttribute("aria-controls"));
    if (!ul || !opcoes.length) return;
    var ativo = -1, itens = [];

    function norm(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
    // "Cabeleireiro(a)" tambem e encontrado por "cabeleireira"; "Artesão / Artesã" por "artesa"
    var sinonimos = {};
    try { sinonimos = JSON.parse(inp.getAttribute("data-sinonimos") || "{}"); } catch (e) {}
    var chaves = opcoes.map(function (o) {
      var n = norm(o);
      return [n, n.replace(/o\(a\)/g, "a").replace(/\(a\)/g, "a"), n.replace(/\(a\)/g, "")];
    });
    var chavesSin = opcoes.map(function (o) { return (sinonimos[o] || []).map(norm); });
    // 0 = comeca igual, 1 = comeco de outra palavra, 2 = palavra-chave (ex.: "unha"), 3 = no meio
    function rank(i, q) {
      var melhor = 9;
      chaves[i].forEach(function (s) {
        var p = s.indexOf(q);
        if (p === 0) melhor = Math.min(melhor, 0);
        else if (p > 0) melhor = Math.min(melhor, /[\s(/-]/.test(s.charAt(p - 1)) ? 1 : 3);
      });
      if (melhor > 2 && q.length >= 3 && chavesSin[i].some(function (s) { return s.indexOf(q) === 0 || s.indexOf(" " + q) !== -1; })) melhor = 2;
      return melhor;
    }
    function dica(texto) {
      var li = document.createElement("li");
      li.className = "combo-dica"; li.setAttribute("role", "presentation"); li.textContent = texto;
      li.addEventListener("mousedown", function (e) { e.preventDefault(); });
      return li;
    }
    function fechar() {
      ul.hidden = true; ativo = -1;
      inp.setAttribute("aria-expanded", "false"); inp.removeAttribute("aria-activedescendant");
    }
    function marcar(i) {
      ativo = i;
      itens.forEach(function (li, k) { li.setAttribute("aria-selected", k === i ? "true" : "false"); });
      if (i >= 0) { inp.setAttribute("aria-activedescendant", itens[i].id); itens[i].scrollIntoView({ block: "nearest" }); }
      else inp.removeAttribute("aria-activedescendant");
    }
    function escolher(texto) { inp.value = texto; fechar(); inp.focus(); inp.dispatchEvent(new Event("change", { bubbles: true })); }
    function abrir() {
      var q = norm(inp.value.trim());
      var achados = opcoes.map(function (o, i) { return { o: o, r: q ? rank(i, q) : 0, i: i }; })
        .filter(function (a) { return a.r < 9; })
        .sort(function (a, b) { return a.r - b.r || a.i - b.i; })
        .map(function (a) { return a.o; });
      // ja escolheu exatamente uma opcao da lista: nao precisa sugerir
      if (q && opcoes.some(function (o) { return norm(o) === q; })) { fechar(); return; }
      ul.innerHTML = "";
      itens = achados.map(function (o, k) {
        var li = document.createElement("li");
        li.id = ul.id + "-" + k; li.setAttribute("role", "option"); li.setAttribute("aria-selected", "false");
        var pos = q ? norm(o).indexOf(q) : -1;
        if (pos >= 0) {
          li.appendChild(document.createTextNode(o.slice(0, pos)));
          var b = document.createElement("b"); b.textContent = o.slice(pos, pos + q.length); li.appendChild(b);
          li.appendChild(document.createTextNode(o.slice(pos + q.length)));
        } else li.textContent = o;
        li.addEventListener("mousedown", function (e) { e.preventDefault(); escolher(o); });
        ul.appendChild(li); return li;
      });
      if (!q) ul.appendChild(dica("Não achou a sua? Escreva do seu jeito."));
      else if (!achados.length) ul.appendChild(dica("Não está na lista, mas tudo bem: vale como você escreveu."));
      ativo = -1; ul.hidden = false; inp.setAttribute("aria-expanded", "true");
      ul.scrollTop = 0;
    }
    inp.addEventListener("focus", abrir);
    inp.addEventListener("click", function () { if (ul.hidden) abrir(); });
    inp.addEventListener("input", abrir);
    inp.addEventListener("blur", fechar);
    inp.addEventListener("keydown", function (e) {
      var aberta = !ul.hidden;
      if (e.key === "ArrowDown") { e.preventDefault(); if (!aberta) abrir(); if (itens.length) marcar((ativo + 1) % itens.length); }
      else if (e.key === "ArrowUp" && aberta) { e.preventDefault(); marcar(ativo <= 0 ? itens.length - 1 : ativo - 1); }
      else if (e.key === "Enter" && aberta && ativo >= 0) { e.preventDefault(); escolher(itens[ativo].textContent); }
      else if (e.key === "Escape" && aberta) { e.preventDefault(); fechar(); }
      else if (e.key === "Tab") fechar();
    });
  });

  // ------------------------------------------- fotos: camera, galeria, miniaturas
  var temDT = (function () { try { new DataTransfer(); return true; } catch (e) { return false; } })();
  var pendentes = 0;

  // Reduz a foto no celular antes de enviar (mais rapido no 4G e evita arquivo grande demais)
  function reduz(arquivo, lado) {
    return new Promise(function (ok) {
      if (!arquivo.type || arquivo.type.indexOf("image/") !== 0) return ok(arquivo);
      var url = URL.createObjectURL(arquivo), img = new Image();
      img.onload = function () {
        var esc = Math.min(1, lado / Math.max(img.naturalWidth, img.naturalHeight));
        var c = document.createElement("canvas");
        c.width = Math.round(img.naturalWidth * esc); c.height = Math.round(img.naturalHeight * esc);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        c.toBlob(function (b) {
          if (!b) return ok(arquivo);
          ok(new File([b], (arquivo.name || "foto").replace(/\.[^.]*$/, "") + ".jpg", { type: "image/jpeg" }));
        }, "image/jpeg", 0.85);
      };
      img.onerror = function () { URL.revokeObjectURL(url); ok(arquivo); };
      img.src = url;
    });
  }

  var blocos = [];
  document.querySelectorAll(".fotos-bloco").forEach(function (bloco) {
    var modo = bloco.getAttribute("data-fotos");
    var max = parseInt(bloco.getAttribute("data-max"), 10) || 0;
    var real = bloco.querySelector(".js-real");
    var thumbs = bloco.querySelector(".js-thumbs");
    var info = bloco.querySelector(".js-info");
    var picks = bloco.querySelectorAll(".js-pick");
    var estado = { modo: modo, arquivos: [], urls: [], bloco: bloco };
    blocos.push(estado);
    if (!temDT) { bloco.classList.add("sem-dt"); return; }

    function sincroniza() {
      var dt = new DataTransfer();
      estado.arquivos.forEach(function (f) { dt.items.add(f); });
      real.files = dt.files;
    }
    function desenha(msg) {
      estado.urls.forEach(URL.revokeObjectURL);
      estado.urls = estado.arquivos.map(function (f) { return URL.createObjectURL(f); });
      if (modo === "perfil") {
        thumbs.innerHTML = "";
        if (estado.urls[0]) {
          var im = document.createElement("img"); im.src = estado.urls[0]; im.alt = "Sua foto"; thumbs.appendChild(im);
        } else if (thumbs.getAttribute("data-atual") && !(remPerfil && remPerfil.checked)) {
          var at = document.createElement("img"); at.src = thumbs.getAttribute("data-atual"); at.alt = "Sua foto atual"; thumbs.appendChild(at);
        } else {
          var vazio = icone("pessoa", 44); if (vazio) { vazio.setAttribute("class", "ic vazio"); thumbs.appendChild(vazio); }
        }
      } else {
        thumbs.innerHTML = "";
        estado.urls.forEach(function (u, i) {
          var d = document.createElement("div"); d.className = "thumb";
          var im = document.createElement("img"); im.src = u; im.alt = "Foto " + (i + 1);
          var bt = document.createElement("button"); bt.type = "button"; bt.textContent = "×";
          bt.setAttribute("aria-label", "Tirar a foto " + (i + 1));
          bt.addEventListener("click", function () { estado.arquivos.splice(i, 1); sincroniza(); desenha(); });
          d.appendChild(im); d.appendChild(bt); thumbs.appendChild(d);
        });
        var cheio = estado.arquivos.length >= max;
        bloco.querySelectorAll(".pick").forEach(function (p) { p.style.display = cheio ? "none" : ""; });
        if (info) info.textContent = msg || (max <= 0 ? "Você já tem o máximo de fotos. Remova alguma para trocar."
          : estado.arquivos.length ? estado.arquivos.length + " de " + max + " fotos" + (cheio ? " (máximo)" : "") : "");
      }
      document.dispatchEvent(new CustomEvent("fotos-mudaram"));
    }

    picks.forEach(function (pk) {
      pk.addEventListener("change", function () {
        var novos = Array.prototype.slice.call(pk.files || []);
        pk.value = "";
        if (!novos.length) return;
        if (modo === "perfil") novos = novos.slice(0, 1);
        else novos = novos.slice(0, Math.max(0, max - estado.arquivos.length));
        if (!novos.length) return;
        pendentes++;
        if (info) info.textContent = "Preparando foto…";
        Promise.all(novos.map(function (f) { return reduz(f, modo === "perfil" ? 1000 : 1600); })).then(function (prontos) {
          estado.arquivos = modo === "perfil" ? prontos : estado.arquivos.concat(prontos);
          sincroniza(); desenha(); pendentes--;
          if (modo === "perfil") {
            var rem = bloco.querySelector(".js-remover-perfil"); if (rem) rem.checked = false;
          }
        });
      });
    });
    var remPerfil = bloco.querySelector(".js-remover-perfil");
    if (remPerfil) remPerfil.addEventListener("change", function () {
      if (remPerfil.checked) { estado.arquivos = []; sincroniza(); }
      desenha();
    });
    desenha();
  });

  // Nao deixa enviar enquanto uma foto ainda esta sendo preparada
  if (form) form.addEventListener("submit", function (e) {
    if (pendentes > 0) {
      e.preventDefault();
      var tenta = setInterval(function () {
        if (pendentes === 0) { clearInterval(tenta); form.requestSubmit ? form.requestSubmit() : form.submit(); }
      }, 200);
    }
  });

  // ------------------------------------------------------------ previa
  var DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"];
  var DIAS_ROT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
  function formataDias(cods) {
    var idx = DIAS.map(function (c, i) { return cods.indexOf(c) !== -1 ? i : -1; }).filter(function (i) { return i >= 0; });
    if (!idx.length) return "";
    if (idx.length === 7) return "Todos os dias";
    var grupos = [], atual = [idx[0]];
    for (var k = 1; k < idx.length; k++) {
      if (idx[k] === atual[atual.length - 1] + 1) atual.push(idx[k]); else { grupos.push(atual); atual = [idx[k]]; }
    }
    grupos.push(atual);
    var partes = [];
    grupos.forEach(function (gr) {
      if (gr.length >= 3) partes.push(DIAS_ROT[gr[0]] + " a " + DIAS_ROT[gr[gr.length - 1]]);
      else gr.forEach(function (i) { partes.push(DIAS_ROT[i]); });
    });
    return partes.length === 1 ? partes[0] : partes.slice(0, -1).join(", ") + " e " + partes[partes.length - 1];
  }
  function el(tag, cls, texto) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (texto != null) e.textContent = texto;
    return e;
  }
  function valor(nome) {
    var i = form.querySelector("[name=" + nome + "]:checked") || form.querySelector("[name=" + nome + "]:not([type=radio]):not([type=checkbox])");
    return i ? i.value.trim() : "";
  }
  var urlsPrevia = [];

  function montaPrevia() {
    var alvo = document.getElementById("previa");
    if (!alvo || !form) return;
    urlsPrevia.forEach(URL.revokeObjectURL); urlsPrevia = [];
    var ocup = valor("ocupacao");
    var nome = valor("nome") || "Seu nome";
    var exp = form.querySelector("input[name=experiencia]:checked");
    var mei = valor("mei");
    var dom = valor("domicilio");
    var dias = Array.prototype.map.call(form.querySelectorAll("input[name=dias]:checked"), function (c) { return c.value; });
    var horario = valor("horario");
    var regiao = [valor("bairro"), valor("cidade")].filter(Boolean).join(", ") || "seu bairro";

    var perfilEstado = blocos.filter(function (b) { return b.modo === "perfil"; })[0];
    var trabEstado = blocos.filter(function (b) { return b.modo === "trabalhos"; })[0];
    var fotoPerfil = null;
    if (perfilEstado && perfilEstado.arquivos[0]) { fotoPerfil = URL.createObjectURL(perfilEstado.arquivos[0]); urlsPrevia.push(fotoPerfil); }
    else {
      var circ = form.querySelector(".perfil-circulo[data-atual]");
      var rem = form.querySelector(".js-remover-perfil");
      if (circ && !(rem && rem.checked)) fotoPerfil = circ.getAttribute("data-atual");
    }

    alvo.innerHTML = "";
    var perfil = el("div", "perfil");
    if (fotoPerfil) { var im = el("img", "avatar-foto"); im.src = fotoPerfil; im.alt = ""; perfil.appendChild(im); }
    else perfil.appendChild(el("div", "avatar", nome.charAt(0).toUpperCase()));
    perfil.appendChild(el("h3", "nome", nome));
    if (ocup) { var p = el("p"); p.appendChild(el("span", "tag", ocup)); perfil.appendChild(p); }
    if (exp || mei === "sim") {
      var selos = el("div", "selos");
      if (exp) { var s1 = el("span", "selo exp"); s1.appendChild(icone("medalha", 16)); s1.appendChild(document.createTextNode(exp.getAttribute("data-rotulo") + " de experiência")); selos.appendChild(s1); }
      if (mei === "sim") { var s2 = el("span", "selo mei"); s2.appendChild(icone("check", 16)); s2.appendChild(document.createTextNode("MEI formalizado")); selos.appendChild(s2); }
      perfil.appendChild(selos);
    }
    var info = el("ul", "info");
    function linha(ic, txt) { var li = el("li"); li.appendChild(icone(ic, 18)); li.appendChild(document.createTextNode(txt)); info.appendChild(li); }
    linha("pin", "Atende em " + regiao);
    if (dom === "sim") linha("casa", "Atende em domicílio");
    var quando = [formataDias(dias), horario].filter(Boolean).join(" · ");
    if (quando) linha("relogio", quando);
    perfil.appendChild(info);
    perfil.appendChild(el("span", "btn zap", "Chamar no WhatsApp"));
    alvo.appendChild(perfil);

    var servs = [];
    form.querySelectorAll("#servicos .serv").forEach(function (s) {
      var t = s.querySelector("input").value.trim(), d = s.querySelector("textarea").value.trim();
      if (t) servs.push([t, d]);
    });
    if (servs.length) {
      alvo.appendChild(el("h4", null, "Serviços"));
      var card = el("div", "card");
      servs.forEach(function (s) { var sv = el("div", "servico"); sv.appendChild(el("h3", null, s[0])); sv.appendChild(el("p", null, s[1])); card.appendChild(sv); });
      alvo.appendChild(card);
    }

    var srcs = [];
    form.querySelectorAll(".fotos-existentes .foto-item").forEach(function (it) {
      var cb = it.querySelector("input[type=checkbox]");
      if (!cb || !cb.checked) srcs.push(it.querySelector("img").src);
    });
    if (trabEstado) trabEstado.arquivos.forEach(function (f) { var u = URL.createObjectURL(f); urlsPrevia.push(u); srcs.push(u); });
    if (srcs.length) {
      alvo.appendChild(el("h4", null, "Trabalhos realizados"));
      var grid = el("div", "fotos-grid");
      srcs.slice(0, 6).forEach(function (u) { var i2 = el("img"); i2.src = u; i2.alt = ""; grid.appendChild(i2); });
      alvo.appendChild(grid);
    }
  }

  // Previa ao vivo (cartao "Sua vitrine" nas etapas 1 a 5)
  var urlMini = null;
  function montaMini() {
    var alvo = document.getElementById("mini-cartao");
    if (!alvo || !form) return;
    if (urlMini) { URL.revokeObjectURL(urlMini); urlMini = null; }
    var nome = valor("nome"), ocup = valor("ocupacao");
    var local = [valor("bairro"), valor("cidade")].filter(Boolean).join(", ");
    var exp = form.querySelector("input[name=experiencia]:checked");
    var mei = valor("mei");
    var perfil = blocos.filter(function (b) { return b.modo === "perfil"; })[0];
    var trab = blocos.filter(function (b) { return b.modo === "trabalhos"; })[0];
    var nServ = Array.prototype.filter.call(form.querySelectorAll("#servicos input[name=servico_titulo]"), function (i) { return i.value.trim(); }).length;
    var nFotos = trab ? trab.arquivos.length : 0;
    alvo.innerHTML = "";
    var av = el("div", "mini-av");
    if (perfil && perfil.arquivos[0]) { urlMini = URL.createObjectURL(perfil.arquivos[0]); var im = el("img"); im.src = urlMini; im.alt = ""; av.appendChild(im); }
    else if (nome) av.textContent = nome.charAt(0).toUpperCase();
    else { av.className = "mini-av vazio"; var ic = icone("pessoa", 26); av.appendChild(ic); }
    alvo.appendChild(av);
    alvo.appendChild(el("div", "mini-nome" + (nome ? "" : " mini-vazio"), nome || "Seu nome"));
    var linha = el("div", "mini-linha");
    linha.appendChild(el("span", "tag" + (ocup ? "" : " mini-vazio"), ocup || "Sua profissão"));
    if (exp) { var s1 = el("span", "selo exp"); s1.appendChild(icone("medalha", 12)); s1.appendChild(document.createTextNode(exp.getAttribute("data-rotulo"))); linha.appendChild(s1); }
    if (mei === "sim") { var s2 = el("span", "selo mei"); s2.appendChild(icone("check", 12)); s2.appendChild(document.createTextNode("MEI")); linha.appendChild(s2); }
    var lc = el("span", "mini-local" + (local ? "" : " mini-vazio")); lc.appendChild(icone("pin", 13)); lc.appendChild(document.createTextNode(local || "Seu bairro")); linha.appendChild(lc);
    alvo.appendChild(linha);
    var partes = [];
    if (nServ) partes.push(nServ + (nServ > 1 ? " serviços" : " serviço"));
    if (nFotos) partes.push(nFotos + (nFotos > 1 ? " fotos" : " foto"));
    if (partes.length) { var pe = el("div", "mini-pe"); pe.appendChild(el("span", "mini-conta", partes.join(" · "))); alvo.appendChild(pe); }
  }

  if (form) {
    var tPrevia, tMini;
    var agenda = function () {
      clearTimeout(tMini); tMini = setTimeout(montaMini, 80);
      var alvo = document.getElementById("previa");
      if (!alvo || !alvo.offsetParent) return;
      clearTimeout(tPrevia); tPrevia = setTimeout(montaPrevia, 150);
    };
    form.addEventListener("input", agenda);
    form.addEventListener("change", agenda);
    document.addEventListener("fotos-mudaram", agenda);
    if (form.classList.contains("form-edicao")) montaPrevia();
    montaMini();
  }

  // ------------------------------------- botao de enviar so com a autorizacao marcada
  var consent = document.getElementById("consentimento");
  if (consent && form) {
    var botoes = form.querySelectorAll("button[type=submit]");
    var aviso = document.createElement("p");
    aviso.className = "aviso-envio"; aviso.id = "aviso-envio";
    aviso.textContent = "Marque a autorização acima para continuar.";
    consent.closest("label").insertAdjacentElement("afterend", aviso);
    var atualizaEnvio = function () {
      botoes.forEach(function (b) {
        b.disabled = !consent.checked;
        if (consent.checked) b.removeAttribute("aria-describedby"); else b.setAttribute("aria-describedby", "aviso-envio");
      });
      aviso.hidden = consent.checked;
    };
    consent.addEventListener("change", atualizaEnvio);
    atualizaEnvio();
  }

  // ------------------------------------------------------ cadastro passo a passo
  var stepper = document.querySelector("form[data-stepper]");
  if (stepper) {
    var passos = Array.prototype.slice.call(stepper.querySelectorAll(".passo"));
    var atual = 0;
    var txt = stepper.querySelector(".progresso");
    var barra = stepper.querySelector(".barra i");
    var voltar = stepper.querySelector(".js-voltar");
    var proximo = stepper.querySelector(".js-proximo");
    var enviar = stepper.querySelector(".js-enviar");

    var mostra = function (n, registrar) {
      atual = n;
      passos.forEach(function (p, i) { p.classList.toggle("ativo", i === n); });
      txt.textContent = "Passo " + (n + 1) + " de " + passos.length + " · " + passos[n].getAttribute("data-titulo");
      barra.style.width = ((n + 1) / passos.length * 100) + "%";
      voltar.style.visibility = n === 0 ? "hidden" : "visible";
      proximo.style.display = n === passos.length - 1 ? "none" : "block";
      enviar.style.display = n === passos.length - 1 ? "block" : "none";
      if (passos[n].hasAttribute("data-previa")) montaPrevia();
      var mini = document.getElementById("mini-previa");
      if (mini) { mini.classList.toggle("oculta", passos[n].hasAttribute("data-previa")); montaMini(); }
      if (registrar) beacon("cadastro_passo", String(n + 1));
      window.scrollTo(0, 0);
    };
    var valido = function () {
      var campos = passos[atual].querySelectorAll("input,textarea,select");
      for (var i = 0; i < campos.length; i++) {
        if (!campos[i].disabled && !campos[i].checkValidity()) {
          var alvo = campos[i].type === "radio" ? campos[i].closest("fieldset") || campos[i] : campos[i];
          if (alvo.scrollIntoView) alvo.scrollIntoView({ block: "center" });
          campos[i].reportValidity();
          return false;
        }
      }
      return true;
    };
    proximo.addEventListener("click", function () { if (valido() && atual < passos.length - 1) mostra(atual + 1, true); });
    voltar.addEventListener("click", function () { if (atual > 0) mostra(atual - 1, false); });
    stepper.addEventListener("submit", function (e) { if (!valido()) e.preventDefault(); });
    var inicio = Math.min(Math.max(parseInt(stepper.getAttribute("data-inicio"), 10) || 1, 1), passos.length) - 1;
    mostra(inicio, false);
  }
})();
