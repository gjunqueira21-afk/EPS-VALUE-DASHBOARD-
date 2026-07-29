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

    const modelWrap = h('div', { class: 'field' });
    const modelInput = h('input', {
      type: 'text', id: `slot-model-${idx}`, value: slot.model || '',
      placeholder: 'ex.: anthropic/claude-sonnet-4.5', list: `models-${idx}`
    });
    const datalist = h('datalist', { id: `models-${idx}` });

    function refreshModels() {
      const p = providers.find((x) => x.key === provSel.value);
      datalist.innerHTML = '';
      (p ? p.models : []).forEach((m) => datalist.appendChild(h('option', { value: m })));
      const link = el(`slot-doc-${idx}`);
      if (link && p) { link.href = p.docs; link.textContent = 'obter chave ↗'; }
    }
    provSel.addEventListener('change', refreshModels);

    modelWrap.appendChild(h('label', { for: `slot-model-${idx}` }, 'Modelo'));
    modelWrap.appendChild(modelInput);
    modelWrap.appendChild(datalist);

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
        modelWrap,
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
    setTimeout(refreshModels, 0);
    return card;
  }

  function collect() {
    return Array.from({ length: SLOT_COUNT }, (_, i) => ({
      id: i + 1,
      provider: el(`slot-prov-${i}`).value,
      model: el(`slot-model-${i}`).value.trim(),
      api_key: el(`slot-key-${i}`).value.trim(),
      label: el(`slot-label-${i}`).value.trim()
    }));
  }

  async function open(callback) {
    onSaved = callback || null;
    await ensureProviders();
    const slots = loadSlots();

    const body = h('div', {}, slots.map((s, i) => slotCard(s, i)));

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
