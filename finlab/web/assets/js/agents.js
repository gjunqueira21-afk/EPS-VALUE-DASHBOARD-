/* Mesa de IA: agentes especializados comentando a empresa a partir
   do mesmo contexto que está na tela. Cada agente pode usar um slot de LLM
   diferente; a chave nunca sai do navegador exceto na chamada ao proxy local. */
(function (global) {
  'use strict';

  const { fmt, api, el, h, esc, isNum, markdown, loadSlots, prefs } = global.FL;

  let cfg = null;                 // /api/config
  let ctx = { params: null, resumo: null };
  const saidas = {};              // agente -> texto
  const propostas = {};           // agente -> JSON de premissas

  async function ensureConfig() {
    if (cfg) return cfg;
    try { cfg = await api('/api/config'); } catch (e) { cfg = { agents: [], providers: [] }; }
    // A lista real de agentes é do backend: sem isto, um agente novo não ganha
    // cartão em ⚙ A mesa e cai calado no slot do primeiro.
    if (global.FL.setAgentOrder) global.FL.setAgentOrder((cfg.agents || []).map((a) => a.key));
    return cfg;
  }

  function slotFor(agentKey) {
    return global.FL.agentConfig(agentKey);
  }

  /** Qual modelo este agente usa — e se ele herdou de outro. A escolha em si
   *  passou a ser feita no cartão do agente, em ⚙ A mesa de IA. */
  function modeloDoAgente(agentKey) {
    const cfg = global.FL.agentConfig(agentKey);
    if (!cfg) {
      return h('span', { class: 'agent-modelo vazio', title: 'Nenhum agente configurado' },
        'sem modelo');
    }
    return h('span', {
      class: 'agent-modelo' + (cfg.herdado ? ' herdado' : ''),
      title: cfg.herdado
        ? 'Este agente não tem chave própria: usa a de ' + (cfg.label || cfg.model)
        : 'Modelo configurado para este agente'
    }, (cfg.herdado ? '↳ ' : '') + cfg.model);
  }

  /* ------------------------------------------------------------ execução */

  async function run(agentKey, state, card) {
    const slot = slotFor(agentKey);

    const out = card.querySelector('.agent-out');
    const btn = card.querySelector('button[data-run]');

    if (!slot) {
      out.innerHTML = '<div class="note bad">Nenhum agente configurado com chave e modelo. '
        + 'Abra <b>⚙ A mesa de IA</b> no topo da página.</div>';
      return;
    }

    btn.disabled = true;
    const rotuloOriginal = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> pensando…';
    out.innerHTML = '<div class="note">Consultando ' + esc(slot.model) + '…</div>';

    const pergunta = card.querySelector('textarea') ? card.querySelector('textarea').value : '';

    try {
      const resp = await api('/api/agents/run', {
        method: 'POST',
        body: JSON.stringify({
          agent: agentKey,
          ticker: state.ticker,
          slot: { provider: slot.provider, api_key: slot.api_key, model: slot.model },
          assumptions: ctx.params,
          resultado: ctx.resumo,
          radar: agentKey === 'contexto' ? '' : (saidas.contexto || ''),
          falas: cfg && (cfg.agents || []).some((a) => a.key === agentKey && a.le_a_mesa)
            ? saidas : undefined,
          pergunta
        })
      });
      saidas[agentKey] = resp.texto;
      out.innerHTML = markdown(resp.texto);
      out.appendChild(h('div', {
        class: 'note', style: 'margin-top:10px'
      }, `${resp.provedor} · ${resp.modelo}`));

      if (resp.proposta && resp.proposta.premissas) {
        propostas[agentKey] = resp.proposta;
        out.appendChild(botaoAplicar(resp.proposta, state));
      }
    } catch (err) {
      out.innerHTML = '';
      out.appendChild(h('div', { class: 'note bad' }, 'Falha: ' + err.message));
    } finally {
      btn.disabled = false;
      btn.textContent = rotuloOriginal;
    }
  }

  function botaoAplicar(proposta, state) {
    const p = proposta.premissas || {};
    const linhas = [];
    const rot = {
      rf: 'Rf', erp: 'ERP', beta: 'Beta', premio_extra: 'Prêmio extra',
      spread_credito: 'Spread de crédito', wd: 'Dívida/(D+E)', g_terminal: 'Perpetuidade'
    };
    Object.entries(rot).forEach(([k, label]) => {
      if (isNum(p[k])) {
        linhas.push(`${label}: ${k === 'beta' ? fmt.num(p[k], 2) : fmt.pct(p[k], 2)}`);
      }
    });
    if (Array.isArray(p.growth)) {
      linhas.push('Crescimento: ' + p.growth.map((g) => fmt.pct(g, 1)).join(' → '));
    }

    return h('div', {
      style: 'margin-top:12px;padding:12px;border:1px solid rgba(167,139,250,.4);'
        + 'border-radius:12px;background:rgba(167,139,250,.07)'
    }, [
      h('div', {
        style: 'font:700 10px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;'
          + 'color:#A78BFA;margin-bottom:8px'
      }, 'Premissas propostas' + (proposta.confianca ? ' · confiança ' + esc(proposta.confianca) : '')),
      h('div', { style: 'font:500 11.5px/1.9 var(--mono);color:var(--dim)' }, linhas.join(' · ')),
      h('button', {
        class: 'btn primary', style: 'margin-top:11px',
        onclick: () => aplicar(p, state)
      }, '⇩ Aplicar estas premissas no painel')
    ]);
  }

  function aplicar(p, state) {
    ['rf', 'erp', 'beta', 'premio_extra', 'spread_credito', 'wd', 'g_terminal'].forEach((k) => {
      if (isNum(p[k])) state.a[k] = p[k];
    });
    if (Array.isArray(p.growth) && p.growth.length) {
      state.a.growth = p.growth.slice(0, 5).map(Number).filter(isNum);
    }
    // Garante consistência: Gordon exige WACC > g.
    const w = global.FLEngine.wacc(state.a).wacc;
    if (state.a.g_terminal >= w - 0.005) state.a.g_terminal = Math.max(0, w - 0.015);

    global.dispatchEvent(new CustomEvent('finlab:assumptions-applied'));
  }

  /* --------------------------------------------------------------- render */

  async function render(state) {
    const host = document.querySelector('[data-panel="ia"]');
    if (!host) return;
    await ensureConfig();
    host.innerHTML = '';

    const prontos = loadSlots().filter((s) => s.api_key && s.model);

    host.appendChild(h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, [
        h('div', { class: 'ptitle' }, [h('b', {}, 'Mesa de análise'),
          ' · o Radar abre e os demais leem os mesmos números']),
        h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, [
          h('button', {
            class: 'btn ghost sm',
            onclick: () => global.FLSettings.open(() => render(state))
          }, '⚙ A mesa'),
          h('button', {
            class: 'btn primary sm', disabled: prontos.length ? null : 'disabled',
            onclick: (ev) => rodarTodos(state, ev.target)
          }, '▶ Rodar mesa completa')
        ])
      ]),
      h('div', {
        class: 'note',
        html: prontos.length
          ? `<b>${prontos.length}</b> agente(s) com chave própria; os demais herdam a do `
            + 'primeiro. Todos recebem o mesmo contexto da tela — fundamentos da CVM, '
            + 'múltiplos, macro do dia, suas premissas e o resultado do modelo. O <b>Radar de '
            + 'Contexto</b> é a exceção: ele roda primeiro, é o único que busca fora do painel, '
            + 'e o que levanta chega aos outros marcado como <b>não verificado</b>.'
          : 'Nenhum agente configurado ainda. Clique em <b>⚙ A mesa</b> e cadastre pelo menos uma '
            + 'chave (OpenRouter, OpenAI, Anthropic, Google, Groq ou DeepSeek).'
      })
    ]));

    (cfg.agents || []).forEach((agent) => {
      const out = h('div', { class: 'agent-out' }, saidas[agent.key] ? undefined
        : h('div', { class: 'note' }, prontos.length
          ? 'Clique em Rodar para receber a leitura deste agente.'
          : 'Configure a chave de um agente para habilitar a mesa.'));
      if (saidas[agent.key]) out.innerHTML = markdown(saidas[agent.key]);

      const card = h('section', { class: 'agent-card' }, [
        h('div', { class: 'hd' }, [
          h('span', { class: 'ico' }, agent.icon),
          h('div', {}, [
            // O nome que o usuário deu à mesa vale aqui também.
            h('div', { class: 'ttl' }, global.FL.agentName(agent.key) || agent.label),
            h('div', { class: 'dsc' }, agent.desc)
          ]),
          h('span', { class: 'sp' }),
          modeloDoAgente(agent.key),
          h('button', {
            class: 'btn sm', 'data-run': agent.key,
            onclick: (ev) => run(agent.key, state, ev.target.closest('.agent-card'))
          }, '▶ Rodar')
        ]),
        agent.key === 'equity' ? h('div', { style: 'margin-top:11px' }, [
          h('textarea', {
            placeholder: 'Pergunta adicional para este agente (opcional) — ex.: "compare a '
              + 'alavancagem com a média histórica da empresa"'
          })
        ]) : null,
        out
      ]);
      host.appendChild(card);
    });

    const f = (state.data && state.data.fundamentals) || {};
    const origem = f.bdr
      ? `demonstrações anuais do papel de origem via ${esc(f.fonte || 'Yahoo Finance')}, `
        + `em ${esc(f.currency || 'USD')}`
      : 'demonstrações anuais da CVM (com a defasagem natural)';
    // Banner de cobertura: a pergunta "até quando a mesa enxerga?" precisa de
    // resposta ANTES da leitura, não depois. Enquanto a nota dizia "sem acesso
    // a trimestral" mesmo depois de o ITR entrar, ela estava mentindo por
    // desatualização — o pior tipo de aviso.
    const ltm = (state.data && state.data.ltm) || {};
    const tri = ((state.data && state.data.trimestral) || {}).pontos || [];
    const reg = (state.data && state.data.regime) || {};
    const ate = ltm.fim ? fmt.date(ltm.fim)
      : (f.last_year ? 'o exercício de ' + f.last_year : 'data desconhecida');

    host.appendChild(h('div', {
      class: 'note warn',
      html: '<b>Até onde a mesa enxerga.</b> Contabilidade até <b>' + esc(ate) + '</b> — '
        + origem
        + (tri.length ? ', mais os trimestres do ITR já desacumulados' : '')
        + (reg.codigo
          ? `, e o regime <b>${esc(reg.codigo)} · ${esc(reg.rotulo)}</b> com as evidências datadas`
          : '')
        + ', preço, múltiplos e macro do dia.<br>'
        + 'Continuam <b>sem</b> guidance, transcrição de call, fato relevante e notícia. '
        + (reg.codigo
          ? 'A classificação de regime é só contábil, então eles não devem afirmar nada '
            + 'sobre intenção declarada da gestão. '
          : '')
        + 'Trate as respostas como leitura crítica dos números — nunca como recomendação.'
    }));
  }

  /**
   * A rodada inteira, em paralelo entre provedores e em fila dentro de cada um.
   *
   * Era `for await` puro: a espera da mesa somava as quatro chamadas, mesmo
   * quando cada agente usava um provedor diferente e não havia disputa
   * nenhuma. Agora a latência é a do provedor mais lento, não a soma.
   *
   * A fila por provedor continua existindo de propósito — quatro agentes na
   * mesma chave estouram rate limit, que era o motivo do sequencial original.
   * Quem usa uma chave só não fica mais lento que antes; quem espalhou entre
   * provedores ganha o paralelismo.
   */
  async function rodarTodos(state, btn) {
    let cards = Array.from(document.querySelectorAll('[data-panel="ia"] .agent-card'));
    btn.disabled = true;
    const rotulo = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> rodando…';

    const meta = (key) => (cfg.agents || []).find((a) => a.key === key) || {};
    const chaveDo = (c) => c.querySelector('button[data-run]').dataset.run;

    // A rodada acontece em ondas, e a ordem não é estética:
    //   antes  o Radar, porque o que ele levanta entra no contexto dos outros;
    //   0      o corpo da mesa, em paralelo — eles não dependem uns dos outros;
    //   1      o Cético, que precisa ter as falas para contestar;
    //   2      o Moderador, que precisa das falas E da contestação.
    const ondas = new Map();
    cards.forEach((card) => {
      const m = meta(chaveDo(card));
      const onda = m.abre_rodada ? -1 : (m.ordem || 0);
      if (!ondas.has(onda)) ondas.set(onda, []);
      ondas.get(onda).push(card);
    });

    for (const onda of Array.from(ondas.keys()).sort((x, y) => x - y)) {
      const desta = ondas.get(onda);
      const filas = new Map();
      desta.forEach((card) => {
        const key = chaveDo(card);
        const slot = slotFor(key);
        // Agrupamos por provedor+chave porque o rate limit é da credencial,
        // não do fornecedor em abstrato.
        const fila = slot ? `${slot.provider}:${slot.api_key}` : 'sem-slot';
        if (!filas.has(fila)) filas.set(fila, []);
        filas.get(fila).push({ key, card });
      });
      // allSettled: um provedor fora do ar não aborta a rodada dos outros.
      await Promise.allSettled(Array.from(filas.values()).map(async (fila) => {
        for (const { key, card } of fila) await run(key, state, card);
      }));
    }

    btn.disabled = false;
    btn.textContent = rotulo;
  }

  function updateAssumptions(state, params, resumo) {
    ctx.params = params;
    ctx.resumo = resumo;
  }

  global.FLAgents = { render, updateAssumptions };
})(window);
