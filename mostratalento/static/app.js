(function () {
  "use strict";

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

  // Cliques que viram eventos: <a data-evento="..." data-slug="...">
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
        cp.textContent = "Copiado ✔";
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

  // Perguntas do guia do MEI
  document.querySelectorAll("details[data-q]").forEach(function (d) {
    d.addEventListener("toggle", function () {
      if (d.open) beacon("guia_mei_pergunta", d.getAttribute("data-q"));
    });
  });

  // Adicionar servico
  var lista = document.getElementById("servicos");
  var add = document.getElementById("add-servico");
  if (lista && add) {
    var max = parseInt(lista.getAttribute("data-max") || "5", 10);
    add.addEventListener("click", function () {
      var itens = lista.querySelectorAll(".serv");
      if (itens.length >= max) return;
      var novo = itens[0].cloneNode(true);
      novo.querySelectorAll("input,textarea").forEach(function (i) { i.value = ""; i.required = false; });
      lista.appendChild(novo);
      novo.querySelector("input").focus();
      if (lista.querySelectorAll(".serv").length >= max) add.style.display = "none";
    });
  }

  // Cadastro passo a passo
  var form = document.querySelector("form[data-stepper]");
  if (form) {
    var passos = Array.prototype.slice.call(form.querySelectorAll(".passo"));
    var atual = 0;
    var txt = form.querySelector(".progresso");
    var barra = form.querySelector(".barra i");
    var voltar = form.querySelector(".js-voltar");
    var proximo = form.querySelector(".js-proximo");
    var enviar = form.querySelector(".js-enviar");

    function mostra(n, registrar) {
      atual = n;
      passos.forEach(function (p, i) { p.classList.toggle("ativo", i === n); });
      txt.textContent = "Passo " + (n + 1) + " de " + passos.length;
      barra.style.width = ((n + 1) / passos.length * 100) + "%";
      voltar.style.visibility = n === 0 ? "hidden" : "visible";
      proximo.style.display = n === passos.length - 1 ? "none" : "block";
      enviar.style.display = n === passos.length - 1 ? "block" : "none";
      if (registrar) beacon("cadastro_passo", String(n + 1));
      window.scrollTo(0, 0);
    }

    function valido() {
      var campos = passos[atual].querySelectorAll("input,textarea,select");
      for (var i = 0; i < campos.length; i++) {
        if (!campos[i].checkValidity()) { campos[i].reportValidity(); return false; }
      }
      return true;
    }

    proximo.addEventListener("click", function () { if (valido() && atual < passos.length - 1) mostra(atual + 1, true); });
    voltar.addEventListener("click", function () { if (atual > 0) mostra(atual - 1, false); });
    form.addEventListener("submit", function (e) { if (!valido()) e.preventDefault(); });
    mostra(0, false);
  }

  // Lista de sugestoes com o visual do app (substitui o datalist do navegador)
  document.querySelectorAll("input[data-sugestoes]").forEach(function (inp) {
    var opcoes = [];
    try { opcoes = JSON.parse(inp.getAttribute("data-sugestoes")); } catch (e) {}
    var lista = document.getElementById(inp.getAttribute("aria-controls"));
    if (!lista || !opcoes.length) return;
    var ativo = -1, itens = [];

    function norm(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
    function fechar() {
      lista.hidden = true; ativo = -1;
      inp.setAttribute("aria-expanded", "false"); inp.removeAttribute("aria-activedescendant");
    }
    function marcar(i) {
      ativo = i;
      itens.forEach(function (li, k) { li.setAttribute("aria-selected", k === i ? "true" : "false"); });
      if (i >= 0) {
        inp.setAttribute("aria-activedescendant", itens[i].id);
        itens[i].scrollIntoView({ block: "nearest" });
      } else inp.removeAttribute("aria-activedescendant");
    }
    function escolher(texto) { inp.value = texto; fechar(); inp.focus(); }
    function abrir() {
      var q = norm(inp.value.trim());
      var achados = opcoes.filter(function (o) { return !q || norm(o).indexOf(q) !== -1; });
      // ja digitou exatamente uma opcao: nao precisa sugerir
      if (!achados.length || (achados.length === 1 && norm(achados[0]) === q)) { fechar(); return; }
      lista.innerHTML = "";
      itens = achados.map(function (o, k) {
        var li = document.createElement("li");
        li.id = lista.id + "-" + k; li.setAttribute("role", "option"); li.setAttribute("aria-selected", "false");
        var pos = q ? norm(o).indexOf(q) : -1;
        if (pos >= 0) {
          li.appendChild(document.createTextNode(o.slice(0, pos)));
          var b = document.createElement("b"); b.textContent = o.slice(pos, pos + q.length); li.appendChild(b);
          li.appendChild(document.createTextNode(o.slice(pos + q.length)));
        } else li.textContent = o;
        // mousedown (e nao click) para escolher antes de o campo perder o foco
        li.addEventListener("mousedown", function (e) { e.preventDefault(); escolher(o); });
        lista.appendChild(li); return li;
      });
      ativo = -1; lista.hidden = false; inp.setAttribute("aria-expanded", "true");
    }

    inp.addEventListener("focus", abrir);
    inp.addEventListener("click", function () { if (lista.hidden) abrir(); });
    inp.addEventListener("input", abrir);
    inp.addEventListener("blur", fechar);
    inp.addEventListener("keydown", function (e) {
      var aberta = !lista.hidden;
      if (e.key === "ArrowDown") { e.preventDefault(); if (!aberta) abrir(); if (itens.length) marcar((ativo + 1) % itens.length); }
      else if (e.key === "ArrowUp" && aberta) { e.preventDefault(); marcar(ativo <= 0 ? itens.length - 1 : ativo - 1); }
      else if (e.key === "Enter" && aberta && ativo >= 0) { e.preventDefault(); escolher(itens[ativo].textContent); }
      else if (e.key === "Escape" && aberta) { e.preventDefault(); fechar(); }
      else if (e.key === "Tab") fechar();
    });
  });

  // Resumo de fotos escolhidas
  document.querySelectorAll("input[type=file][data-max]").forEach(function (inp) {
    inp.addEventListener("change", function () {
      var max = parseInt(inp.getAttribute("data-max"), 10);
      var out = document.getElementById("fotos-info");
      if (inp.files.length > max) {
        inp.value = "";
        if (out) out.textContent = "Escolha no máximo " + max + " fotos.";
      } else if (out) {
        out.textContent = inp.files.length ? inp.files.length + " foto(s) escolhida(s)." : "";
      }
    });
  });
})();
