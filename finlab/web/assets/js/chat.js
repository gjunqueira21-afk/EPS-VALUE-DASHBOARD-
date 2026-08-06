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
  const SAVED_KEY = 'finlab.chat.saved.v1';

  /* A mesa inteira vive aqui agora — a aba "Mesa de IA" saiu de cena. A lista
     de agentes (e a ordem das ondas: Radar abre, corpo em paralelo, Cético lê,
     Moderador fecha) é do backend; este padrão só cobre o /api/config falhar. */
  let MESA = [
    { key: 'contexto', abre_rodada: true, le_a_mesa: false, ordem: 0 },
    { key: 'equity', ordem: 0 }, { key: 'macro', ordem: 0 },
    { key: 'gestor', ordem: 0 }, { key: 'premissas', ordem: 0 },
    { key: 'cetico', le_a_mesa: true, ordem: 1 },
    { key: 'moderador', le_a_mesa: true, ordem: 2 }
  ];

  async function carregarMesa() {
    try {
      const cfg = await api('/api/config');
      if (Array.isArray(cfg.agents) && cfg.agents.length) {
        MESA = cfg.agents;
        if (global.FL.setAgentOrder) global.FL.setAgentOrder(MESA.map((a) => a.key));
        atualizarRodape();
      }
    } catch (e) { /* fica o padrão */ }
  }

  const state = { aberto: false, enviando: false, ticker: null, tela: null, ctx: null,
                  montado: false, anexo: null };

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

  /** A configuração do agente: a dele, ou a herdada de quem tem chave. */
  function slotDo(agentKey) {
    return global.FL.agentConfig(agentKey);
  }

  function temSlot() { return loadSlots().some((s) => s.api_key && s.model); }

  /* ------------------------------------------------------------- destinatário */

  function alvo() { return prefs.get('chat.alvo', 'mesa'); }

  /** "gestor, vale a posição?" fala com o gestor, mesmo com a mesa escolhida. */
  function alvoDaPergunta(texto) {
    const nomes = loadAgentNames();
    const inicio = texto.slice(0, 60).toLowerCase();
    const achado = MESA.map((a) => a.key).find((k) => {
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
      // O destaque de fechamento vale para quem fecha: era a "sintese", hoje é
      // o Moderador — a fala que o usuário procura primeiro ao reler.
      if (msg.agente === 'sintese' || msg.agente === 'moderador') caixa.classList.add('sintese');
      const cracha = [
        h('span', { class: 'ico' }, msg.icone || '🧠'),
        h('span', {}, msg.autor)
      ];
      // Qual modelo respondeu: a pergunta "quem está usando o quê" tem de ter
      // resposta olhando a própria fala, não só no modal de configuração.
      if (msg.modelo) {
        cracha.push(h('span', {
          class: 'chat-modelo', title: 'Slot usado por este agente'
        }, msg.modelo));
      }
      caixa.appendChild(h('div', { class: 'chat-autor' }, cracha));
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
            : state.tela
              ? 'A mesa enxerga <b>tudo o que está nesta tela</b> — pergunte sobre o '
                + 'conjunto. Ex.: <i>"se fosse montar uma carteira com as melhores, '
                + 'quais seriam?"</i>'
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
      '🧠 Mesa inteira')].concat(MESA.map((a) => h('option', {
      value: a.key, selected: a.key === atual ? 'selected' : null
    }, `${agentIcon(a.key)} ${nomes[a.key] || a.label || a.key}`))));
    info.appendChild(sel);
  }

  /* ---------------------------------------------------------------- envio */

  function pensando(rotulo, icone, modelo) {
    const n = h('div', { class: 'chat-msg ai nomeado pensando' }, [
      h('div', { class: 'chat-autor' }, [
        h('span', { class: 'ico' }, icone || '🧠'), h('span', {}, rotulo),
        modelo ? h('span', { class: 'chat-modelo' }, modelo) : null
      ].filter(Boolean)),
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
    const marca = pensando(rotulo, icone, slot && slot.model);
    try {
      const r = await api('/api/agents/chat', {
        method: 'POST',
        body: JSON.stringify(Object.assign({
          slot: { provider: slot.provider, api_key: slot.api_key, model: slot.model },
          ticker: state.ticker,
          tela: state.tela,
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
      empilhar({ role: 'assistant', autor: rotulo, icone: icone, agente: agente,
                 modelo: r.modelo || (slot && slot.model), content: texto });
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

    // O anexo vale para ESTA pergunta: vai para quem foi endereçado — na mesa
    // inteira, para o Radar, que abre a rodada e repassa o que leu.
    const anexo = state.anexo;
    state.anexo = null;
    pintarAnexo();
    const comAnexo = anexo ? { anexo: anexo } : {};

    try {
      if (escolha !== 'mesa') {
        await falar(escolha, nomes[escolha] || escolha, agentIcon(escolha), texto,
          anterior, comAnexo);
      } else {
        // A rodada acontece em ondas, como na mesa: o Radar abre (o que ele
        // levanta chega aos outros cercado como não verificado), o corpo fala,
        // o Cético contesta lendo as falas, o Moderador fecha lendo tudo.
        // Cada bolha aparece assim que chega — é a reunião na tela.
        const abre = MESA.filter((a) => a.abre_rodada);
        const corpo = MESA.filter((a) => !a.abre_rodada && !(a.ordem > 0));
        const leitores = MESA.filter((a) => !a.abre_rodada && a.ordem > 0)
          .sort((x, y) => (x.ordem || 0) - (y.ordem || 0));

        let radar = '';
        const respostas = [];
        for (const a of abre) {
          const r = await falar(a.key, nomes[a.key] || a.key, agentIcon(a.key),
            texto, anterior, comAnexo);
          if (r) { radar = r; respostas.push({ agente: a.key, nome: nomes[a.key], texto: r }); }
        }
        // Com o Radar falando, o que ele leu do anexo segue via radar; sem
        // Radar (ou se ele falhou), o anexo não pode evaporar — vai ao corpo.
        const extra = radar ? { radar: radar } : {};
        if (!radar && anexo) extra.anexo = anexo;
        for (const a of corpo) {
          const r = await falar(a.key, nomes[a.key] || a.key, agentIcon(a.key),
            texto, anterior, extra);
          if (r) respostas.push({ agente: a.key, nome: nomes[a.key], texto: r });
        }
        // Com uma fala só não há mesa para ler: os leitores só entram quando
        // existe divergência possível.
        if (respostas.length >= 2) {
          for (const a of leitores) {
            const r = await falar(a.key, nomes[a.key] || a.key, agentIcon(a.key),
              texto, anterior, Object.assign({ respostas: respostas.slice() }, extra));
            if (r) respostas.push({ agente: a.key, nome: nomes[a.key], texto: r });
          }
        }
      }
    } finally {
      state.enviando = false;
      el('chat-send').disabled = false;
      el('chat-input').focus();
    }
  }

  /* ------------------------------------------------------------ anexo (PDF) */
  /* O usuário pode anexar um PDF — release, apresentação, relatório — e pedir
     que um agente o leia. O texto é extraído pelo servidor na hora do anexo
     (nada fica gravado lá) e viaja junto da PRÓXIMA pergunta, para o agente
     endereçado; na rodada da mesa, quem lê é o Radar de Contexto e o resumo
     dele chega aos outros. */

  async function anexarPdf(arquivo) {
    if (!arquivo) return;
    if (!/\.pdf$/i.test(arquivo.name)) {
      alert('Só PDF por enquanto — os documentos da CVM são PDFs.');
      return;
    }
    const chip = el('chat-anexo');
    chip.hidden = false;
    chip.innerHTML = '<span class="spinner"></span> lendo ' + esc(arquivo.name) + '…';
    try {
      const resp = await fetch('/api/docs/extrair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/pdf' },
        body: arquivo
      });
      const dados = await resp.json();
      if (!resp.ok) throw new Error(dados.detail || 'falha na extração');
      state.anexo = { nome: arquivo.name, texto: dados.texto, truncado: dados.truncado };
      pintarAnexo();
    } catch (err) {
      state.anexo = null;
      chip.hidden = false;
      chip.innerHTML = '⚠ ' + esc(err.message);
      setTimeout(() => { if (!state.anexo) chip.hidden = true; }, 5000);
    }
  }

  function pintarAnexo() {
    const chip = el('chat-anexo');
    if (!chip) return;
    if (!state.anexo) { chip.hidden = true; chip.innerHTML = ''; return; }
    chip.hidden = false;
    chip.innerHTML = '';
    chip.appendChild(h('span', { class: 'nome' },
      '📎 ' + state.anexo.nome + (state.anexo.truncado ? ' (truncado)' : '')));
    chip.appendChild(h('span', { class: 'dica' },
      'vai junto da próxima pergunta, para quem você endereçar'));
    chip.appendChild(h('button', {
      class: 'btn ghost sm', title: 'Remover o anexo',
      onclick: () => { state.anexo = null; pintarAnexo(); }
    }, '✕'));
  }

  /* --------------------------------------------------------- análises salvas */
  /* A conversa vive na sessão e evapora ao fechar a aba. O 💾 tira uma foto
     dela — pergunta, falas da mesa, conclusão — e guarda no navegador
     (localStorage), com download em Markdown para levar para fora. Nada vai
     ao servidor: mesma regra das chaves. */

  function salvas() {
    try {
      const arr = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]');
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }

  function gravarSalvas(lista) {
    try { localStorage.setItem(SAVED_KEY, JSON.stringify(lista.slice(0, 40))); }
    catch (e) { alert('Sem espaço no navegador para salvar. Apague análises antigas.'); }
  }

  function salvarAnalise() {
    const msgs = carregar().filter((m) => !m.local);
    if (!msgs.length) { alert('Nada para salvar ainda — pergunte algo à mesa primeiro.'); return; }
    const primeira = (msgs.find((m) => m.role === 'user') || {}).content || 'conversa';
    const item = {
      id: Date.now(),
      quando: new Date().toISOString(),
      ticker: state.ticker || state.tela || null,
      titulo: primeira.slice(0, 80),
      msgs: msgs
    };
    gravarSalvas([item].concat(salvas()));
    // Salvar já entrega o arquivo: a análise desce em .md na hora, e a cópia
    // fica em 📚 para reabrir ou baixar de novo.
    baixarAnalise(item);
    const btn = el('chat-save');
    if (btn) {
      btn.textContent = '✓ salva';
      setTimeout(() => { btn.textContent = '💾'; }, 1600);
    }
  }

  function analiseEmMarkdown(item) {
    const nomes = loadAgentNames();
    const linhas = [`# Análise da mesa — ${item.ticker || 'geral'}`,
      `_${new Date(item.quando).toLocaleString('pt-BR')} · Gab's FinLab_`, ''];
    item.msgs.forEach((m) => {
      if (m.role === 'user') {
        linhas.push(`## Pergunta`, '', m.content, '');
      } else {
        const autor = m.autor || nomes[m.agente] || 'Mesa';
        linhas.push(`### ${m.icone || '🧠'} ${autor}${m.modelo ? ` · \`${m.modelo}\`` : ''}`,
          '', m.content, '');
      }
    });
    return linhas.join('\n');
  }

  function baixarAnalise(item) {
    const quando = item.quando.slice(0, 10);
    const nome = `analise-${(item.ticker || 'mesa').toLowerCase()}-${quando}.md`;
    const blob = new Blob([analiseEmMarkdown(item)], { type: 'text/markdown' });
    const a = h('a', { href: URL.createObjectURL(blob), download: nome });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  function abrirSalvas() {
    const corpo = el('chat-body');
    const lista = salvas();
    corpo.innerHTML = '';
    const topo = h('div', { class: 'chat-salvas-topo' }, [
      h('b', {}, `Análises salvas (${lista.length})`),
      h('span', { style: 'flex:1 1 auto' }),
      h('button', { class: 'btn ghost sm', onclick: pintarHistorico }, '← voltar')
    ]);
    corpo.appendChild(topo);
    if (!lista.length) {
      corpo.appendChild(h('div', { class: 'chat-vazio' },
        'Nenhuma análise salva. Depois de uma rodada da mesa, clique em 💾 para guardar.'));
      return;
    }
    lista.forEach((item) => {
      corpo.appendChild(h('div', { class: 'chat-salva' }, [
        h('div', { class: 'meta' }, [
          h('b', {}, item.ticker || 'geral'),
          h('span', {}, new Date(item.quando).toLocaleString('pt-BR')),
          h('span', { class: 'n' }, `${item.msgs.length} mensagens`)
        ]),
        h('div', { class: 'ttl' }, item.titulo),
        h('div', { class: 'acoes' }, [
          h('button', {
            class: 'btn ghost sm', title: 'Recarregar esta conversa no chat',
            onclick: () => { salvar(item.msgs); pintarHistorico(); }
          }, '↩ reabrir'),
          h('button', {
            class: 'btn ghost sm', title: 'Baixar como Markdown',
            onclick: () => baixarAnalise(item)
          }, '⬇ baixar .md'),
          h('button', {
            class: 'btn ghost sm', title: 'Excluir',
            onclick: () => { gravarSalvas(salvas().filter((s) => s.id !== item.id)); abrirSalvas(); }
          }, '🗑')
        ])
      ]));
    });
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
          class: 'btn ghost sm', id: 'chat-save', title: 'Salvar esta análise',
          onclick: salvarAnalise
        }, '💾'),
        h('button', {
          class: 'btn ghost sm', title: 'Análises salvas',
          onclick: abrirSalvas
        }, '📚'),
        h('button', {
          class: 'btn ghost sm', title: 'Limpar a conversa',
          onclick: () => { salvar([]); pintarHistorico(); }
        }, '🗑'),
        h('button', { class: 'btn ghost sm', title: 'Fechar', onclick: alternar }, '✕')
      ]),
      h('div', { class: 'chat-body', id: 'chat-body' }),
      h('div', { class: 'chat-foot' }, [
        h('div', { class: 'chat-anexo', id: 'chat-anexo', hidden: 'hidden' }),
        h('div', { class: 'chat-inputrow' }, [
          h('input', {
            type: 'file', id: 'chat-arquivo', accept: '.pdf,application/pdf',
            hidden: 'hidden',
            onchange: (ev) => { anexarPdf(ev.target.files[0]); ev.target.value = ''; }
          }),
          h('button', {
            class: 'btn ghost', id: 'chat-clip',
            title: 'Anexar um PDF para o agente ler (release, apresentação, relatório)',
            onclick: () => el('chat-arquivo').click()
          }, '📎'),
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
    carregarMesa();
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
    state.tela = o.tela || null;
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
