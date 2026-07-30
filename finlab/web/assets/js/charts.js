/* Gab's FinLab — gráficos em SVG puro.
   Zero dependências: o painel abre offline e o visual fica sob controle
   total do design system. Suporta linha/área com faixas e marcadores
   (a "régua" de sensibilidade), barras combinadas, sparkline, anel de
   score e matriz de calor. */
(function (global) {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v !== null && v !== undefined) n.setAttribute(k, v);
    });
    return n;
  };
  const isNum = (v) => typeof v === 'number' && isFinite(v);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  /** Escala "bonita": passos 1/2/2.5/5/10. */
  function niceTicks(min, max, count) {
    if (!isNum(min) || !isNum(max)) return { min: 0, max: 1, ticks: [0, 1] };
    // Um piso maior que o teto (ex.: forçar 0 numa série toda negativa)
    // produziria passo negativo e coordenadas NaN.
    if (min > max) { const t = min; min = max; max = t; }
    if (min === max) { min -= Math.abs(min || 1) * 0.1; max += Math.abs(max || 1) * 0.1; }
    const span = max - min;
    const raw = span / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step * 1e-6; v += step) ticks.push(Number(v.toFixed(10)));
    return { min: lo, max: hi, ticks };
  }

  function ensureTip(container) {
    let tip = container.querySelector('.chart-tip');
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'chart-tip';
      container.appendChild(tip);
    }
    return tip;
  }

  function frame(container, opts) {
    container.innerHTML = '';
    container.style.position = 'relative';
    const height = opts.height || 260;
    container.style.height = height + 'px';
    const width = Math.max(280, container.clientWidth || 720);
    const svg = el('svg', {
      viewBox: `0 0 ${width} ${height}`,
      preserveAspectRatio: 'none',
      role: 'img',
      'aria-label': opts.ariaLabel || 'gráfico'
    });
    svg.style.width = '100%';
    svg.style.height = '100%';
    container.appendChild(svg);
    return { svg, width, height };
  }

  const COLORS = {
    grid: 'rgba(126,150,190,.11)',
    axis: 'rgba(126,150,190,.35)',
    zero: 'rgba(230,236,245,.34)',
    text: '#7C8DAA',
    brand: '#67E8F9'
  };

  /* ======================================================= linha / área ==== */

  /**
   * opts:
   *   series: [{ name, color, points:[{x,y}], width, dash, fill, colorAt(x) }]
   *   xType: 'linear' | 'category'
   *   labels: rótulos quando xType='category'
   *   xFormat(v), yFormat(v), tipFormat(point, serie)
   *   zones: [{ from, to, color }]            (só xType='linear')
   *   markers: [{ x, color, label }]
   *   dots: [{ x, y, color, label }]
   *   yMin, yMax, height, padding
   */
  function line(container, opts) {
    if (!container) return null;
    const o = Object.assign({ xType: 'linear', height: 260 }, opts);
    const { svg, width, height } = frame(container, o);
    const pad = Object.assign({ t: 16, r: 16, b: 26, l: 54 }, o.padding);
    const W = width - pad.l - pad.r;
    const H = height - pad.t - pad.b;
    const series = (o.series || []).filter((s) => s.points && s.points.length);

    if (!series.length) {
      svg.appendChild(el('text', {
        x: width / 2, y: height / 2, fill: COLORS.text, 'font-size': 12,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      })).textContent = 'sem dados suficientes';
      return null;
    }

    const xs = series.flatMap((s) => s.points.map((p) => p.x));
    const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter(isNum);
    const xMin = isNum(o.xMin) ? o.xMin : Math.min.apply(null, xs);
    const xMax = isNum(o.xMax) ? o.xMax : Math.max.apply(null, xs);
    const yScale = niceTicks(
      isNum(o.yMin) ? o.yMin : Math.min.apply(null, ys),
      isNum(o.yMax) ? o.yMax : Math.max.apply(null, ys),
      o.yTicks || 5
    );

    const sx = (v) => pad.l + (xMax === xMin ? W / 2 : ((v - xMin) / (xMax - xMin)) * W);
    const sy = (v) => pad.t + H - ((v - yScale.min) / (yScale.max - yScale.min || 1)) * H;

    // faixas coloridas de fundo
    (o.zones || []).forEach((z) => {
      const a = sx(clamp(z.from, xMin, xMax));
      const b = sx(clamp(z.to, xMin, xMax));
      if (b <= a) return;
      svg.appendChild(el('rect', { x: a, y: pad.t, width: b - a, height: H, fill: z.color }));
    });

    // grade horizontal
    yScale.ticks.forEach((t) => {
      const y = sy(t);
      svg.appendChild(el('line', {
        x1: pad.l, x2: pad.l + W, y1: y, y2: y,
        stroke: Math.abs(t) < 1e-12 ? COLORS.zero : COLORS.grid,
        'stroke-width': Math.abs(t) < 1e-12 ? 1.2 : 1
      }));
      const label = el('text', {
        x: pad.l - 8, y: y + 3.5, fill: COLORS.text, 'font-size': 10,
        'text-anchor': 'end', 'font-family': 'ui-monospace, monospace'
      });
      label.textContent = o.yFormat ? o.yFormat(t) : String(t);
      svg.appendChild(label);
    });

    // eixo X
    const xTickVals = o.xTickValues || (function () {
      const n = o.xTicks || 6;
      const out = [];
      for (let i = 0; i <= n; i++) out.push(xMin + ((xMax - xMin) * i) / n);
      return out;
    })();
    xTickVals.forEach((t) => {
      const x = sx(t);
      const label = el('text', {
        x, y: height - 8, fill: COLORS.text, 'font-size': 10,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      });
      label.textContent = o.xFormat ? o.xFormat(t) : String(Math.round(t));
      svg.appendChild(label);
    });

    // As séries são recortadas na área de plotagem: com escala limitada,
    // um trecho fora do eixo não pode invadir o resto do painel.
    const clipId = 'clip-' + Math.random().toString(36).slice(2, 9);
    const defs = el('defs');
    const clip = el('clipPath', { id: clipId });
    clip.appendChild(el('rect', { x: pad.l, y: pad.t - 2, width: W, height: H + 2 }));
    defs.appendChild(clip);
    svg.appendChild(defs);
    const plot = el('g', { 'clip-path': `url(#${clipId})` });
    svg.appendChild(plot);

    // séries
    series.forEach((s) => {
      const pts = s.points.filter((p) => isNum(p.y));
      if (!pts.length) return;
      const d = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(2)} ${sy(p.y).toFixed(2)}`).join(' ');

      if (s.fill) {
        const base = sy(clamp(0, yScale.min, yScale.max));
        plot.appendChild(el('path', {
          d: `${d} L${sx(pts[pts.length - 1].x).toFixed(2)} ${base} L${sx(pts[0].x).toFixed(2)} ${base} Z`,
          fill: s.fill, stroke: 'none'
        }));
      }

      if (s.colorAt) {
        // caminho segmentado: cada trecho ganha a cor da sua faixa
        for (let i = 1; i < pts.length; i++) {
          plot.appendChild(el('line', {
            x1: sx(pts[i - 1].x), y1: sy(pts[i - 1].y),
            x2: sx(pts[i].x), y2: sy(pts[i].y),
            stroke: s.colorAt(pts[i].x, pts[i].y),
            'stroke-width': s.width || 2.4,
            'stroke-linecap': 'round'
          }));
        }
      } else {
        plot.appendChild(el('path', {
          d, fill: 'none', stroke: s.color || COLORS.brand,
          'stroke-width': s.width || 2.2,
          'stroke-dasharray': s.dash || null,
          'stroke-linejoin': 'round', 'stroke-linecap': 'round'
        }));
      }
    });

    // Marcadores verticais. Os rótulos são escalonados em faixas para que
    // marcadores próximos não se sobreponham.
    const ocupado = [];
    (o.markers || []).slice().sort((a, b) => a.x - b.x).forEach((m) => {
      if (!isNum(m.x) || m.x < xMin || m.x > xMax) return;
      const x = sx(m.x);
      const largura = String(m.label).length * 5.4;
      const cx = clamp(x, pad.l + largura / 2, pad.l + W - largura / 2);

      let faixa = 0;
      while (ocupado.some((o2) => o2.faixa === faixa
        && Math.abs(o2.cx - cx) < (o2.largura + largura) / 2 + 6)) faixa++;
      ocupado.push({ faixa, cx, largura });

      const topo = pad.t + 8 + faixa * 12;
      svg.appendChild(el('line', {
        x1: x, x2: x, y1: topo + 4, y2: pad.t + H,
        stroke: m.color, 'stroke-width': 1, 'stroke-dasharray': '4 4'
      }));
      const label = el('text', {
        x: cx, y: topo, fill: m.color, 'font-size': 9.5, 'text-anchor': 'middle',
        'font-weight': 700, 'font-family': 'ui-monospace, monospace'
      });
      label.textContent = m.label;
      svg.appendChild(label);
    });

    // pontos destacados
    (o.dots || []).forEach((p) => {
      if (!isNum(p.x) || !isNum(p.y)) return;
      svg.appendChild(el('circle', {
        cx: sx(clamp(p.x, xMin, xMax)), cy: sy(clamp(p.y, yScale.min, yScale.max)),
        r: p.r || 6, fill: p.color || '#F5B841',
        stroke: '#0A1120', 'stroke-width': 2.5
      }));
    });

    // interação
    if (o.hover !== false) {
      const tip = ensureTip(container);
      const cross = el('line', {
        x1: 0, x2: 0, y1: pad.t, y2: pad.t + H,
        stroke: COLORS.axis, 'stroke-width': 1, opacity: 0
      });
      svg.appendChild(cross);
      const marker = el('circle', { r: 4, fill: COLORS.brand, opacity: 0 });
      svg.appendChild(marker);

      const overlay = el('rect', {
        x: pad.l, y: pad.t, width: W, height: H, fill: 'transparent', style: 'cursor:crosshair'
      });
      svg.appendChild(overlay);

      const main = series[series.length - 1].points.length >= series[0].points.length
        ? series[0] : series[series.length - 1];

      overlay.addEventListener('mousemove', (ev) => {
        const rect = svg.getBoundingClientRect();
        const px = ((ev.clientX - rect.left) / rect.width) * width;
        const xVal = xMin + ((px - pad.l) / W) * (xMax - xMin);
        let best = null, bestD = Infinity;
        main.points.forEach((p) => {
          const d = Math.abs(p.x - xVal);
          if (d < bestD && isNum(p.y)) { bestD = d; best = p; }
        });
        if (!best) return;
        const bx = sx(best.x), by = sy(best.y);
        cross.setAttribute('x1', bx); cross.setAttribute('x2', bx); cross.setAttribute('opacity', 1);
        marker.setAttribute('cx', bx); marker.setAttribute('cy', by); marker.setAttribute('opacity', 1);
        tip.innerHTML = o.tipFormat
          ? o.tipFormat(best, main, series)
          : `<span class="k">${o.xFormat ? o.xFormat(best.x) : best.x}</span> · ${o.yFormat ? o.yFormat(best.y) : best.y}`;
        tip.classList.add('on');
        const tw = tip.offsetWidth || 120;
        const left = clamp((bx / width) * container.clientWidth - tw / 2, 4, container.clientWidth - tw - 4);
        tip.style.left = left + 'px';
        tip.style.top = clamp((by / height) * container.clientHeight - 52, 2, container.clientHeight - 40) + 'px';
      });
      overlay.addEventListener('mouseleave', () => {
        cross.setAttribute('opacity', 0);
        marker.setAttribute('opacity', 0);
        tip.classList.remove('on');
      });
    }

    return { sx, sy, svg };
  }

  /* ============================================================== barras ==== */

  /**
   * opts:
   *   labels: [..]
   *   series: [{ name, color, values:[..] }]   (barras agrupadas)
   *   overlay: { name, color, values:[..] }    (linha sobre as barras, mesmo eixo)
   *   yFormat(v), height
   */
  function bars(container, opts) {
    if (!container) return null;
    const o = Object.assign({ height: 250 }, opts);
    const { svg, width, height } = frame(container, o);
    const pad = Object.assign({ t: 16, r: 16, b: 26, l: 56 }, o.padding);
    const W = width - pad.l - pad.r;
    const H = height - pad.t - pad.b;
    const labels = o.labels || [];
    const series = (o.series || []).filter((s) => s.values && s.values.length);
    if (!labels.length || !series.length) {
      const t = el('text', {
        x: width / 2, y: height / 2, fill: COLORS.text, 'font-size': 12,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      });
      t.textContent = 'sem dados suficientes';
      svg.appendChild(t);
      return null;
    }

    const all = series.flatMap((s) => s.values).filter(isNum)
      .concat((o.overlay && o.overlay.values || []).filter(isNum));
    if (!all.length) {
      const t = el('text', {
        x: width / 2, y: height / 2, fill: COLORS.text, 'font-size': 12,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      });
      t.textContent = 'sem dados suficientes';
      svg.appendChild(t);
      return null;
    }
    // O domínio precisa conter o zero nas duas pontas: a barra é desenhada de
    // 0 até o valor, então uma série toda negativa (ou toda positiva) sem o
    // zero no eixo joga a base fora da área e a barra vaza do painel.
    const yScale = niceTicks(Math.min(0, Math.min.apply(null, all)),
                             Math.max(0, Math.max.apply(null, all)), 5);
    const sy = (v) => pad.t + H - ((v - yScale.min) / (yScale.max - yScale.min || 1)) * H;

    // Recorte defensivo: nenhum traço pode invadir o resto da página.
    const clipId = 'clipb-' + Math.random().toString(36).slice(2, 9);
    const defs = el('defs');
    const clip = el('clipPath', { id: clipId });
    clip.appendChild(el('rect', { x: pad.l - 2, y: pad.t - 4, width: W + 4, height: H + 8 }));
    defs.appendChild(clip);
    svg.appendChild(defs);
    const plot = el('g', { 'clip-path': `url(#${clipId})` });

    yScale.ticks.forEach((t) => {
      const y = sy(t);
      svg.appendChild(el('line', {
        x1: pad.l, x2: pad.l + W, y1: y, y2: y,
        stroke: Math.abs(t) < 1e-12 ? COLORS.zero : COLORS.grid,
        'stroke-width': Math.abs(t) < 1e-12 ? 1.2 : 1
      }));
      const lb = el('text', {
        x: pad.l - 8, y: y + 3.5, fill: COLORS.text, 'font-size': 10,
        'text-anchor': 'end', 'font-family': 'ui-monospace, monospace'
      });
      lb.textContent = o.yFormat ? o.yFormat(t) : String(t);
      svg.appendChild(lb);
    });

    svg.appendChild(plot);   // barras e linha ficam dentro do recorte

    const slot = W / labels.length;
    const groupW = slot * 0.62;
    const barW = groupW / series.length;
    const tip = ensureTip(container);

    labels.forEach((lab, i) => {
      const cx = pad.l + slot * i + slot / 2;
      series.forEach((s, j) => {
        const v = s.values[i];
        if (!isNum(v)) return;
        const y0 = sy(0), y1 = sy(v);
        const x = cx - groupW / 2 + barW * j;
        const rect = el('rect', {
          x: x + 1, y: Math.min(y0, y1), width: Math.max(1, barW - 2),
          height: Math.max(1, Math.abs(y1 - y0)), fill: s.color, rx: 2, opacity: .92,
          style: 'cursor:pointer'
        });
        rect.addEventListener('mouseenter', () => {
          rect.setAttribute('opacity', 1);
          tip.innerHTML = `<span class="k">${lab}</span> · ${s.name}<br>${o.yFormat ? o.yFormat(v) : v}`;
          tip.classList.add('on');
          const tw = tip.offsetWidth || 120;
          tip.style.left = clamp((cx / width) * container.clientWidth - tw / 2, 4,
            container.clientWidth - tw - 4) + 'px';
          tip.style.top = clamp((Math.min(y0, y1) / height) * container.clientHeight - 48, 2,
            container.clientHeight - 40) + 'px';
        });
        rect.addEventListener('mouseleave', () => {
          rect.setAttribute('opacity', .92);
          tip.classList.remove('on');
        });
        plot.appendChild(rect);
      });

      const lb = el('text', {
        x: cx, y: height - 8, fill: COLORS.text, 'font-size': 10,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      });
      lb.textContent = lab;
      svg.appendChild(lb);
    });

    if (o.overlay && o.overlay.values) {
      const pts = o.overlay.values.map((v, i) => ({
        x: pad.l + slot * i + slot / 2, y: isNum(v) ? sy(v) : null
      })).filter((p) => p.y !== null);
      if (pts.length > 1) {
        plot.appendChild(el('path', {
          d: pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' '),
          fill: 'none', stroke: o.overlay.color, 'stroke-width': 2,
          'stroke-dasharray': o.overlay.dash || null, 'stroke-linecap': 'round'
        }));
        pts.forEach((p) => plot.appendChild(el('circle', {
          cx: p.x, cy: p.y, r: 3, fill: o.overlay.color, stroke: '#0A1120', 'stroke-width': 1.5
        })));
      }
    }
    return { svg };
  }

  /* =========================================================== sparkline ==== */

  function spark(container, opts) {
    if (!container) return;
    const o = Object.assign({ height: 30 }, opts);
    const vals = (o.values || []).filter(isNum);
    container.innerHTML = '';
    if (vals.length < 2) return;
    const width = 100, height = o.height;
    const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none' });
    svg.style.width = '100%'; svg.style.height = height + 'px'; svg.style.display = 'block';
    const min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    const sy = (v) => height - 3 - ((v - min) / (max - min || 1)) * (height - 6);
    const d = vals.map((v, i) => `${i ? 'L' : 'M'}${((i / (vals.length - 1)) * width).toFixed(2)} ${sy(v).toFixed(2)}`).join(' ');
    const up = vals[vals.length - 1] >= vals[0];
    const color = o.color || (up ? '#34D399' : '#F87171');
    svg.appendChild(el('path', {
      d: `${d} L${width} ${height} L0 ${height} Z`, fill: color, opacity: .12, stroke: 'none'
    }));
    svg.appendChild(el('path', { d, fill: 'none', stroke: color, 'stroke-width': 1.6, 'stroke-linejoin': 'round' }));
    container.appendChild(svg);
  }

  /* ========================================================== anel de score = */

  function ring(container, opts) {
    if (!container) return;
    const o = Object.assign({ size: 132, value: 0, max: 100 }, opts);
    container.innerHTML = '';
    const s = o.size, r = s / 2 - 11, c = 2 * Math.PI * r;
    const frac = clamp((o.value || 0) / o.max, 0, 1);
    const svg = el('svg', { viewBox: `0 0 ${s} ${s}` });
    svg.style.width = s + 'px'; svg.style.height = s + 'px'; svg.style.display = 'block';
    svg.appendChild(el('circle', {
      cx: s / 2, cy: s / 2, r, fill: 'none',
      stroke: 'rgba(126,150,190,.15)', 'stroke-width': 9
    }));
    svg.appendChild(el('circle', {
      cx: s / 2, cy: s / 2, r, fill: 'none', stroke: o.color || COLORS.brand,
      'stroke-width': 9, 'stroke-linecap': 'round',
      'stroke-dasharray': `${(c * frac).toFixed(2)} ${c.toFixed(2)}`,
      transform: `rotate(-90 ${s / 2} ${s / 2})`
    }));
    const v = el('text', {
      x: s / 2, y: s / 2 + 2, fill: o.color || COLORS.brand, 'font-size': 27,
      'font-weight': 700, 'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
    });
    v.textContent = o.label || (isNum(o.value) ? Math.round(o.value) : '—');
    svg.appendChild(v);
    const sub = el('text', {
      x: s / 2, y: s / 2 + 21, fill: COLORS.text, 'font-size': 9.5,
      'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace',
      'letter-spacing': 1.6
    });
    sub.textContent = o.caption || '';
    svg.appendChild(sub);
    container.appendChild(svg);
  }

  /* ======================================================== mapa de calor === */

  /**
   * opts: { rows, cols, rowLabel(v), colLabel(v), value(r,c), format(v),
   *         highlight:{row,col}, height }
   */
  function heat(container, opts) {
    if (!container) return;
    const o = opts || {};
    const rows = o.rows || [], cols = o.cols || [];
    container.innerHTML = '';
    container.style.position = 'relative';
    if (!rows.length || !cols.length) return;

    const cells = [];
    rows.forEach((r, i) => cols.forEach((c, j) => {
      const v = o.value(r, c);
      if (isNum(v)) cells.push(v);
      void i; void j;
    }));
    if (!cells.length) return;
    const min = Math.min.apply(null, cells), max = Math.max.apply(null, cells);

    const table = document.createElement('table');
    table.style.width = '100%';
    table.style.fontSize = '11.5px';

    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    hr.appendChild(Object.assign(document.createElement('th'), {
      className: 'left', textContent: o.corner || ''
    }));
    cols.forEach((c) => {
      const th = document.createElement('th');
      th.textContent = o.colLabel ? o.colLabel(c) : String(c);
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rows.forEach((r) => {
      const tr = document.createElement('tr');
      const th = document.createElement('td');
      th.className = 'left mut';
      th.textContent = o.rowLabel ? o.rowLabel(r) : String(r);
      tr.appendChild(th);
      cols.forEach((c) => {
        const td = document.createElement('td');
        const v = o.value(r, c);
        td.textContent = isNum(v) ? (o.format ? o.format(v) : v.toFixed(1)) : '—';
        if (isNum(v)) {
          const t = (v - min) / (max - min || 1);
          // vermelho → âmbar → verde
          const color = t < 0.5
            ? `rgba(248,113,113,${(0.30 * (1 - t * 2) + 0.06).toFixed(3)})`
            : `rgba(52,211,153,${(0.30 * ((t - 0.5) * 2) + 0.06).toFixed(3)})`;
          td.style.background = color;
        }
        if (o.highlight && o.highlight.row === r && o.highlight.col === c) {
          td.style.outline = '1.5px solid #67E8F9';
          td.style.outlineOffset = '-2px';
          td.style.fontWeight = '700';
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  /* ============================================================ barra 100% == */

  function stack(container, segments, opts) {
    if (!container) return;
    const o = opts || {};
    container.innerHTML = '';
    const total = segments.reduce((a, s) => a + Math.abs(s.value || 0), 0) || 1;
    const bar = document.createElement('div');
    bar.style.cssText = 'display:flex;height:' + (o.height || 12) + 'px;border-radius:6px;overflow:hidden;background:rgba(126,150,190,.12)';
    segments.forEach((s) => {
      const d = document.createElement('div');
      d.style.cssText = `width:${(Math.abs(s.value || 0) / total * 100).toFixed(2)}%;background:${s.color}`;
      d.title = `${s.name}: ${o.format ? o.format(s.value) : s.value}`;
      bar.appendChild(d);
    });
    container.appendChild(bar);
  }

  global.FLChart = { line, bars, spark, ring, heat, stack, niceTicks, COLORS };
})(window);
