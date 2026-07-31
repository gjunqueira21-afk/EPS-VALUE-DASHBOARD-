/* Modal de configuração dos 4 slots de LLM.
   As chaves ficam somente no localStorage deste navegador e são enviadas ao
   backend apenas no momento da chamada, que age como proxy para o provedor. */
(function (global) {
  'use strict';

  const { h, el, esc, loadSlots, saveSlots, SLOT_COUNT } = global.FL;

  let providers = [];
  let onSaved = null;

  async function ensureProviders() {
    if (providers.length) return providers;
    try {
      const cfg = await global.FL.api('/api/config');
      providers = cfg.providers || [];
    } catch (e) {
      providers = [];
    }
    return providers;
  }

  function slotCard(slot, idx) {
    const provSel = h('select', { id: `slot-prov-${idx}` },
      providers.map((p) => h('option', {
        value: p.key, selected: p.key === slot.provider ? 'selected' : null
      }, p.label))
    );

    // O modelo é um select alimentado pela API do provedor (os modelos que a
    // SUA chave pode usar), com escape para digitar um id manualmente.
    const modelSel = h('select', { id: `slot-model-${idx}` });
    const modelInput = h('input', {
      type: 'text', id: `slot-model-txt-${idx}`, value: slot.model || '',
      placeholder: 'id do modelo', hidden: 'hidden',
      style: 'margin-top:6px'
    });
    const statusModelo = h('div', {
      id: `slot-status-${idx}`,
      style: 'font:400 10px/1.5 var(--mono);color:var(--dim2);margin-top:5px'
    }, '');

    const btnBuscar = h('button', {
      class: 'btn ghost sm', type: 'button', style: 'margin-top:7px',
      onclick: () => carregarModelos(true)
    }, '↻ Buscar meus modelos');

    function preencher(lista, selecionado) {
      modelSel.innerHTML = '';
      // Sem escolha ainda, o navegador selecionaria o primeiro da lista e o
      // salvaria como se o usuário tivesse escolhido. Um vazio na frente evita.
      if (!selecionado) {
        modelSel.appendChild(h('option', { value: '', selected: 'selected' }, '— escolher —'));
      }
      lista.forEach((m) => modelSel.appendChild(h('option', {
        value: m, selected: m === selecionado ? 'selected' : null
      }, m)));
      modelSel.appendChild(h('option', {
        value: '__outro__', selected: (selecionado && !lista.includes(selecionado)) ? 'selected' : null
      }, '✎ outro (digitar)'));
      const manual = modelSel.value === '__outro__';
      modelInput.hidden = !manual;
      if (manual) modelInput.value = selecionado || '';
    }

    async function carregarModelos(forcar) {
      const p = providers.find((x) => x.key === provSel.value);
      const link = el(`slot-doc-${idx}`);
      if (link && p) { link.href = p.docs; link.textContent = 'obter chave ↗'; }

      const atual = modelSel.value === '__outro__'
        ? modelInput.value.trim()
        : (modelSel.value || slot.model || '');
      const chave = (el(`slot-key-${idx}`) || {}).value || '';

      preencher(p ? p.models : [], atual);
      if (!forcar && !chave) {
        statusModelo.textContent = 'sugestões — salve a chave e clique em buscar para ver os seus';
        return;
      }
      statusModelo.innerHTML = '<span class="spinner"></span> consultando o provedor…';
      try {
        const r = await global.FL.api('/api/llm/models', {
          method: 'POST',
          body: JSON.stringify({ provider: provSel.value, api_key: chave.trim() })
        });
        preencher(r.models || [], atual);
        statusModelo.textContent = r.aviso
          || `${(r.models || []).length} modelos disponíveis nesta chave`;
      } catch (err) {
        statusModelo.textContent = 'não foi possível listar: ' + err.message;
      }
    }

    modelSel.addEventListener('change', () => {
      modelInput.hidden = modelSel.value !== '__outro__';
      if (!modelInput.hidden) modelInput.focus();
    });
    provSel.addEventListener('change', () => carregarModelos(false));

    const card = h('div', { class: 'slot-card' }, [
      h('div', { class: 'hd' }, [
        h('span', { class: 'n' }, `Slot ${idx + 1}`),
        h('span', { class: 'sp', style: 'flex:1 1 auto' }),
        h('a', {
          id: `slot-doc-${idx}`, href: '#', target: '_blank', rel: 'noopener',
          style: 'font:600 10.5px ui-monospace,monospace'
        }, 'obter chave ↗')
      ]),
      h('div', { class: 'slot-grid' }, [
        h('div', { class: 'field' }, [h('label', {}, 'Provedor'), provSel]),
        h('div', { class: 'field' }, [
          h('label', { for: `slot-model-${idx}` }, 'Modelo'),
          modelSel, modelInput, statusModelo, btnBuscar
        ]),
        h('div', { class: 'field' }, [
          h('label', { for: `slot-key-${idx}` }, 'Chave de API'),
          h('input', {
            type: 'password', id: `slot-key-${idx}`, value: slot.api_key || '',
            placeholder: 'sk-...', autocomplete: 'off', spellcheck: 'false'
          })
        ])
      ]),
      h('div', { class: 'field', style: 'margin-top:9px' }, [
        h('label', { for: `slot-label-${idx}` }, 'Apelido (opcional)'),
        h('input', {
          type: 'text', id: `slot-label-${idx}`, value: slot.label || '',
          placeholder: `ex.: ${idx === 0 ? 'raciocínio pesado' : 'rápido e barato'}`
        })
      ])
    ]);
    // Chave já salva: busca os modelos reais assim que o modal abre.
    setTimeout(() => carregarModelos(!!(slot.api_key || '').trim()), 0);
    return card;
  }

  /* ------------------------------------------------------- nomes da mesa */

  /** Os quatro agentes já vêm batizados pela especialidade; aqui só se troca
   *  o nome. Campo vazio volta ao padrão. */
  function mesaCard() {
    const nomes = global.FL.loadAgentNames();
    const padroes = global.FL.AGENT_DEFAULTS;
    const icones = global.FL.AGENT_ICONS;
    const papeis = {
      equity: 'fundamentos, tese, riscos',
      macro: 'juros, inflação e câmbio nas premissas',
      gestor: 'veredito de posição e gatilhos',
      premissas: 'calibragem do modelo — Rf, beta, crescimento'
    };

    return h('div', { class: 'slot-card' }, [
      h('div', { class: 'hd' }, [
        h('span', { class: 'n' }, 'A mesa'),
        h('span', { class: 'sp', style: 'flex:1 1 auto' }),
        h('span', { style: 'font:400 10.5px var(--mono);color:var(--dim2)' },
          'como cada agente assina na conversa')
      ]),
      h('div', { class: 'mesa-grid' }, Object.keys(padroes).map((k) => h('div', { class: 'field' }, [
        h('label', { for: `agent-nome-${k}` }, `${icones[k]} ${papeis[k]}`),
        h('input', {
          type: 'text', id: `agent-nome-${k}`, value: nomes[k] === padroes[k] ? '' : nomes[k],
          placeholder: padroes[k], autocomplete: 'off'
        })
      ])))
    ]);
  }

  function collectNomes() {
    const out = {};
    Object.keys(global.FL.AGENT_DEFAULTS).forEach((k) => {
      const campo = el(`agent-nome-${k}`);
      out[k] = campo && campo.value.trim() ? campo.value.trim() : global.FL.AGENT_DEFAULTS[k];
    });
    return out;
  }

  function collect() {
    return Array.from({ length: SLOT_COUNT }, (_, i) => {
      const sel = el(`slot-model-${i}`);
      const manual = el(`slot-model-txt-${i}`);
      const model = (sel && sel.value === '__outro__')
        ? (manual ? manual.value.trim() : '')
        : ((sel && sel.value) || '').trim();
      return {
        id: i + 1,
        provider: el(`slot-prov-${i}`).value,
        model,
        api_key: el(`slot-key-${i}`).value.trim(),
        label: el(`slot-label-${i}`).value.trim()
      };
    });
  }

  async function open(callback) {
    onSaved = callback || null;
    await ensureProviders();
    const slots = loadSlots();

    const body = h('div', {}, [mesaCard()].concat(slots.map((s, i) => slotCard(s, i))));

    const bg = h('div', { class: 'modal-bg', id: 'llm-modal' });
    const modal = h('div', { class: 'modal wide' }, [
      h('div', { class: 'modal-head' }, [
        h('div', {}, [
          h('h2', {}, '⚙ Modelos de IA'),
          h('p', {
            class: 'sub',
            html: 'Configure até <b>4 slots</b> de LLM. Cada agente de análise do painel pode '
              + 'usar um slot diferente — por exemplo, um modelo forte para o gestor e um '
              + 'barato para o analista macro.<br>'
              + '<b>As chaves ficam só neste navegador</b> (localStorage) e são enviadas ao '
              + 'servidor local apenas no instante da chamada, que apenas repassa ao provedor. '
              + 'Nada é gravado em disco, em log ou no repositório.'
          })
        ]),
        h('button', { class: 'btn ghost sm', onclick: close }, '✕')
      ]),
      body,
      h('div', { style: 'display:flex;gap:9px;justify-content:flex-end;margin-top:16px;flex-wrap:wrap' }, [
        h('button', {
          class: 'btn ghost',
          onclick: () => {
            if (confirm('Apagar todas as chaves salvas neste navegador?')) {
              saveSlots(global.FL.defaultSlots());
              close();
              if (onSaved) onSaved();
            }
          }
        }, 'Limpar tudo'),
        h('button', { class: 'btn ghost', onclick: close }, 'Cancelar'),
        h('button', {
          class: 'btn primary',
          onclick: () => {
            saveSlots(collect());
            global.FL.saveAgentNames(collectNomes());
            if (global.FLChat) global.FLChat.atualizarRodape();
            close();
            if (onSaved) onSaved();
          }
        }, 'Salvar slots')
      ])
    ]);

    bg.appendChild(modal);
    bg.addEventListener('mousedown', (ev) => { if (ev.target === bg) close(); });
    document.body.appendChild(bg);
    document.addEventListener('keydown', escClose);
  }

  function escClose(ev) { if (ev.key === 'Escape') close(); }

  function close() {
    const m = el('llm-modal');
    if (m) m.remove();
    document.removeEventListener('keydown', escClose);
  }

  /** Rótulo curto de um slot, para os seletores dos agentes. */
  function slotLabel(slot) {
    if (!slot) return '—';
    const base = slot.label || slot.model || '(vazio)';
    return `Slot ${slot.id} · ${esc(base)}`;
  }

  global.FLSettings = { open, close, ensureProviders, slotLabel };
})(window);
