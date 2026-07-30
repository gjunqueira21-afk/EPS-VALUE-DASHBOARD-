/* Painel de valuation da empresa: premissas ao vivo, régua de sensibilidade,
   fundamentos, nota de saúde e comparação com pares. */
(function () {
  'use strict';

  const { fmt, api, el, qs, qsa, h, esc, isNum, signClass, prefs } = window.FL;
  const E = window.FLEngine;
  const C = window.FLChart;

  const state = {
    ticker: null,
    data: null,
    universe: null,
    a: null,        // premissas correntes
    base: null,     // premissas originais (para "restaurar")
    fcfMode: 'media3',
    fcfAjuste: 0,   // ajuste percentual sobre o FCL base
    tab: 'valuation'
  };

  /* ================================================================ helpers */

  function currentTicker() {
    const p = new URLSearchParams(window.location.search);
    return (p.get('ticker') || 'PETR4').toUpperCase();
  }

  function fcfBase() {
    const a = state.a;
    const raw = state.fcfMode === 'ultimo' ? a.fcf_ultimo : a.fcf_media3;
    if (!isNum(raw)) return null;
    return raw * (1 + state.fcfAjuste);
  }

  /** Premissas efetivas mandadas ao motor. */
  function params() {
    return Object.assign({}, state.a, { fcf_base: fcfBase() });
  }

  function result() { return E.dcf(params()); }

  /* ========================================================= cabeçalho */

  function renderStrip() {
    const d = state.data;
    const f = d.fundamentals, m = d.market, mu = d.multiples, sc = d.score;
    const perf = m.perf || {};

    const banda = 'sb-' + (!isNum(sc.total) ? 'none'
      : sc.total >= 70 ? 'good' : sc.total >= 55 ? 'ok' : sc.total >= 40 ? 'warn' : 'bad');

    el('companyStrip').innerHTML = '';
    el('companyStrip').appendChild(h('section', { class: 'panel tight' }, [
      h('div', {
        style: 'display:flex;align-items:center;gap:18px;flex-wrap:wrap'
      }, [
        h('div', {}, [
          h('div', { style: 'display:flex;align-items:baseline;gap:10px;flex-wrap:wrap' }, [
            h('span', { style: 'font:800 26px/1 var(--sans);letter-spacing:-.02em' }, f.ticker),
            h('span', { style: 'font:500 14px/1 var(--sans);color:var(--dim)' }, f.name),
            h('span', { class: 'score-badge ' + banda, style: 'margin-left:4px' }, [
              h('span', {}, isNum(sc.total) ? fmt.num(sc.total, 1) : '—'),
              h('span', { class: 'g' }, 'saúde')
            ])
          ]),
          h('div', {
            style: 'font:400 11px var(--mono);color:var(--dim2);margin-top:6px'
          }, f.bdr ? [
            'BDR · ', d.sector_label,
            ' · papel de origem: ', f.us_ticker || '—',
            f.last_year ? ' · exercício-base ' + f.last_year : '',
            f.currency ? ' · demonstrações em ' + f.currency : '',
            f.financial ? ' · balanço de instituição financeira' : ''
          ].join('') : [
            d.sector_label,
            ' · CVM ', f.cd_cvm || '—',
            ' · exercício-base ', String(f.last_year || '—'),
            f.financial ? ' · plano de contas de instituição financeira' : ''
          ].join(''))
        ]),
        h('div', { style: 'flex:1 1 auto' }),
        h('div', { style: 'display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end' }, [
          miniStat('Cotação', isNum(m.price) ? fmt.money(m.price) : '—',
            `${m.price_source || ''} · ${fmt.date(m.price_date)}`),
          miniStat('Dia', fmt.pctSigned(perf.day), 'último pregão', signClass(perf.day)),
          miniStat('12 meses', fmt.pctSigned(perf.m12), 'retorno', signClass(perf.m12)),
          miniStat('Valor de mercado', fmt.big(m.market_cap, 1), m.market_cap_source || '—'),
          miniStat('P/L', fmt.mult(mu.pl), 'sobre o exercício-base'),
          miniStat('Dív.Líq/EBITDA', f.financial ? 'n/a' : fmt.mult(mu.nd_ebitda, 2), 'alavancagem')
        ])
      ])
    ]));
  }

  function miniStat(label, value, sub, cls) {
    return h('div', {}, [
      h('div', {
        style: 'font:700 9px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--dim2)'
      }, label),
      h('div', { class: cls || '', style: 'font:700 17px/1.2 var(--mono);margin-top:3px' }, value),
      h('div', { style: 'font:400 9.5px/1.4 var(--mono);color:var(--dim2);margin-top:2px' }, sub || '')
    ]);
  }

  /* ============================================================ avisos */

  function renderAlerts() {
    const zone = el('alertZone');
    zone.innerHTML = '';
    const a = state.a;
    const r = result();

    if (!a.aplicavel && a.motivo_nao_aplicavel) {
      const temDados = (state.data.fundamentals.years || []).length > 0;
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>DCF indisponível para esta empresa.</b> ' + esc(a.motivo_nao_aplicavel)
          + (temDados ? ' As abas de fundamentos, nota de saúde e múltiplos continuam completas.'
            : ' A cotação e a performance abaixo continuam funcionando.')
      }));
      return;
    }
    if (r.alertas.includes('WACC_MENOR_QUE_G')) {
      zone.appendChild(h('div', {
        class: 'callout bad',
        html: '<b>Premissas inconsistentes:</b> o crescimento na perpetuidade ('
          + fmt.pct(a.g_terminal) + ') ficou maior ou igual ao WACC (' + fmt.pct(r.wacc)
          + '). A fórmula de Gordon deixa de valer — reduza a perpetuidade ou aumente o custo de capital.'
      }));
    }
    if (r.alertas.includes('PERPETUIDADE_ACIMA_75PCT')) {
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>' + fmt.pct(r.peso_perpetuidade, 0) + ' do valor vem da perpetuidade.</b> '
          + 'O resultado é muito sensível a premissas de longuíssimo prazo — trate o preço justo '
          + 'como faixa, não como número.'
      }));
    }
    const base = fcfBase();
    if (isNum(base) && base <= 0) {
      const holding = /holding|participa/i.test(state.data.fundamentals.denom || '');
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>Fluxo de caixa livre base negativo (' + esc(fmt.big(base, 2)) + ').</b> '
          + 'Um DCF sobre fluxo negativo devolve preço justo negativo por construção — o número '
          + 'abaixo é aritmética, não avaliação. '
          + (holding
            ? 'Esta empresa é uma holding: o caixa que importa são os dividendos das '
              + 'investidas, não o FCL consolidado do DFC. Avalie pela soma das partes, '
              + 'pelo P/VP e pelo desconto de holding.'
            : 'Troque a base para o outro exercício, normalize o FCL no slider ao lado, ou '
              + 'use o EPV e os múltiplos como referência.')
      }));
    } else if (isNum(state.a.fcl_sobre_ebitda) && state.a.fcl_sobre_ebitda > 1.2
               && state.fcfAjuste === 0) {
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>FCL base acima do EBITDA ('
          + esc(fmt.mult(state.a.fcl_sobre_ebitda, 2)) + ').</b> Um fluxo de caixa livre maior '
          + 'que o EBITDA quase sempre vem de <b>capital de giro</b> — na prática, alongamento '
          + 'de prazo com fornecedores — e não da operação. Projetar isso por cinco anos '
          + 'extrapola algo que não se repete. Use o slider <b>Normalizar o FCL base</b> para '
          + 'trazê-lo para perto do EBITDA, ou leia o valuation pelos múltiplos.'
      }));
    } else if (r.alertas.includes('EQUITY_NEGATIVO')) {
      zone.appendChild(h('div', {
        class: 'callout bad',
        html: '<b>Equity value negativo.</b> Com estas premissas, a dívida líquida de '
          + esc(fmt.big(state.a.divida_liquida, 2)) + ' supera o valor da operação — o modelo '
          + 'diz que não sobra valor para o acionista. Em empresa muito alavancada esse '
          + 'resultado é extremamente sensível ao crescimento e ao WACC: veja a matriz de '
          + 'sensibilidade antes de concluir qualquer coisa.'
      }));
    } else if (r.alertas.includes('FLUXO_NEGATIVO')) {
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>Algum ano projetado ficou com fluxo negativo.</b> Confira as taxas de '
          + 'crescimento: uma retração forte no início derruba toda a projeção.'
      }));
    }
  }

  /* ============================================================== KPIs */

  function renderKpis() {
    const r = result();
    const e = E.epv(params());
    const gi = E.crescimentoImplicito(params());
    const box = el('kpis');
    box.innerHTML = '';

    const upCls = !isNum(r.upside) ? '' : r.upside > 0.30 ? 'good' : r.upside > 0 ? 'info'
      : r.upside > -0.20 ? 'warn' : 'bad';

    const base = fcfBase();
    const fluxoRuim = isNum(base) && base <= 0;

    const cards = [
      [fluxoRuim ? 'bad' : 'info', 'Preço justo · DCF',
        isNum(r.preco_justo) ? fmt.money(r.preco_justo) : '—',
        fluxoRuim ? 'sem significado: o FCL base é negativo'
          : isNum(state.a.preco) ? 'preço de tela ' + fmt.money(state.a.preco) : 'sem cotação'],
      [upCls, 'Upside', fmt.pctSigned(r.upside),
        isNum(r.upside) ? (r.upside > 0 ? 'ação abaixo do modelo' : 'ação acima do modelo') : '—'],
      ['', 'WACC', fmt.pct(r.wacc, 2),
        `Ke ${fmt.pct(r.ke, 1)} · Kd líq. ${fmt.pct(r.kdLiquido, 1)} · D/(D+E) ${fmt.pct(r.wd, 0)}`],
      ['', 'EPV por ação', isNum(e.por_acao) ? fmt.money(e.por_acao) : '—',
        'poder de lucro atual, sem crescimento'],
      ['', 'Crescimento implícito', fmt.pct(gi, 1),
        !isNum(gi) ? 'fora da faixa testável (−35% a +80%)'
          : gi > 0.25 ? 'o preço embute crescimento agressivo — confira o EPV e os múltiplos'
            : gi < 0 ? 'o preço embute encolhimento do fluxo'
              : 'o que o preço de hoje embute'],
      ['', 'Peso da perpetuidade', fmt.pct(r.peso_perpetuidade, 0),
        'quanto do valor está além do horizonte']
    ];

    cards.forEach(([cls, l, v, s]) => {
      box.appendChild(h('div', { class: 'kpi ' + cls }, [
        h('div', { class: 'l' }, l),
        h('div', { class: 'v' }, v),
        h('div', { class: 's' }, s)
      ]));
    });
  }

  /* ============================================================= régua */

  const REGUA_MIN = -0.15;
  const REGUA_MAX = 0.25;

  function renderRegua() {
    const a = params();
    const preco = a.preco;
    const pts = E.curva(a, 'growth', REGUA_MIN, REGUA_MAX, 90);
    const gi = E.crescimentoImplicito(a);
    const gAtual = E.growthSeries(a.growth, a.anos)[0];

    const zonas = [];
    const marcadores = [];

    if (isNum(preco)) {
      // Fronteiras: crescimento onde o upside cruza -20%, 0% e +30%.
      const alvo = (mult) => E.bisect((g) => {
        const r = E.dcf(a, { growth: [g] });
        return isNum(r.preco_justo) ? r.preco_justo - preco * mult : NaN;
      }, REGUA_MIN, REGUA_MAX, 70);

      const g0 = alvo(1), g30 = alvo(1.30), gm20 = alvo(0.80);
      const lo = REGUA_MIN, hi = REGUA_MAX;
      const b1 = isNum(gm20) ? gm20 : lo;
      const b2 = isNum(g0) ? g0 : b1;
      const b3 = isNum(g30) ? g30 : hi;

      zonas.push({ from: lo, to: b1, color: 'rgba(248,113,113,.11)' });
      zonas.push({ from: b1, to: b2, color: 'rgba(245,184,65,.10)' });
      zonas.push({ from: b2, to: b3, color: 'rgba(103,232,249,.09)' });
      zonas.push({ from: b3, to: hi, color: 'rgba(52,211,153,.11)' });

      if (isNum(g0)) marcadores.push({ x: g0, color: '#67E8F9', label: 'preço justo = tela ' + fmt.pct(g0, 1) });
      if (isNum(g30)) marcadores.push({ x: g30, color: '#34D399', label: '+30% ' + fmt.pct(g30, 1) });
      if (isNum(gm20)) marcadores.push({ x: gm20, color: '#F87171', label: '-20% ' + fmt.pct(gm20, 1) });
    }

    const rAtual = E.dcf(a, { growth: [gAtual] });

    // Escala vertical: a região que importa é a vizinhança do preço de tela.
    // Sem teto, o trecho de crescimento alto achata tudo; com teto fixo, uma
    // empresa cujo valor justo é muito baixo vira uma linha colada no zero.
    // A curva pode ser inteiramente negativa (dívida líquida acima do EV),
    // então o piso acompanha o mínimo em vez de ser fixado em zero.
    const validos = pts.map((p) => p.y).filter(isNum);
    const maxCurva = validos.length ? Math.max.apply(null, validos) : 0;
    const minCurva = validos.length ? Math.min.apply(null, validos) : 0;
    // O teto precisa garantir duas coisas: a linha do preço sempre visível e
    // o ponto do cenário atual dentro da área. Fora isso, corta o exagero.
    let yTeto;
    if (isNum(preco)) {
      const alvo = Math.max(preco * 3,
        isNum(rAtual.preco_justo) ? rAtual.preco_justo * 1.15 : 0);
      yTeto = Math.max(preco * 1.15, Math.min(maxCurva * 1.08, alvo));
    } else {
      yTeto = Math.max(maxCurva * 1.08, 0);
    }
    const yPiso = Math.min(0, minCurva * 1.08);

    C.line(el('chartRegua'), {
      height: 290,
      xMin: REGUA_MIN, xMax: REGUA_MAX,
      yMax: yTeto,
      yMin: yPiso,
      series: [{
        name: 'Preço justo', points: pts, width: 2.6,
        colorAt: (x, y) => {
          if (!isNum(preco)) return '#67E8F9';
          const up = y / preco - 1;
          return up > 0.30 ? '#34D399' : up > 0 ? '#67E8F9' : up > -0.20 ? '#F5B841' : '#F87171';
        }
      }].concat(isNum(preco) ? [{
        name: 'Preço de tela',
        points: [{ x: REGUA_MIN, y: preco }, { x: REGUA_MAX, y: preco }],
        color: 'rgba(230,236,245,.45)', width: 1.3, dash: '5 5'
      }] : []),
      dots: isNum(rAtual.preco_justo) ? [{ x: gAtual, y: rAtual.preco_justo, color: '#F5B841' }] : [],
      zones: zonas,
      markers: marcadores,
      xFormat: (v) => fmt.num(v * 100, 0) + '%',
      yFormat: (v) => 'R$ ' + fmt.num(v, 0),
      tipFormat: (p) => {
        const up = isNum(preco) && isNum(p.y) ? p.y / preco - 1 : null;
        return `<span class="k">crescimento</span> ${fmt.pct(p.x, 1)}<br>`
          + `<span class="k">preço justo</span> ${isNum(p.y) ? fmt.money(p.y) : '—'}`
          + (isNum(up) ? `<br><span class="k">upside</span> ${fmt.pctSigned(up)}` : '');
      }
    });

    el('heroVal').textContent = fmt.pct(gAtual, 1);
    el('heroGrowth').value = gAtual;
    el('heroHint').textContent = state.a.growth.length > 1 && !state.uniform
      ? 'move os 5 anos em bloco, preservando o formato da curva'
      : 'taxa aplicada aos anos explícitos da projeção';

    const marks = el('heroMarks');
    marks.innerHTML = '';
    const add = (label, value, color) => marks.appendChild(h('span', {}, [
      label + ' ',
      h('b', { style: 'color:' + color + ';font-weight:700' }, value)
    ]));
    add('crescimento implícito no preço', fmt.pct(gi, 1), '#F5B841');
    add('WACC atual', fmt.pct(rAtual.wacc, 2), '#67E8F9');
    add('WACC que zera o upside', fmt.pct(E.waccBreakeven(a), 2), '#A78BFA');
    add('perpetuidade', fmt.pct(a.g_terminal, 1), '#E6ECF5');
  }

  /* =========================================================== cenários */

  const CENARIOS = [
    ['base', '↺ Base do painel'],
    ['otimista', 'Otimista'],
    ['pessimista', 'Pessimista'],
    ['inflacao', 'Só inflação'],
    ['sem_crescimento', 'Sem crescimento'],
    ['implicito', 'Preço atual (reverso)']
  ];

  function renderScenarios() {
    const row = el('scenarioRow');
    row.innerHTML = '';
    row.appendChild(h('span', {
      style: 'font:600 10px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;'
        + 'color:var(--dim2);align-self:center;margin-right:4px'
    }, 'Cenários'));

    CENARIOS.forEach(([key, label]) => {
      row.appendChild(h('button', {
        class: 'chip',
        onclick: () => {
          if (key === 'base') {
            state.a = JSON.parse(JSON.stringify(state.base));
            state.fcfMode = state.base.fcf_modo;
            state.fcfAjuste = 0;
          } else {
            state.a = E.cenario(params(), key);
          }
          rebuildControls();
          renderAll();
        }
      }, label));
    });
  }

  /* =========================================================== controles */

  const GRUPOS = [
    {
      titulo: 'Custo de capital', aberto: true, itens: [
        { k: 'rf', l: 'Taxa livre de risco', min: 0.04, max: 0.25, step: 0.0005, f: 'pct2', hint: 'juro nominal brasileiro; já embute o risco soberano, por isso não somamos prêmio-país' },
        { k: 'erp', l: 'Prêmio de risco de mercado', min: 0.02, max: 0.12, step: 0.0005, f: 'pct2', hint: 'prêmio de ações sobre o livre de risco' },
        { k: 'beta', l: 'Beta', min: 0.3, max: 2.5, step: 0.01, f: 'num2', hint: 'sensibilidade ao mercado' },
        { k: 'premio_extra', l: 'Prêmio adicional', min: -0.03, max: 0.12, step: 0.0025, f: 'pct2', hint: 'risco de tamanho, governança ou execução' },
        { k: 'spread_credito', l: 'Spread de crédito sobre o CDI', min: 0, max: 0.09, step: 0.0025, f: 'pct2' },
        { k: 'wd', l: 'Dívida / (dívida + equity)', min: 0, max: 0.80, step: 0.01, f: 'pct0' },
        { k: 'tax', l: 'Alíquota efetiva', min: 0, max: 0.40, step: 0.005, f: 'pct1' }
      ]
    },
    {
      titulo: 'Crescimento do FCL', aberto: true, itens: [
        { k: 'g0', l: 'Ano 1', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
        { k: 'g1', l: 'Ano 2', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
        { k: 'g2', l: 'Ano 3', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
        { k: 'g3', l: 'Ano 4', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
        { k: 'g4', l: 'Ano 5', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
        { k: 'g_terminal', l: 'Perpetuidade (g)', min: 0, max: 0.09, step: 0.0025, f: 'pct2', hint: 'no longo prazo, dificilmente supera a inflação + PIB' }
      ]
    }
  ];

  const FMT = {
    pct2: (v) => fmt.pct(v, 2), pct1: (v) => fmt.pct(v, 1), pct0: (v) => fmt.pct(v, 0),
    num2: (v) => fmt.num(v, 2)
  };

  const refs = {};

  function getVal(key) {
    if (key.startsWith('g') && /^g[0-4]$/.test(key)) {
      return E.growthSeries(state.a.growth, 5)[Number(key.slice(1))];
    }
    return state.a[key];
  }

  function setVal(key, value) {
    if (/^g[0-4]$/.test(key)) {
      const g = E.growthSeries(state.a.growth, 5);
      g[Number(key.slice(1))] = value;
      state.a.growth = g;
    } else {
      state.a[key] = value;
    }
  }

  /** Botões de âncora para a taxa livre de risco. */
  function ancoraRf() {
    const op = state.a.rf_opcoes || {};
    const chaves = Object.keys(op);
    if (!chaves.length) return h('div');

    const box = h('div', { style: 'padding:8px 0 4px' });
    box.appendChild(h('div', {
      style: 'font:600 9.5px/1.4 var(--mono);letter-spacing:.12em;text-transform:uppercase;'
        + 'color:var(--dim2);margin-bottom:7px'
    }, 'Âncora do juro livre de risco'));

    const linha = h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' });
    chaves.forEach((k) => {
      const o = op[k];
      const ativo = Math.abs(state.a.rf - o.valor) < 1e-6;
      linha.appendChild(h('button', {
        class: 'chip' + (ativo ? ' on' : ''), title: o.nota,
        onclick: () => {
          state.a.rf = o.valor;
          state.a.rf_modo = k;
          rebuildControls();
          renderAll();
        }
      }, `${o.label} · ${fmt.pct(o.valor, 2)}`));
    });
    box.appendChild(linha);
    box.appendChild(h('div', {
      class: 'note', style: 'margin-top:8px',
      html: 'Um DCF com perpetuidade precisa de juro <b>longo</b>: a Selic à vista é cíclica e '
        + 'distorce o valor no pico ou no fundo do ciclo. O padrão do painel é o prefixado de '
        + '~10 anos da ANBIMA.'
    }));
    return box;
  }

  function rebuildControls() {
    const root = el('controls');
    root.innerHTML = '';
    Object.keys(refs).forEach((k) => delete refs[k]);

    // Fluxo base -------------------------------------------------------
    const fcfBox = h('div', { class: 'ctrl-body' });
    const modos = [['media3', 'Média 3 anos'], ['ultimo', 'Último exercício']];
    const chips = h('div', { style: 'display:flex;gap:6px;margin:8px 0 4px;flex-wrap:wrap' },
      modos.map(([key, label]) => {
        const disponivel = isNum(key === 'ultimo' ? state.a.fcf_ultimo : state.a.fcf_media3);
        return h('button', {
          class: 'chip' + (state.fcfMode === key ? ' on' : ''),
          disabled: disponivel ? null : 'disabled',
          onclick: () => { state.fcfMode = key; rebuildControls(); renderAll(); }
        }, label);
      })
    );
    fcfBox.appendChild(chips);
    fcfBox.appendChild(h('div', {
      style: 'font:700 18px var(--mono);color:var(--brand);margin:6px 0 2px'
    }, fmt.big(fcfBase(), 2)));
    fcfBox.appendChild(h('div', {
      class: 'note', style: 'margin-top:4px',
      html: 'FCL = caixa das operações − capex, direto do DFC da CVM.<br>'
        + 'Último: <b>' + esc(fmt.big(state.a.fcf_ultimo, 2)) + '</b> · '
        + 'Média 3a: <b>' + esc(fmt.big(state.a.fcf_media3, 2)) + '</b>'
    }));

    const ajuste = h('input', {
      type: 'range', min: -0.5, max: 0.5, step: 0.01, value: state.fcfAjuste,
      'aria-label': 'Ajuste sobre o FCL base'
    });
    const ajusteVal = h('span', { class: 'cv' }, fmt.pctSigned(state.fcfAjuste, 0));
    ajuste.addEventListener('input', () => {
      state.fcfAjuste = parseFloat(ajuste.value);
      ajusteVal.textContent = fmt.pctSigned(state.fcfAjuste, 0);
      ajusteVal.className = 'cv' + (state.fcfAjuste !== 0 ? ' edited' : '');
      schedule();
    });
    fcfBox.appendChild(h('div', { class: 'ctrl' }, [
      h('div', { class: 'row' }, [
        h('label', {}, ['Normalizar o FCL base', h('small', {}, 'ajuste manual sobre a base escolhida')]),
        ajusteVal
      ]),
      ajuste
    ]));

    root.appendChild(h('details', { class: 'ctrl-group', open: 'open' }, [
      h('summary', {}, 'Fluxo de caixa base'), fcfBox
    ]));

    // Demais grupos ----------------------------------------------------
    GRUPOS.forEach((grupo) => {
      const body = h('div', { class: 'ctrl-body' });

      if (grupo.titulo === 'Custo de capital') body.appendChild(ancoraRf());

      grupo.itens.forEach((item) => {
        const valor = getVal(item.k);
        const label = h('label', { for: 'in-' + item.k }, [
          item.l, item.hint ? h('small', {}, item.hint) : null
        ]);
        const cv = h('span', { class: 'cv' }, FMT[item.f](valor));
        const range = h('input', {
          type: 'range', id: 'in-' + item.k, min: item.min, max: item.max,
          step: item.step, value: isNum(valor) ? valor : item.min,
          'aria-label': item.l
        });
        range.addEventListener('input', () => {
          const v = parseFloat(range.value);
          setVal(item.k, v);
          cv.textContent = FMT[item.f](v);
          cv.className = 'cv edited';
          schedule();
        });
        refs[item.k] = { range, cv, fmt: FMT[item.f] };
        body.appendChild(h('div', { class: 'ctrl' }, [
          h('div', { class: 'row' }, [label, cv]), range
        ]));
      });
      root.appendChild(h('details', {
        class: 'ctrl-group', open: grupo.aberto ? 'open' : null
      }, [h('summary', {}, grupo.titulo), body]));
    });

    // Diagnóstico do custo de capital -----------------------------------
    root.appendChild(h('div', { class: 'panel tight', id: 'waccBox' }));
  }

  function syncControls() {
    Object.entries(refs).forEach(([key, ref]) => {
      const v = getVal(key);
      if (isNum(v) && parseFloat(ref.range.value) !== v) ref.range.value = v;
      ref.cv.textContent = ref.fmt(v);
    });
    const box = el('waccBox');
    if (!box) return;
    const r = result();
    box.innerHTML = '';
    box.appendChild(h('div', { class: 'ptitle', style: 'margin-bottom:8px' },
      [h('b', {}, 'Composição do custo de capital')]));
    const linha = (l, v, cor) => h('div', {
      style: 'display:flex;justify-content:space-between;gap:10px;font:500 11.5px/2 var(--mono)'
    }, [
      h('span', { style: 'color:var(--dim)' }, l),
      h('span', { style: 'color:' + (cor || 'var(--paper)') + ';font-weight:700' }, v)
    ]);
    box.appendChild(linha('Ke = Rf + β×ERP + extra', fmt.pct(r.ke, 2), '#67E8F9'));
    box.appendChild(linha('Kd bruto (CDI + spread)', fmt.pct(r.kd, 2)));
    box.appendChild(linha('Kd depois de imposto', fmt.pct(r.kdLiquido, 2)));
    box.appendChild(linha('Peso equity / dívida',
      `${fmt.pct(r.we, 0)} / ${fmt.pct(r.wd, 0)}`));
    box.appendChild(h('div', { style: 'border-top:1px dashed var(--line);margin:7px 0 4px' }));
    box.appendChild(linha('WACC', fmt.pct(r.wacc, 2), '#A78BFA'));
    box.appendChild(h('div', {
      class: 'note', style: 'margin-top:8px',
      html: 'Beta <b>' + esc(state.a.beta_source || '—') + '</b> · estrutura de capital '
        + esc(state.a.wd_source || '—') + '.'
    }));
  }

  /* ====================================================== aba valuation */

  function renderValuation() {
    const host = qs('[data-panel="valuation"]');
    const a = params();
    const r = result();
    host.innerHTML = '';

    if (!isNum(r.ev)) {
      host.appendChild(h('div', { class: 'callout' },
        'Sem projeção: o modelo precisa de FCL base e de um WACC maior que a perpetuidade.'));
      return;
    }

    // Projeção -----------------------------------------------------------
    const anos = r.anos;
    const anoBase = state.data.fundamentals.last_year || new Date().getFullYear();
    const labels = Array.from({ length: anos }, (_, i) => String(anoBase + i + 1));
    const g = E.growthSeries(a.growth, anos);

    const proj = h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, [
        h('div', { class: 'ptitle' }, [h('b', {}, 'Projeção de fluxo de caixa livre'),
          ' · valores nominais e valor presente']),
        h('div', { class: 'psub' }, `desconto a ${fmt.pct(r.wacc, 2)} ao ano`)
      ]),
      h('div', { class: 'chartbox', id: 'chartProj', style: 'height:250px' })
    ]);
    host.appendChild(proj);

    C.bars(el('chartProj'), {
      height: 250,
      labels,
      series: [
        { name: 'FCL projetado', color: '#67E8F9', values: r.fluxos },
        { name: 'Valor presente', color: '#A78BFA', values: r.vp }
      ],
      yFormat: (v) => fmt.bigShort(v, 0)
    });

    // Tabela da projeção --------------------------------------------------
    const linhas = labels.map((ano, i) => h('tr', {}, [
      h('td', { class: 'left' }, ano),
      h('td', { class: 'num acc' }, fmt.pctSigned(g[i], 1)),
      h('td', { class: 'num' }, fmt.big(r.fluxos[i], 2)),
      h('td', { class: 'num' }, fmt.mult(Math.pow(1 + r.wacc, i + 1), 3).replace('x', '')),
      h('td', { class: 'num' }, fmt.big(r.vp[i], 2))
    ]));
    linhas.push(h('tr', { style: 'border-top:1px solid var(--line2)' }, [
      h('td', { class: 'left', style: 'font-weight:700' }, 'Perpetuidade'),
      h('td', { class: 'num acc' }, fmt.pct(a.g_terminal, 1)),
      h('td', { class: 'num' }, fmt.big(r.valor_terminal, 2)),
      h('td', { class: 'num' }, fmt.num(Math.pow(1 + r.wacc, anos), 3)),
      h('td', { class: 'num' }, fmt.big(r.vp_terminal, 2))
    ]));

    host.appendChild(h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, h('div', { class: 'ptitle' },
        [h('b', {}, 'Da projeção ao preço justo')])),
      h('div', { class: 'table-wrap' }, h('table', {}, [
        h('thead', {}, h('tr', {}, [
          h('th', { class: 'left' }, 'Ano'), h('th', {}, 'Crescimento'),
          h('th', {}, 'FCL'), h('th', {}, 'Fator de desconto'), h('th', {}, 'Valor presente')
        ])),
        h('tbody', {}, linhas)
      ])),
      pontesEV(r, a)
    ]));

    // Matriz de sensibilidade ---------------------------------------------
    // Grades centradas no cenário atual: a célula do meio é exatamente o
    // upside mostrado nos KPIs, e as vizinhas mostram a vizinhança da decisão.
    const extras = [-0.03, -0.015, 0, 0.015, 0.03];
    const gAtualT = a.g_terminal;
    const terminais = [-0.02, -0.01, 0, 0.01, 0.02]
      .map((d) => Math.round((gAtualT + d) * 10000) / 10000)
      .filter((gt) => gt >= 0 && gt < r.wacc - 0.005);
    const cells = E.matriz(a, extras, terminais);

    const matrizPanel = h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, [
        h('div', { class: 'ptitle' }, [h('b', {}, 'Matriz de sensibilidade'),
          ' · upside conforme custo de capital e perpetuidade']),
        h('div', { class: 'psub' }, 'linha = ajuste no WACC · coluna = g na perpetuidade')
      ]),
      h('div', { class: 'table-wrap', id: 'matrizBox' })
    ]);
    host.appendChild(matrizPanel);

    C.heat(el('matrizBox'), {
      rows: extras, cols: terminais,
      corner: 'WACC',
      rowLabel: (v) => (v === 0 ? 'atual ' : (v > 0 ? '+' : '')) + fmt.pct(v, 1),
      colLabel: (v) => 'g ' + fmt.pct(v, 1),
      value: (rw, cl) => cells[`${rw}|${cl}`],
      format: (v) => fmt.pctSigned(v, 0),
      highlight: { row: 0, col: gAtualT }
    });

    host.appendChild(h('div', {
      class: 'note',
      html: 'Cada célula recalcula o DCF inteiro. A leitura útil é a <b>faixa</b>: se o upside '
        + 'muda de sinal dentro da matriz, o preço justo depende mais da premissa do que do negócio.'
    }));
  }

  function pontesEV(r, a) {
    const dl = isNum(a.divida_liquida) ? a.divida_liquida : 0;
    const box = h('div', { style: 'margin-top:14px' });
    box.appendChild(h('div', {
      class: 'ptitle', style: 'margin-bottom:8px'
    }, [h('b', {}, 'Ponte até o equity')]));

    const linha = (l, v, cor) => h('div', {
      style: 'display:flex;justify-content:space-between;gap:12px;font:500 12px/2 var(--mono);'
        + 'border-bottom:1px dashed rgba(126,150,190,.12)'
    }, [
      h('span', { style: 'color:var(--dim)' }, l),
      h('span', { style: 'color:' + (cor || 'var(--paper)') + ';font-weight:700' }, v)
    ]);

    box.appendChild(linha('VP dos fluxos explícitos', fmt.big(r.soma_vp, 2)));
    box.appendChild(linha('VP da perpetuidade', fmt.big(r.vp_terminal, 2)));
    box.appendChild(linha('= Enterprise Value', fmt.big(r.ev, 2), '#67E8F9'));
    box.appendChild(linha('− Dívida líquida', fmt.big(-dl, 2), dl > 0 ? '#F87171' : '#34D399'));
    box.appendChild(linha('= Equity value', fmt.big(r.equity_value, 2), '#A78BFA'));
    box.appendChild(linha(
      a.bdr ? '→ preço justo por BDR (via market cap e câmbio)'
        : '÷ ' + fmt.bigShort(a.shares, 2) + ' papéis',
      isNum(r.preco_justo) ? fmt.money(r.preco_justo) : '—', '#34D399'));
    if (a.bdr) {
      box.appendChild(h('div', {
        class: 'note',
        html: 'Conversão sem depender da razão BDR/ação do programa: '
          + '<b>upside = equity value ÷ market cap em USD − 1</b>, e o preço justo por BDR '
          + 'é o preço de tela vezes (1 + upside). Market cap da BRAPI convertido pela PTAX '
          + (isNum(a.usdbrl) ? `(US$ 1 = R$ ${fmt.num(a.usdbrl, 2)})` : '') + '.'
      }));
    }

    const stackBox = h('div', { style: 'margin-top:11px' });
    box.appendChild(stackBox);
    setTimeout(() => C.stack(stackBox, [
      { name: 'Fluxos explícitos', value: r.soma_vp, color: '#67E8F9' },
      { name: 'Perpetuidade', value: r.vp_terminal, color: '#A78BFA' }
    ], { format: (v) => fmt.big(v, 1) }), 0);
    box.appendChild(h('div', {
      class: 'note',
      html: `Explícito <b>${fmt.pct(1 - (r.peso_perpetuidade || 0), 0)}</b> · `
        + `perpetuidade <b>${fmt.pct(r.peso_perpetuidade, 0)}</b> do Enterprise Value.`
    }));
    return box;
  }

  /* ==================================================== aba fundamentos */

  function renderFundamentos() {
    const host = qs('[data-panel="fundamentos"]');
    if (host.dataset.done === '1') return;
    host.dataset.done = '1';
    host.innerHTML = '';

    const f = state.data.fundamentals;
    const anos = f.years || [];

    if (f.bdr && !anos.length) {
      host.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>Fundamentos indisponíveis para este BDR.</b> As demonstrações de empresas '
          + 'estrangeiras não estão na CVM: elas vêm dos módulos da BRAPI (dados Yahoo). '
          + 'Configure <code>BRAPI_TOKEN</code> no <code>finlab/.env</code> e recarregue — '
          + 'fundamentos, nota de saúde e valuation passam a funcionar como nas ações brasileiras.'
      }));
      return;
    }
    if (f.bdr) {
      host.appendChild(h('div', {
        class: 'callout',
        html: `<b>Valores em ${esc(f.currency || 'USD')}</b> — moeda de reporte da companhia, `
          + 'via BRAPI/Yahoo (histórico de até 4 exercícios). O preço do BDR em reais embute '
          + 'o câmbio; os fundamentos aqui, não.'
      }));
    }
    const s = f.series || {};
    const labels = anos.map(String);

    const legenda = (itens) => h('div', { class: 'legend' }, itens.map(([cor, nome]) =>
      h('span', {}, [h('i', { style: 'background:' + cor }), nome])));

    const painel = (titulo, sub, id, altura, itens) => {
      const p = h('section', { class: 'panel' }, [
        h('div', { class: 'panel-h' }, [
          h('div', { class: 'ptitle' }, [h('b', {}, titulo), sub ? ' · ' + sub : '']),
          itens ? legenda(itens) : null
        ]),
        h('div', { class: 'chartbox', id, style: 'height:' + (altura || 240) + 'px' })
      ]);
      host.appendChild(p);
      return p;
    };

    painel('Receita e resultado', 'exercícios anuais da CVM', 'chartRec', 250,
      [['#3B82F6', 'Receita'], ['#34D399', 'Lucro líquido']]);
    painel(f.financial ? 'Lucro líquido e patrimônio' : 'EBITDA e fluxo de caixa livre',
      'geração de resultado', 'chartEbitda', 250,
      f.financial ? [['#34D399', 'Lucro líquido'], ['#A78BFA', 'Patrimônio líquido']]
        : [['#67E8F9', 'EBITDA'], ['#F5B841', 'Fluxo de caixa livre']]);
    painel('Margens', 'sobre a receita do exercício', 'chartMargens', 230,
      f.financial ? [['#34D399', 'Margem líquida']]
        : [['#67E8F9', 'Margem EBITDA'], ['#34D399', 'Margem líquida']]);
    if (!f.financial) {
      painel('Dívida líquida', 'saldo ao fim de cada exercício', 'chartDivida', 210,
        [['#F87171', 'Dívida líquida']]);
      painel('Alavancagem', 'dívida líquida ÷ EBITDA', 'chartAlav', 200,
        [['#F5B841', 'Dív.Líq/EBITDA']]);
    }

    const pct = (num, den) => anos.map((_, i) => {
      const a = (s[num] || [])[i], b = (s[den] || [])[i];
      return isNum(a) && isNum(b) && b !== 0 ? a / b : null;
    });

    setTimeout(() => {
      C.bars(el('chartRec'), {
        height: 250, labels,
        series: [
          { name: 'Receita', color: '#3B82F6', values: s.receita || [] },
          { name: 'Lucro líquido', color: '#34D399', values: s.lucro_liquido || [] }
        ],
        yFormat: (v) => fmt.bigShort(v, 0)
      });

      C.bars(el('chartEbitda'), {
        height: 250, labels,
        series: f.financial ? [
          { name: 'Lucro líquido', color: '#34D399', values: s.lucro_liquido || [] },
          { name: 'Patrimônio líquido', color: '#A78BFA', values: s.patrimonio_liquido || [] }
        ] : [
          { name: 'EBITDA', color: '#67E8F9', values: s.ebitda || [] },
          { name: 'FCL', color: '#F5B841', values: s.fcl || [] }
        ],
        yFormat: (v) => fmt.bigShort(v, 0)
      });

      const margens = [
        { name: 'Margem líquida', color: '#34D399', points: pct('lucro_liquido', 'receita') }
      ];
      if (!f.financial) {
        margens.unshift({ name: 'Margem EBITDA', color: '#67E8F9', points: pct('ebitda', 'receita') });
      }
      C.line(el('chartMargens'), {
        height: 230,
        xMin: 0, xMax: Math.max(1, anos.length - 1),
        xTickValues: anos.map((_, i) => i),
        xFormat: (v) => labels[Math.round(v)] || '',
        yFormat: (v) => fmt.pct(v, 0),
        series: margens.map((m) => ({
          name: m.name, color: m.color, width: 2.4,
          points: m.points.map((y, i) => ({ x: i, y }))
        })),
        tipFormat: (p) => `<span class="k">${labels[Math.round(p.x)]}</span> · ${fmt.pct(p.y, 1)}`
      });

      if (!f.financial && el('chartDivida')) {
        const nd = s.divida_liquida || [];
        const ebitda = s.ebitda || [];
        C.bars(el('chartDivida'), {
          height: 210, labels,
          series: [{ name: 'Dívida líquida', color: '#F87171', values: nd }],
          yFormat: (v) => fmt.bigShort(v, 0)
        });
        // Eixo próprio: sobrepor a razão às barras exigiria reescalar o
        // número, o que atrapalha a leitura do nível de alavancagem.
        const razao = anos.map((_, i) => (isNum(nd[i]) && isNum(ebitda[i]) && ebitda[i] > 0
          ? nd[i] / ebitda[i] : null));
        C.line(el('chartAlav'), {
          height: 200,
          xMin: 0, xMax: Math.max(1, anos.length - 1),
          xTickValues: anos.map((_, i) => i),
          xFormat: (v) => labels[Math.round(v)] || '',
          yFormat: (v) => fmt.mult(v, 1),
          series: [{
            name: 'Dív.Líq/EBITDA', color: '#F5B841', width: 2.4,
            points: razao.map((y, i) => ({ x: i, y }))
          }],
          tipFormat: (p) => `<span class="k">${labels[Math.round(p.x)]}</span> · ${fmt.mult(p.y, 2)}`
        });
      }
    }, 0);

    // Tabela completa ------------------------------------------------------
    const LINHAS = f.financial
      ? [['receita', 'Receita de intermediação'], ['lucro_liquido', 'Lucro líquido'],
         ['patrimonio_liquido', 'Patrimônio líquido'], ['ativo_total', 'Ativo total']]
      : [['receita', 'Receita líquida'], ['ebitda', 'EBITDA'], ['ebit', 'EBIT'],
         ['lucro_liquido', 'Lucro líquido'], ['fco', 'Caixa das operações'],
         ['capex', 'Capex'], ['fcl', 'Fluxo de caixa livre'],
         ['divida_liquida', 'Dívida líquida'], ['patrimonio_liquido', 'Patrimônio líquido']];

    host.appendChild(h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, h('div', { class: 'ptitle' },
        [h('b', {}, 'Demonstrações consolidadas'), ' · DFP anual da CVM'])),
      h('div', { class: 'table-wrap' }, h('table', {}, [
        h('thead', {}, h('tr', {}, [h('th', { class: 'left' }, 'R$')]
          .concat(labels.map((y) => h('th', {}, y))))),
        h('tbody', {}, LINHAS.map(([key, label]) => h('tr', {}, [
          h('td', { class: 'left' }, label)
        ].concat(anos.map((_, i) => {
          const v = (s[key] || [])[i];
          return h('td', { class: 'num ' + (isNum(v) && v < 0 ? 'neg' : '') }, fmt.bigShort(v, 1));
        })))))
      ]))
    ]));
  }

  /* ========================================================= aba saúde */

  function renderSaude() {
    const host = qs('[data-panel="saude"]');
    if (host.dataset.done === '1') return;
    host.dataset.done = '1';
    host.innerHTML = '';

    const sc = state.data.score;
    const cor = sc.total >= 70 ? '#34D399' : sc.total >= 55 ? '#67E8F9'
      : sc.total >= 40 ? '#F5B841' : '#F87171';

    const topo = h('section', { class: 'panel' }, [
      h('div', {
        style: 'display:flex;gap:26px;align-items:center;flex-wrap:wrap'
      }, [
        h('div', { id: 'scoreRing' }),
        h('div', { style: 'flex:1 1 320px' }, [
          h('div', { class: 'ptitle', style: 'margin-bottom:8px' },
            [h('b', {}, 'Como a nota foi montada')]),
          h('div', {
            style: 'font-size:12.5px;line-height:1.7;color:var(--dim)',
            html: `Perfil <b style="color:var(--paper)">${esc(sc.perfil)}</b> · cobertura de dados `
              + `<b style="color:var(--paper)">${fmt.pct(sc.cobertura, 0)}</b>.<br>`
              + 'Cada indicador vira nota 0–100 por interpolação entre âncoras de mercado; os '
              + 'pilares entram com peso fixo. Indicador ausente não pune nem premia: o peso é '
              + 'redistribuído dentro do pilar e a cobertura cai.'
              + (sc.parcial ? '<br><b style="color:var(--amber)">Nota parcial:</b> menos de 60% '
                + 'dos indicadores têm dado na base da CVM.' : '')
          })
        ])
      ])
    ]);
    host.appendChild(topo);
    setTimeout(() => C.ring(el('scoreRing'), {
      value: sc.total, color: cor, size: 150,
      caption: 'DE 100'
    }), 0);

    (sc.pilares || []).forEach((p) => {
      const barra = h('div', { class: 'score-bar', style: 'margin-top:8px' },
        h('i', {
          style: `width:${isNum(p.score) ? p.score : 0}%;background:${
            !isNum(p.score) ? 'var(--dim2)' : p.score >= 70 ? '#34D399'
              : p.score >= 50 ? '#67E8F9' : p.score >= 35 ? '#F5B841' : '#F87171'}`
        })
      );

      const linhas = (p.components || []).map((c) => h('tr', {}, [
        h('td', { class: 'left' }, c.label),
        h('td', { class: 'num' }, formatIndicador(c.key, c.value)),
        h('td', { class: 'num' }, isNum(c.score) ? fmt.num(c.score, 0) : '—'),
        h('td', { class: 'num mut' }, fmt.pct(c.weight, 0))
      ]));

      host.appendChild(h('section', { class: 'panel' }, [
        h('div', { class: 'panel-h', style: 'margin-bottom:6px' }, [
          h('div', { class: 'ptitle' }, [h('b', {}, p.label), ` · peso ${fmt.pct(p.weight, 0)}`]),
          h('div', {
            style: 'font:700 17px var(--mono);color:' + (isNum(p.score) ? cor : 'var(--dim2)')
          }, isNum(p.score) ? fmt.num(p.score, 1) : '—')
        ]),
        barra,
        h('div', { class: 'table-wrap', style: 'margin-top:10px' }, h('table', {}, [
          h('thead', {}, h('tr', {}, [
            h('th', { class: 'left' }, 'Indicador'), h('th', {}, 'Valor'),
            h('th', {}, 'Nota'), h('th', {}, 'Peso no pilar')
          ])),
          h('tbody', {}, linhas)
        ]))
      ]));
    });
  }

  const IND_PCT = new Set(['roe', 'roa', 'roic', 'mg_liquida', 'mg_ebitda', 'cagr_receita_3a',
    'cagr_ebitda_3a', 'cagr_lucro_3a', 'fcf_margin', 'consistencia_lucro']);

  function formatIndicador(key, v) {
    if (!isNum(v)) return '—';
    if (IND_PCT.has(key)) return fmt.pct(v, 1);
    return fmt.mult(v, 2);
  }

  /* ========================================================= aba pares */

  function renderPares() {
    const host = qs('[data-panel="pares"]');
    if (host.dataset.done === '1') return;
    host.dataset.done = '1';
    host.innerHTML = '';

    const d = state.data;
    const stats = d.sector_stats || {};
    const mine = d.multiples;
    const meta = (state.universe.sectors || []).find((s) => s.key === d.fundamentals.sector);
    const keys = (meta ? meta.metrics : ['pl', 'pvp', 'ev_ebitda', 'roe'])
      .concat(d.fundamentals.financial ? [] : ['nd_ebitda']);
    const labels = state.universe.metric_labels;
    const fmts = state.universe.metric_format;

    // Comparação com a mediana ------------------------------------------
    // BDRs não têm mediana setorial calculada (os pares só têm dados de
    // mercado sem token) — a tabela de pares abaixo já cobre a comparação.
    if (!d.bdr) host.appendChild(h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, h('div', { class: 'ptitle' },
        [h('b', {}, 'A empresa contra a mediana do setor')])),
      h('div', { class: 'table-wrap' }, h('table', {}, [
        h('thead', {}, h('tr', {}, [
          h('th', { class: 'left' }, 'Múltiplo'), h('th', {}, d.fundamentals.ticker),
          h('th', {}, 'Mediana ' + d.sector_label), h('th', {}, 'Diferença')
        ])),
        h('tbody', {}, keys.map((k) => {
          const v = mine[k], med = stats[k];
          // Só múltiplos de preço comparam em termos relativos. Taxas comparam
          // em pontos percentuais e alavancagem em "turns" — razão entre um
          // valor negativo e uma mediana positiva não significa nada.
          const relativo = (k === 'pl' || k === 'pvp' || k === 'ev_ebitda');
          let dif = null, texto = fmt.dash;
          if (isNum(v) && isNum(med)) {
            if (relativo && med > 0 && v > 0) {
              dif = v / med - 1;
              texto = fmt.pctSigned(dif, 0);
            } else if (!relativo) {
              dif = v - med;
              texto = (dif > 0 ? '+' : '')
                + (fmts[k] === 'pct' ? fmt.num(dif * 100, 1) + ' p.p.' : fmt.num(dif, 2) + 'x');
            }
          }
          // Acima da mediana é bom em rentabilidade e dividendo; ruim em
          // múltiplo de preço e em alavancagem.
          const bom = (k === 'roe' || k === 'dy' || k === 'mg_ebitda') ? 1 : -1;
          const quaseZero = isNum(dif) && Math.abs(dif) < (relativo ? 0.005 : 0.001);
          return h('tr', {}, [
            h('td', { class: 'left' }, labels[k] || k),
            h('td', { class: 'num' }, fmt.byType(v, fmts[k])),
            h('td', { class: 'num mut' }, fmt.byType(med, fmts[k])),
            h('td', {
              class: 'num ' + (!isNum(dif) || quaseZero ? 'mut' : (dif * bom > 0 ? 'pos' : 'neg'))
            }, quaseZero ? 'em linha' : texto)
          ]);
        }))
      ])),
      h('div', {
        class: 'note',
        html: 'Medianas calculadas apenas com valores positivos em P/L, P/VP e EV/EBITDA — '
          + 'empresa com prejuízo distorceria a referência de caro/barato. '
          + `Amostra: ${stats.n || 0} empresas do setor.`
      })
    ]));

    // Tabela de pares ----------------------------------------------------
    // O backend devolve todo o setor; a própria empresa entra uma única vez,
    // com os múltiplos já recalculados nesta tela.
    const pares = (d.peers || []).filter((p) => p.ticker !== d.fundamentals.ticker).concat([{
      ticker: d.fundamentals.ticker, name: d.fundamentals.name,
      score: d.score.total, multiples: mine, price: d.market.price, perf: d.market.perf
    }]).sort((a, b) => (b.score || -1) - (a.score || -1));

    host.appendChild(h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, h('div', { class: 'ptitle' },
        [h('b', {}, 'Pares do setor'), ' · ordenados por saúde financeira'])),
      h('div', { class: 'table-wrap' }, h('table', {}, [
        h('thead', {}, h('tr', {}, [
          h('th', { class: 'left' }, 'Empresa'), h('th', {}, 'Saúde'), h('th', {}, 'Cotação'),
          h('th', {}, '12m')
        ].concat(keys.map((k) => h('th', {}, labels[k] || k))))),
        h('tbody', {}, pares.map((p) => {
          const eu = p.ticker === d.fundamentals.ticker;
          const tr = h('tr', {
            class: eu ? '' : 'clickable',
            style: eu ? 'background:rgba(103,232,249,.08);font-weight:700' : ''
          }, [
            h('td', { class: 'left' }, p.ticker + (eu ? ' ←' : '')),
            h('td', { class: 'num' }, isNum(p.score) ? fmt.num(p.score, 1) : '—'),
            h('td', { class: 'num' }, isNum(p.price) ? fmt.money(p.price) : '—'),
            h('td', { class: 'num ' + signClass(p.perf && p.perf.m12) },
              fmt.pctSigned(p.perf && p.perf.m12))
          ].concat(keys.map((k) => h('td', { class: 'num' },
            fmt.byType(p.multiples ? p.multiples[k] : null, fmts[k])))));
          if (!eu) {
            tr.addEventListener('click', () => {
              window.location.href = '/empresa?ticker=' + encodeURIComponent(p.ticker);
            });
          }
          return tr;
        }))
      ]))
    ]));

    // Consenso -----------------------------------------------------------
    const cons = d.consenso || {};
    if (isNum(cons.alvo_medio)) {
      host.appendChild(h('section', { class: 'panel' }, [
        h('div', { class: 'panel-h' }, h('div', { class: 'ptitle' },
          [h('b', {}, 'Consenso de analistas'), ' · via BRAPI'])),
        h('div', { style: 'display:flex;gap:26px;flex-wrap:wrap' }, [
          miniStat('Alvo médio', fmt.money(cons.alvo_medio), `${cons.analistas || '—'} analistas`),
          miniStat('Alvo mínimo', fmt.money(cons.alvo_baixo), ''),
          miniStat('Alvo máximo', fmt.money(cons.alvo_alto), ''),
          miniStat('Recomendação', String(cons.recomendacao || '—'), '')
        ])
      ]));
    }
  }

  /* ============================================================== abas */

  function bindTabs() {
    qsa('.tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        qsa('.tab').forEach((b) => b.classList.toggle('on', b === btn));
        state.tab = btn.dataset.tab;
        qsa('[data-panel]').forEach((p) => { p.hidden = p.dataset.panel !== state.tab; });
        if (state.tab === 'fundamentos') renderFundamentos();
        if (state.tab === 'saude') renderSaude();
        if (state.tab === 'pares') renderPares();
        if (state.tab === 'ia') window.FLAgents.render(state);
      });
    });
  }

  /* ============================================================ busca */

  function bindSearch() {
    const input = el('tickerSearch');
    const list = el('tickerList');
    list.style.cssText = 'position:absolute;top:100%;left:0;right:0;z-index:20;margin-top:6px;'
      + 'background:var(--panel2);border:1px solid var(--line2);border-radius:12px;'
      + 'max-height:320px;overflow-y:auto;display:none;box-shadow:var(--shadow)';

    function close() { list.style.display = 'none'; }

    input.addEventListener('input', () => {
      const q = input.value.trim().toUpperCase();
      list.innerHTML = '';
      if (!q) return close();
      const todos = (state.universe.companies || []).concat(state.universe.bdrs || []);
      const hits = todos.filter(
        (c) => c.ticker.includes(q) || c.name.toUpperCase().includes(q)).slice(0, 10);
      if (!hits.length) return close();
      hits.forEach((c) => {
        list.appendChild(h('div', {
          style: 'padding:9px 13px;cursor:pointer;font:500 12.5px var(--mono);'
            + 'border-bottom:1px solid rgba(126,150,190,.08)',
          onclick: () => { window.location.href = '/empresa?ticker=' + c.ticker; },
          onmouseenter: (ev) => { ev.target.style.background = 'rgba(103,232,249,.08)'; },
          onmouseleave: (ev) => { ev.target.style.background = 'transparent'; }
        }, `${c.ticker} · ${c.name}`));
      });
      list.style.display = 'block';
    });
    input.addEventListener('blur', () => setTimeout(close, 180));
  }

  /* ============================================================= render */

  let raf = null;
  function schedule() {
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = null; renderLive(); });
  }

  /** Redesenha só o que depende das premissas. */
  function renderLive() {
    syncControls();
    renderAlerts();
    renderKpis();
    renderRegua();
    renderValuation();
    window.FLAgents.updateAssumptions(state, params(), E.resumo(params()));
  }

  /** Quando o DCF não se aplica, some com a maquinaria do modelo em vez de
   *  exibir gráfico vazio e preço justo sem significado. */
  function modoSemDcf() {
    el('heroPanel').hidden = true;
    el('kpis').hidden = true;
    el('controls').hidden = true;
    qs('.layout').style.gridTemplateColumns = '1fr';
    const aba = qs('.tab[data-tab="valuation"]');
    if (aba) aba.remove();
    qs('[data-panel="valuation"]').remove();
    state.tab = 'fundamentos';
    qsa('.tab').forEach((b, i) => b.classList.toggle('on', i === 0));
    qsa('[data-panel]').forEach((p) => { p.hidden = p.dataset.panel !== 'fundamentos'; });
    renderFundamentos();
    // Os agentes continuam disponíveis: eles comentam fundamentos e múltiplos,
    // que existem mesmo sem DCF.
    window.FLAgents.updateAssumptions(state, state.a, {});
  }

  function renderAll() {
    renderStrip();
    if (!state.a.aplicavel) {
      renderAlerts();
      modoSemDcf();
      return;
    }
    renderScenarios();
    renderLive();
  }

  function renderFooter() {
    const f = state.data.fundamentals;
    if (f.bdr) {
      el('foot').innerHTML =
        '<b>Fontes (BDR).</b> Preço e volume do BDR na B3 ('
        + esc(state.data.market.price_source || '—') + '); demonstrações da companhia via '
        + 'módulos da BRAPI (dados Yahoo), na moeda de reporte ('
        + esc(f.currency || 'USD') + '), com histórico de até 4 exercícios.<br><br>'
        + '<b>Método.</b> O DCF roda inteiro na moeda de reporte; o upside compara o equity '
        + 'value com o market cap convertido pela PTAX, e o preço justo por BDR é o preço de '
        + 'tela vezes (1 + upside) — sem depender da razão BDR/ação do programa. Custo de '
        + 'capital ancorado em referências americanas (UST ~10 anos), editável nos sliders.'
        + '<br><br><b>Isto não é recomendação de investimento.</b>';
      return;
    }
    el('foot').innerHTML =
      '<b>Fontes.</b> Demonstrações anuais (DFP) da CVM para os fundamentos; '
      + esc(state.data.market.price_source || '—') + ' para preço e performance; '
      + 'BCB/PulseFlat para o macro. Nenhum número é estimado sem aviso: conta ausente aparece '
      + 'como “—”.<br><br>'
      + '<b>Método.</b> DCF de fluxo de caixa livre da firma, desconto no fim de cada período, '
      + 'perpetuidade por Gordon. Equity = Enterprise Value − dívida líquida contábil do último '
      + 'exercício (' + (f.last_year || '—') + '). O EPV capitaliza o EBIT normalizado dos últimos '
      + '3 anos, sem crescimento. Todas as premissas são editáveis e nada é travado.<br><br>'
      + '<b>Isto não é recomendação de investimento.</b>';
  }

  /* =============================================================== boot */

  async function boot() {
    state.ticker = currentTicker();
    el('brand').innerHTML = window.FL.brandHeader('Valuation interativo · ' + state.ticker);
    document.title = `${state.ticker} · Gab's FinLab`;

    try {
      const [uni, data] = await Promise.all([
        api('/api/universe'),
        api('/api/company/' + encodeURIComponent(state.ticker))
      ]);
      state.universe = uni;
      state.data = data;
      state.a = JSON.parse(JSON.stringify(data.assumptions));
      state.base = JSON.parse(JSON.stringify(data.assumptions));
      state.fcfMode = data.assumptions.fcf_modo || 'media3';

      // BDR: grandezas financeiras na moeda de reporte da companhia, e o
      // botão de voltar aponta para a tela de BDRs.
      if (data.fundamentals && data.fundamentals.bdr) {
        window.FL.fmt.unit = (data.fundamentals.currency === 'USD' || !data.fundamentals.currency)
          ? 'US$' : data.fundamentals.currency;
        const voltar = document.querySelector('.topbar-actions a.btn');
        if (voltar) {
          voltar.href = '/bdrs';
          voltar.textContent = '← BDRs';
        }
      }

      if (state.a.aplicavel) rebuildControls();
      bindTabs();
      bindSearch();
      renderAll();
      renderFooter();

      el('heroGrowth').addEventListener('input', (ev) => {
        const alvo = parseFloat(ev.target.value);
        const g = E.growthSeries(state.a.growth, 5);
        const delta = alvo - g[0];
        state.a.growth = g.map((v) => v + delta);   // move a curva em bloco
        el('heroVal').textContent = fmt.pct(alvo, 1);
        schedule();
      });
      el('btnLLM').addEventListener('click', () => window.FLSettings.open(
        () => window.FLAgents.render(state)));

      // Um agente pode propor premissas; ao aplicá-las, os sliders acompanham.
      window.addEventListener('finlab:assumptions-applied', () => {
        rebuildControls();
        renderAll();
      });
    } catch (err) {
      el('alertZone').appendChild(h('div', { class: 'callout bad' },
        'Não foi possível carregar ' + state.ticker + ': ' + err.message));
    }
  }

  boot();
})();
