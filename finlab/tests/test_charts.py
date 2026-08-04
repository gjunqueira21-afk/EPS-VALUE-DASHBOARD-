"""Teste dos gráficos em SVG (charts.js), executados no navegador.

Gráfico não se testa por pixel — se testa pelo que ele afirma. Aqui a
pergunta é sempre "a geometria codifica o número certo?": posição
proporcional ao valor, cor ancorada no ponto de virada, ordem por impacto.

Rodar: python -m pytest finlab/tests/test_charts.py -q
Requer playwright + chromium; é pulado automaticamente se não houver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="playwright não instalado")

CHARTS = Path(__file__).resolve().parents[1] / "web" / "assets" / "js" / "charts.js"


def _chromium_alternativo() -> str | None:
    import os

    raiz = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    if not raiz.is_dir():
        return None
    for padrao in ("chromium-*/chrome-linux/chrome", "chromium*/chrome-linux/chrome"):
        for caminho in sorted(raiz.glob(padrao), reverse=True):
            if caminho.is_file():
                return str(caminho)
    return None


@pytest.fixture(scope="module")
def pagina():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # pragma: no cover
            alt = _chromium_alternativo()
            if not alt:
                pytest.skip(f"chromium indisponível: {exc}")
            browser = pw.chromium.launch(executable_path=alt, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 900, "height": 600})
        page.set_content(
            "<html><body><div id='box' style='width:800px;height:300px'></div></body></html>")
        page.add_script_tag(content=CHARTS.read_text(encoding="utf-8"))

        def avaliar(expr: str, args: dict | None = None):
            return page.evaluate(f"(args) => {{ {expr} }}", args or {})

        yield avaliar
        browser.close()


# ---------------------------------------------------------------------------
# Football field
# ---------------------------------------------------------------------------

def test_football_field_posiciona_barras_no_mesmo_eixo(pagina):
    saida = pagina("""
        const box = document.getElementById('box');
        FLChart.hbars(box, {
          items: [
            {label: 'DCF', from: 20, to: 60, point: 40},
            {label: 'EPV', from: 30, to: 30}
          ],
          ref: {value: 50, label: 'tela'},
          format: v => 'R$ ' + v
        });
        const rects = [...box.querySelectorAll('rect')].filter(r => +r.getAttribute('height') === 18);
        const losangos = box.querySelectorAll('path');
        const linhas = [...box.querySelectorAll('line')]
          .filter(l => l.getAttribute('stroke-dasharray'));
        return {
          barras: rects.length,
          losangos: losangos.length,
          x: rects[0] ? +rects[0].getAttribute('x') : null,
          largura: rects[0] ? +rects[0].getAttribute('width') : null,
          refX: linhas.length ? +linhas[0].getAttribute('x1') : null,
          circulos: box.querySelectorAll('circle').length
        };
    """)
    # DCF é faixa (retângulo); EPV é ponto (losango), não uma barra de 3px
    assert saida["barras"] == 1
    assert saida["losangos"] == 1
    assert saida["circulos"] == 1                      # o ponto central do DCF
    # a linha de referência (50) cai à direita do início da barra (20)
    assert saida["refX"] > saida["x"]
    # e dentro da barra, que vai de 20 a 60
    assert saida["x"] < saida["refX"] < saida["x"] + saida["largura"]


def test_football_field_sem_itens_nao_desenha(pagina):
    vazio = pagina("""
        const box = document.getElementById('box');
        box.innerHTML = 'sujeira';
        FLChart.hbars(box, {items: [{label: 'x', from: null, to: null}]});
        return box.innerHTML;
    """)
    assert vazio == ""


# ---------------------------------------------------------------------------
# Waterfall
# ---------------------------------------------------------------------------

def test_waterfall_faz_as_barras_flutuarem_no_acumulado(pagina):
    saida = pagina("""
        const box = document.getElementById('box');
        FLChart.waterfall(box, {
          height: 300,
          steps: [
            {label: 'A', value: 100},
            {label: 'B', value: 50},
            {label: 'EV', value: 150, tipo: 'total'},
            {label: 'Dívida', value: -60},
            {label: 'Equity', value: 90, tipo: 'total'}
          ],
          format: v => String(v)
        });
        const rects = [...box.querySelectorAll('rect')].map(r => ({
          y: +r.getAttribute('y'), h: +r.getAttribute('height')
        })).sort((a, b) => a.y - b.y);
        return {n: rects.length, rects};
    """)
    assert saida["n"] == 5
    # Toda barra tem altura positiva: nenhuma degenerou em faixa invisível.
    assert all(r["h"] > 0 for r in saida["rects"])


def test_waterfall_acumula_soma_e_total_corretamente(pagina):
    """A barra 'B' precisa COMEÇAR onde 'A' terminou — é o que faz a ponte
    ser uma ponte, e não cinco barras soltas."""
    saida = pagina("""
        const box = document.getElementById('box');
        FLChart.waterfall(box, {
          height: 300,
          steps: [{label: 'A', value: 100}, {label: 'B', value: 100},
                  {label: 'T', value: 200, tipo: 'total'}],
          format: v => String(v)
        });
        const rs = [...box.querySelectorAll('rect')];
        const topo = r => +r.getAttribute('y');
        const base = r => +r.getAttribute('y') + +r.getAttribute('height');
        return {aBase: base(rs[0]), aTopo: topo(rs[0]),
                bBase: base(rs[1]), bTopo: topo(rs[1]),
                tBase: base(rs[2]), tTopo: topo(rs[2])};
    """)
    # A sai de 0 até 100; B sai de 100 até 200 (topo de B = topo do total)
    assert saida["bBase"] == pytest.approx(saida["aTopo"], abs=0.6)
    assert saida["bTopo"] == pytest.approx(saida["tTopo"], abs=0.6)
    # o total desenha do zero (mesma base de A)
    assert saida["tBase"] == pytest.approx(saida["aBase"], abs=0.6)


# ---------------------------------------------------------------------------
# Tornado
# ---------------------------------------------------------------------------

def test_tornado_ordena_por_amplitude(pagina):
    rotulos = pagina("""
        const box = document.getElementById('box');
        FLChart.tornado(box, {
          base: 50,
          items: [
            {label: 'pequeno', baixo: 48, alto: 52},
            {label: 'enorme',  baixo: 20, alto: 80},
            {label: 'medio',   baixo: 40, alto: 60}
          ],
          format: v => String(v)
        });
        // o rótulo de cada linha carrega um <title> com o texto integral
        // (o do eixo, não) — é o que distingue os dois
        return [...box.querySelectorAll('text')]
          .filter(t => t.querySelector('title'))
          .map(t => t.querySelector('title').textContent);
    """)
    assert rotulos == ["enorme", "medio", "pequeno"]


def test_tornado_sem_base_nao_desenha(pagina):
    vazio = pagina("""
        const box = document.getElementById('box');
        box.innerHTML = 'sujeira';
        FLChart.tornado(box, {items: [{label: 'x', baixo: 1, alto: 2}], base: null});
        return box.innerHTML;
    """)
    assert vazio == ""


# ---------------------------------------------------------------------------
# Heatmap divergente
# ---------------------------------------------------------------------------

def test_heatmap_ancora_a_cor_no_centro_e_nao_no_meio_da_amostra(pagina):
    """O bug: numa matriz inteiramente positiva, a escala min..max pintava de
    vermelho a célula MENOS boa — sugerindo prejuízo onde não havia."""
    saida = pagina("""
        const box = document.getElementById('box');
        const vals = {'a|x': 0.05, 'a|y': 0.30, 'b|x': 0.10, 'b|y': 0.50};
        FLChart.heat(box, {
          rows: ['a', 'b'], cols: ['x', 'y'],
          value: (r, c) => vals[r + '|' + c],
          center: 0, format: v => String(v)
        });
        const tds = [...box.querySelectorAll('tbody td')].filter(t => t.style.background);
        return tds.map(t => t.style.background);
    """)
    # todas positivas → todas azuis; nenhuma laranja (o "vermelho" antigo)
    assert len(saida) == 4
    assert all("56, 189, 248" in cor for cor in saida), saida


def test_heatmap_marca_a_iso_linha_onde_o_sinal_vira(pagina):
    saida = pagina("""
        const box = document.getElementById('box');
        // linha 'a': -0.1 → +0.1 (vira entre as colunas x e y)
        const vals = {'a|x': -0.10, 'a|y': 0.10, 'b|x': -0.20, 'b|y': -0.05};
        FLChart.heat(box, {
          rows: ['a', 'b'], cols: ['x', 'y'],
          value: (r, c) => vals[r + '|' + c],
          center: 0, format: v => String(v)
        });
        const tds = [...box.querySelectorAll('tbody td')];
        return tds.map(t => ({txt: t.textContent,
                              esq: t.style.borderLeft, cima: t.style.borderTop}));
    """)
    # a célula a|y (+0.10) tem borda à esquerda: o sinal virou ali
    ay = next(c for c in saida if c["txt"] == "0.1")
    assert "2px solid" in ay["esq"]
    # b|y (-0.05) não vira nem à esquerda nem acima… mas vira POR CIMA de a|y
    by = next(c for c in saida if c["txt"] == "-0.05")
    assert "2px solid" in by["cima"]
    # a|x (-0.10) não marca nada: é a primeira célula e não cruza nada
    ax = next(c for c in saida if c["txt"] == "-0.1")
    assert not ax["esq"] and not ax["cima"]


def test_heatmap_sem_center_mantem_o_comportamento_antigo(pagina):
    """Compatibilidade: quem não passa `center` continua na escala min..max."""
    saida = pagina("""
        const box = document.getElementById('box');
        const vals = {'a|x': 1, 'a|y': 9};
        FLChart.heat(box, {
          rows: ['a'], cols: ['x', 'y'],
          value: (r, c) => vals[r + '|' + c], format: v => String(v)
        });
        return [...box.querySelectorAll('tbody td')]
          .filter(t => t.style.background).map(t => t.style.background);
    """)
    assert any("248, 113, 113" in c for c in saida)   # vermelho no mínimo
    assert any("52, 211, 153" in c for c in saida)    # verde no máximo


def test_rotulos_longos_e_ticks_nao_vazam_do_painel(pagina):
    """Rótulo do último tick centralizado vazava metade da largura para fora,
    e rótulo de categoria longo invadia o vizinho. Ambos com painel estreito."""
    saida = pagina("""
        const box = document.getElementById('box');
        box.style.width = '360px';
        const longos = ['Prêmio de risco (WACC) muito longo mesmo',
                        'Estrutura de capital', 'Beta'];
        FLChart.tornado(box, {
          base: 50,
          items: longos.map((l, i) => ({label: l, baixo: 40 - i, alto: 60 + i})),
          format: v => 'R$ ' + v.toFixed(2)
        });
        const c = box.getBoundingClientRect();
        const fora = [...box.querySelectorAll('text')].filter(t => {
          const r = t.getBoundingClientRect();
          return r.width > 0 && (r.left < c.left - 1 || r.right > c.right + 1);
        }).map(t => t.textContent);
        const cortados = [...box.querySelectorAll('text')]
          .filter(t => t.textContent.includes('…')).length;
        box.style.width = '800px';
        return {fora, cortados};
    """)
    assert saida["fora"] == [], saida["fora"]
    assert saida["cortados"] >= 1, "o rótulo longo deveria ter sido cortado"


def test_football_field_tambem_segura_os_rotulos(pagina):
    saida = pagina("""
        const box = document.getElementById('box');
        box.style.width = '340px';
        FLChart.hbars(box, {
          items: [{label: 'Múltiplos de pares comparáveis do setor', from: 10, to: 90},
                  {label: 'DCF', from: 20, to: 60}],
          ref: {value: 55, label: 'preço de tela R$ 55,00'},
          format: v => 'R$ ' + v.toFixed(2)
        });
        const c = box.getBoundingClientRect();
        const fora = [...box.querySelectorAll('text')].filter(t => {
          const r = t.getBoundingClientRect();
          return r.width > 0 && (r.left < c.left - 1 || r.right > c.right + 1);
        }).map(t => t.textContent);
        box.style.width = '800px';
        return fora;
    """)
    assert saida == [], saida


def test_ticks_de_valor_nao_se_sobrepoem_em_tela_estreita(pagina):
    """No celular, "R$ 20,00 R$ 40,00 R$ 60,00…" viravam um borrão de dígitos.
    A grade continua completa; só o rótulo é rareado."""
    saida = pagina("""
        const box = document.getElementById('box');
        box.style.width = '340px';
        const medir = () => {
          const ts = [...box.querySelectorAll('text')]
            .filter(t => !t.querySelector('title') && /R\\$/.test(t.textContent))
            .map(t => t.getBoundingClientRect())
            .filter(r => r.width > 0)
            .sort((a, b) => a.left - b.left);
          let colisoes = 0;
          for (let i = 1; i < ts.length; i++)
            if (ts[i].left < ts[i - 1].right + 2) colisoes++;
          return {colisoes, rotulos: ts.length};
        };
        const fmt = v => 'R$ ' + v.toFixed(2);
        FLChart.hbars(box, {items: [{label: 'DCF', from: 20, to: 90}], format: fmt});
        const f = medir();
        FLChart.tornado(box, {
          base: 50, format: fmt,
          items: [{label: 'Beta', baixo: 20, alto: 90}]
        });
        const t = medir();
        box.style.width = '800px';
        return {f, t, grade: box.querySelectorAll('line').length};
    """)
    assert saida["f"]["colisoes"] == 0, saida["f"]
    assert saida["t"]["colisoes"] == 0, saida["t"]
    assert saida["f"]["rotulos"] >= 2, "sobrou rótulo demais de menos no eixo"
    assert saida["grade"] >= 3, "a grade não deve sumir junto com os rótulos"
