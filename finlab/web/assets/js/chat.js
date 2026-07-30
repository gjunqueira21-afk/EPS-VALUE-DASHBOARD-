/* Caixa de conversa com a mesa, fixa no canto inferior direito.

   Vive em todas as telas. O contexto enviado é o do ativo aberto (quando há
   um) mais as premissas correntes do painel — as mesmas que os agentes da
   aba Mesa de IA recebem. A conversa fica no navegador; nada é gravado no
   servidor. */
(function (global) {
  'use strict';

  const { h, el, esc, api, markdown, loadSlots, prefs } = global.FL;

  const HIST_KEY = 'finlab.chat.hist.v1';
  const state = { aberto: false, enviando: false, ticker: null, ctx: null, montado: false };

  /* -------------------------------------------------------------- histórico */

  function carregar() {
    try {
      const raw = sessionStorage.getItem(HIST_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }

  function salvar(msgs) {
    try { sessionStorage.setItem(HIST_KEY, JSON.stringify(msgs.slice(-40))); } catch (e) { /* noop */ }
  }

  /* ------------------------------------------------------------------ slot */

  function slotAtivo() {
    const slots = loadSlots();
    const escolhido = prefs.get('chat.slot', null);
    if (escolhido) {
      const s = slots.find((x) => x.id === escolhido);
      if (s && s.api_key && s.model) return s;
    }
    return slots.find((x) => x.api_key && x.model) || null;
  }

  /* ----------------------------------------------------------------- render */

  function bolha(msg) {
    const meu = msg.role === 'user';
    return h('div', { class: 'chat-msg ' + (meu ? 'me' : 'ai') },
      h('div', {
        class: 'chat-bubble',
        html: meu ? esc(msg.content) : markdown(msg.content)
      }));
  }

  function pintarHistorico() {
    const corpo = el('chat-body');
    if (!corpo) return;
    const msgs = carregar();
    corpo.innerHTML = '';
    if (!msgs.length) {
      corpo.appendChild(h('div', { class: 'chat-vazio' }, [
        h('div', { class: 'chat-vazio-mark', html: brainSvg() }),
        h('div', {
          html: state.ticker
            ? `Pergunte o que quiser sobre <b>${esc(state.ticker)}</b> — fundamentos, `
              + 'múltiplos, premissas do modelo, comparação com os pares.'
            : 'Abra uma empresa para conversar sobre ela, ou pergunte sobre o macro do dia.'
        })
      ]));
    } else {
      msgs.forEach((m) => corpo.appendChild(bolha(m)));
    }
    corpo.scrollTop = corpo.scrollHeight;
  }

  function atualizarRodape() {
    const info = el('chat-slot');
    if (!info) return;
    const slots = loadSlots();
    const prontos = slots.filter((s) => s.api_key && s.model);
    info.innerHTML = '';
    if (!prontos.length) {
      info.appendChild(h('button', {
        class: 'btn ghost sm',
        onclick: () => global.FLSettings.open(() => { atualizarRodape(); })
      }, '⚙ configurar IA'));
      return;
    }
    const atual = slotAtivo();
    const sel = h('select', {
      title: 'Slot usado nesta conversa',
      onchange: (ev) => prefs.set('chat.slot', Number(ev.target.value) || null)
    }, prontos.map((s) => h('option', {
      value: s.id, selected: atual && s.id === atual.id ? 'selected' : null
    }, `Slot ${s.id} · ${s.label || s.model}`)));
    info.appendChild(sel);
  }

  /* ---------------------------------------------------------------- envio */

  async function enviar() {
    if (state.enviando) return;
    const campo = el('chat-input');
    const texto = campo.value.trim();
    if (!texto) return;

    const slot = slotAtivo();
    const msgs = carregar();

    if (!slot) {
      msgs.push({ role: 'user', content: texto });
      msgs.push({
        role: 'assistant',
        content: 'Nenhum slot de IA configurado ainda. Clique em **⚙ configurar IA** aqui '
          + 'embaixo e cadastre uma chave — OpenRouter, OpenAI, Anthropic, Google, Groq ou '
          + 'DeepSeek.'
      });
      salvar(msgs); pintarHistorico(); campo.value = '';
      return;
    }

    msgs.push({ role: 'user', content: texto });
    salvar(msgs);
    campo.value = '';
    campo.style.height = 'auto';
    pintarHistorico();

    state.enviando = true;
    const corpo = el('chat-body');
    const pensando = h('div', { class: 'chat-msg ai' },
      h('div', { class: 'chat-bubble' }, [h('span', { class: 'spinner' }), ' pensando…']));
    corpo.appendChild(pensando);
    corpo.scrollTop = corpo.scrollHeight;
    el('chat-send').disabled = true;

    try {
      const ctx = (state.ctx && state.ctx()) || {};
      const r = await api('/api/agents/chat', {
        method: 'POST',
        body: JSON.stringify({
          slot: { provider: slot.provider, api_key: slot.api_key, model: slot.model },
          ticker: state.ticker,
          assumptions: ctx.assumptions || null,
          resultado: ctx.resultado || null,
          historico: msgs.slice(0, -1),
          pergunta: texto
        })
      });
      msgs.push({ role: 'assistant', content: r.texto });
    } catch (err) {
      msgs.push({ role: 'assistant', content: '⚠️ ' + err.message });
    } finally {
      state.enviando = false;
      el('chat-send').disabled = false;
      salvar(msgs);
      pintarHistorico();
      el('chat-input').focus();
    }
  }

  /* ---------------------------------------------------------------- montagem */

  /* O cérebro do cabeçalho já está no documento com esses ids de gradiente.
     Repetir os mesmos ids aqui deixaria dois elementos disputando o mesmo
     url(#…) — renomeia antes de injetar. */
  function brainSvg() {
    return global.FL.BRAIN_SVG
      .replace(/bgGlow/g, 'bgGlowChat')
      .replace(/bgStroke/g, 'bgStrokeChat');
  }

  function montar() {
    if (state.montado) return;
    state.montado = true;

    const botao = h('button', {
      class: 'chat-fab', id: 'chat-fab', title: 'Conversar com a mesa (Ctrl+K)',
      'aria-label': 'Abrir conversa com a mesa de análise',
      onclick: alternar
    }, h('span', { html: brainSvg() }));

    const painel = h('section', { class: 'chat-panel', id: 'chat-panel', hidden: 'hidden' }, [
      h('header', { class: 'chat-head' }, [
        h('div', {}, [
          h('div', { class: 'chat-title' }, 'Mesa de análise'),
          h('div', { class: 'chat-sub', id: 'chat-ctx' }, '—')
        ]),
        h('span', { style: 'flex:1 1 auto' }),
        h('button', {
          class: 'btn ghost sm', title: 'Limpar a conversa',
          onclick: () => { salvar([]); pintarHistorico(); }
        }, '🗑'),
        h('button', { class: 'btn ghost sm', title: 'Fechar', onclick: alternar }, '✕')
      ]),
      h('div', { class: 'chat-body', id: 'chat-body' }),
      h('div', { class: 'chat-foot' }, [
        h('div', { class: 'chat-inputrow' }, [
          h('textarea', {
            id: 'chat-input', rows: '1', placeholder: 'Pergunte sobre este ativo…',
            oninput: (ev) => {
              ev.target.style.height = 'auto';
              ev.target.style.height = Math.min(ev.target.scrollHeight, 120) + 'px';
            },
            onkeydown: (ev) => {
              if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); enviar(); }
            }
          }),
          h('button', { class: 'btn primary', id: 'chat-send', onclick: enviar }, '➤')
        ]),
        h('div', { class: 'chat-slotrow' }, [
          h('span', { id: 'chat-slot' }),
          h('span', { style: 'flex:1 1 auto' }),
          h('span', { class: 'chat-hint' }, 'Enter envia · Shift+Enter quebra linha')
        ])
      ])
    ]);

    document.body.appendChild(botao);
    document.body.appendChild(painel);

    document.addEventListener('keydown', (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k') {
        ev.preventDefault(); alternar();
      }
      if (ev.key === 'Escape' && state.aberto) alternar();
    });

    pintarHistorico();
    atualizarRodape();
  }

  function alternar() {
    const painel = el('chat-panel');
    state.aberto = !state.aberto;
    painel.hidden = !state.aberto;
    el('chat-fab').classList.toggle('on', state.aberto);
    if (state.aberto) {
      atualizarRodape();
      pintarHistorico();
      setTimeout(() => el('chat-input').focus(), 60);
    }
  }

  /**
   * Liga o chat a uma tela.
   *   ticker: ativo aberto (ou null nas telas de lista)
   *   rotulo: texto mostrado no cabeçalho
   *   ctx:    função que devolve {assumptions, resultado} no momento do envio
   */
  function init(opts) {
    const o = opts || {};
    montar();
    state.ticker = o.ticker || null;
    state.ctx = typeof o.ctx === 'function' ? o.ctx : null;
    const rotulo = el('chat-ctx');
    if (rotulo) {
      rotulo.textContent = o.rotulo
        || (state.ticker ? 'sobre ' + state.ticker : 'abra uma empresa para ir a fundo');
    }
    const campo = el('chat-input');
    if (campo) {
      campo.placeholder = state.ticker
        ? `Pergunte sobre ${state.ticker}…`
        : 'Pergunte sobre o mercado…';
    }
    pintarHistorico();
  }

  global.FLChat = { init, alternar };
})(window);
