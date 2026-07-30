/* Mesa de IA: quatro agentes especializados comentando a empresa a partir
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
    return cfg;
  }

  function slotFor(agentKey) {
    const slots = loadSlots();
    const escolhido = prefs.get('agentSlot.' + agentKey, null);
    if (escolhido) {
      const s = slots.find((x) => x.id === escolhido);
      if (s && s.api_key && s.model) return s;
    }
    return slots.find((x) => x.api_key && x.model) || null;
  }

  function slotSelect(agentKey) {
    const slots = loadSlots();
    const atual = prefs.get('agentSlot.' + agentKey, null);
    const sel = h('select', {
      title: 'Slot de LLM usado por este agente',
      onchange: (ev) => prefs.set('agentSlot.' + agentKey, Number(ev.target.value) || null)
    }, slots.map((s) => h('option', {
      value: s.id,
      selected: s.id === atual ? 'selected' : null
    }, `Slot ${s.id}${s.label ? ' · ' + s.label : s.model ? ' · ' + s.model : ' · vazio'}`)));
    if (!atual) {
      const primeiro = slots.find((x) => x.api_key && x.model);
      if (primeiro) sel.value = primeiro.id;
    }
    return sel;
  }

  /* ------------------------------------------------------------ execução */

  async function run(agentKey, state, card) {
    const slot = (function () {
      const escolhido = Number(card.querySelector('select').value);
      const s = loadSlots().find((x) => x.id === escolhido);
      return (s && s.api_key && s.model) ? s : slotFor(agentKey);
    })();

    const out = card.querySelector('.agent-out');
    const btn = card.querySelector('button[data-run]');

    if (!slot) {
      out.innerHTML = '<div class="note bad">Nenhum slot de IA configurado com chave e modelo. '
        + 'Abra <b>⚙ Modelos de IA</b> no topo da página.</div>';
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
          ' · quatro papéis lendo os mesmos números da tela']),
        h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, [
          h('button', {
            class: 'btn ghost sm',
            onclick: () => global.FLSettings.open(() => render(state))
          }, '⚙ Slots'),
          h('button', {
            class: 'btn primary sm', disabled: prontos.length ? null : 'disabled',
            onclick: (ev) => rodarTodos(state, ev.target)
          }, '▶ Rodar mesa completa')
        ])
      ]),
      h('div', {
        class: 'note',
        html: prontos.length
          ? `<b>${prontos.length}</b> de 4 slots configurados. Cada agente recebe o mesmo contexto: `
            + 'fundamentos da CVM, múltiplos, macro do dia, suas premissas atuais e o resultado do '
            + 'modelo. Eles interpretam — não têm acesso a notícias nem a dados fora desta tela.'
          : 'Nenhum slot configurado ainda. Clique em <b>⚙ Slots</b> e cadastre pelo menos uma '
            + 'chave (OpenRouter, OpenAI, Anthropic, Google, Groq ou DeepSeek).'
      })
    ]));

    (cfg.agents || []).forEach((agent) => {
      const out = h('div', { class: 'agent-out' }, saidas[agent.key] ? undefined
        : h('div', { class: 'note' }, prontos.length
          ? 'Escolha o slot e clique em Rodar para receber a leitura deste agente.'
          : 'Configure um slot de IA para habilitar este agente.'));
      if (saidas[agent.key]) out.innerHTML = markdown(saidas[agent.key]);

      const card = h('section', { class: 'agent-card' }, [
        h('div', { class: 'hd' }, [
          h('span', { class: 'ico' }, agent.icon),
          h('div', {}, [
            h('div', { class: 'ttl' }, agent.label),
            h('div', { class: 'dsc' }, agent.desc)
          ]),
          h('span', { class: 'sp' }),
          slotSelect(agent.key),
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
    host.appendChild(h('div', {
      class: 'note warn',
      html: '<b>Limites do que você lê aqui.</b> Os agentes só enxergam o contexto desta tela: '
        + origem + ', preço, múltiplos e macro do dia. '
        + 'Não têm acesso a resultado trimestral, guidance, fato relevante nem notícia. '
        + 'Trate as respostas como leitura crítica dos números — nunca como recomendação.'
    }));
  }

  async function rodarTodos(state, btn) {
    const cards = Array.from(document.querySelectorAll('[data-panel="ia"] .agent-card'));
    btn.disabled = true;
    const rotulo = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> rodando…';
    for (const card of cards) {
      const key = card.querySelector('button[data-run]').dataset.run;
      await run(key, state, card);      // sequencial: evita estourar rate limit
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
