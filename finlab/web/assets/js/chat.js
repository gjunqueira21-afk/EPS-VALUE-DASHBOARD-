/* Caixa de conversa com a mesa, fixa no canto inferior direito.

   Vive em todas as telas. O contexto enviado é o do ativo aberto (quando há
   um) mais as premissas correntes do painel — as mesmas que os agentes da
   aba Mesa de IA recebem. A conversa fica no navegador; nada é gravado no
   servidor.

   Quem responde é escolhido no rodapé: a mesa inteira (cada agente fala pela
   sua especialidade e no fim sai uma conclusão) ou um agente só. Dá para
   chamar alguém pelo nome no meio da pergunta — "gestor, vale a posição?" —
   que a conversa vai direto para ele. */
(function (global) {
  'use strict';

  const { h, el, esc, api, markdown, loadSlots, loadAgentNames, agentIcon, prefs } = global.FL;

  const HIST_KEY = 'finlab.chat.hist.v1';
  const ORDEM = ['equity', 'macro', 'gestor', 'premissas'];

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

  /** O que vai ao modelo como histórico: só o fio da conversa, sem os avisos
   *  locais do painel e sem as falas dos outros agentes da mesma rodada. */
  function fio(msgs) {
    return msgs
      .filter((m) => !m.local && m.content && String(m.content).trim())
      .map((m) => ({ role: m.role, content: m.content }));
  }

  /* ------------------------------------------------------------------ slot */

  /** Slot de cada agente: o que ele já usa na aba Mesa de IA, senão o
   *  primeiro configurado. Assim uma chave só atende a mesa inteira. */
  function slotDo(agentKey) {
    const slots = loadSlots();
    const prontos = slots.filter((s) => s.api_key && s.model);
    const escolhido = agentKey ? prefs.get('agentSlot.' + agentKey, null) : null;
    if (escolhido) {
      const s = prontos.find((x) => x.id === escolhido);
      if (s) return s;
    }
    return prontos[0] || null;
  }

  function temSlot() { return loadSlots().some((s) => s.api_key && s.model); }

  /* ------------------------------------------------------------- destinatário */

  function alvo() { return prefs.get('chat.alvo', 'mesa'); }

  /** "gestor, vale a posição?" fala com o gestor, mesmo com a mesa escolhida. */
  function alvoDaPergunta(texto) {
    const nomes = loadAgentNames();
    const inicio = texto.slice(0, 60).toLowerCase();
    const achado = ORDEM.find((k) => {
      const nome = (nomes[k] || '').toLowerCase().replace(/^agente\s+/, '');
      return nome && (inicio.startsWith(nome) || inicio.startsWith('agente ' + nome)
        || inicio.startsWith('@' + nome));
    });
    return achado || null;
  }

  /* ----------------------------------------------------------------- render */

  function bolha(msg) {
    const meu = msg.role === 'user';
    const corpo = h('div', {
      class: 'chat-bubble',
      html: meu ? esc(msg.content) : markdown(msg.content)
    });
    const caixa = h('div', { class: 'chat-msg ' + (meu ? 'me' : 'ai') });
    if (!meu && msg.autor) {
      caixa.classList.add('nomeado');
      if (msg.agente === 'sintese') caixa.classList.add('sintese');
      caixa.appendChild(h('div', { class: 'chat-autor' }, [
        h('span', { class: 'ico' }, msg.icone || '🧠'),
        h('span', {}, msg.autor)
      ]));
    }
    caixa.appendChild(corpo);
    return caixa;
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
              + 'múltiplos, premissas do modelo, comparação com os pares.<br><br>'
              + 'A mesa inteira responde e fecha com uma conclusão. Para falar com um '
              + 'só, escolha embaixo ou comece a frase com o nome dele.'
            : 'Abra uma empresa para conversar sobre ela, ou pergunte sobre o macro do dia.'
        })
      ]));
    } else {
      msgs.forEach((m) => corpo.appendChild(bolha(m)));
    }
    corpo.scrollTop = corpo.scrollHeight;
  }

  /** Acrescenta uma mensagem, grava e rola — sem repintar tudo, para que as
   *  falas da mesa entrem uma a uma em vez de piscar a lista inteira. */
  function empilhar(msg) {
    const msgs = carregar();
    msgs.push(msg);
    salvar(msgs);
    const corpo = el('chat-body');
    if (corpo.querySelector('.chat-vazio')) corpo.innerHTML = '';
    corpo.appendChild(bolha(msg));
    corpo.scrollTop = corpo.scrollHeight;
    return msgs;
  }

  function atualizarRodape() {
    const info = el('chat-alvo');
    if (!info) return;
    info.innerHTML = '';

    if (!temSlot()) {
      info.appendChild(h('button', {
        class: 'btn ghost sm',
        onclick: () => global.FLSettings.open(() => { atualizarRodape(); })
      }, '⚙ configurar IA'));
      return;
    }

    const nomes = loadAgentNames();
    const atual = alvo();
    const sel = h('select', {
      id: 'chat-alvo-sel',
      title: 'Quem responde: a mesa inteira ou um agente',
      onchange: (ev) => prefs.set('chat.alvo', ev.target.value)
    }, [h('option', { value: 'mesa', selected: atual === 'mesa' ? 'selected' : null },
      '🧠 Mesa inteira')].concat(ORDEM.map((k) => h('option', {
      value: k, selected: k === atual ? 'selected' : null
    }, `${agentIcon(k)} ${nomes[k]}`))));
    info.appendChild(sel);
  }

  /* ---------------------------------------------------------------- envio */

  function pensando(rotulo, icone) {
    const n = h('div', { class: 'chat-msg ai nomeado pensando' }, [
      h('div', { class: 'chat-autor' }, [
        h('span', { class: 'ico' }, icone || '🧠'), h('span', {}, rotulo)
      ]),
      h('div', { class: 'chat-bubble' }, [h('span', { class: 'spinner' }), ' pensando…'])
    ]);
    const corpo = el('chat-body');
    if (corpo.querySelector('.chat-vazio')) corpo.innerHTML = '';
    corpo.appendChild(n);
    corpo.scrollTop = corpo.scrollHeight;
    return n;
  }

  /** Uma fala. Devolve o texto ou null, e nunca deixa bolha vazia na tela. */
  async function falar(agente, rotulo, icone, pergunta, historico, extra) {
    const slot = slotDo(agente);
    const marca = pensando(rotulo, icone);
    try {
      const r = await api('/api/agents/chat', {
        method: 'POST',
        body: JSON.stringify(Object.assign({
          slot: { provider: slot.provider, api_key: slot.api_key, model: slot.model },
          ticker: state.ticker,
          assumptions: (state.ctxAtual || {}).assumptions || null,
          resultado: (state.ctxAtual || {}).resultado || null,
          historico: historico,
          pergunta: pergunta,
          agente: agente || null
        }, extra || {}))
      });
      marca.remove();
      const texto = (r.texto || '').trim();
      if (!texto) {
        empilhar({
          role: 'assistant', autor: rotulo, icone: icone, agente: agente, local: true,
          content: '⚠️ Resposta vazia do provedor. Tente de novo ou troque o modelo do slot.'
        });
        return null;
      }
      empilhar({ role: 'assistant', autor: rotulo, icone: icone, agente: agente, content: texto });
      return texto;
    } catch (err) {
      marca.remove();
      empilhar({
        role: 'assistant', autor: rotulo, icone: icone, agente: agente, local: true,
        content: '⚠️ ' + err.message
      });
      return null;
    }
  }

  async function enviar() {
    if (state.enviando) return;
    const campo = el('chat-input');
    const texto = campo.value.trim();
    if (!texto) return;

    if (!temSlot()) {
      empilhar({ role: 'user', content: texto });
      empilhar({
        role: 'assistant', local: true,
        content: 'Nenhum slot de IA configurado ainda. Clique em **⚙ configurar IA** aqui '
          + 'embaixo e cadastre uma chave — OpenRouter, OpenAI, Anthropic, Google, Groq ou '
          + 'DeepSeek.'
      });
      campo.value = '';
      return;
    }

    // O histórico enviado é o de ANTES desta pergunta.
    const anterior = fio(carregar());
    empilhar({ role: 'user', content: texto });
    campo.value = '';
    campo.style.height = 'auto';

    state.enviando = true;
    el('chat-send').disabled = true;
    state.ctxAtual = (state.ctx && state.ctx()) || {};

    const nomes = loadAgentNames();
    const dirigido = alvoDaPergunta(texto);
    const escolha = dirigido || alvo();

    try {
      if (escolha !== 'mesa') {
        await falar(escolha, nomes[escolha], agentIcon(escolha), texto, anterior);
      } else {
        // Cada agente fala na sua vez, e a bolha aparece assim que chega —
        // é a reunião acontecendo na tela, não um bloco no fim.
        const respostas = [];
        for (const k of ORDEM) {
          const r = await falar(k, nomes[k], agentIcon(k), texto, anterior);
          if (r) respostas.push({ agente: k, nome: nomes[k], texto: r });
        }
        if (respostas.length >= 2) {
          await falar('sintese', 'Conclusão da mesa', '⚖️', texto, anterior,
            { respostas: respostas });
        }
      }
    } finally {
      state.enviando = false;
      el('chat-send').disabled = false;
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
          h('span', { id: 'chat-alvo' }),
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
      if (!state.enviando) pintarHistorico();
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
    atualizarRodape();
  }

  global.FLChat = { init, alternar, atualizarRodape };
})(window);
