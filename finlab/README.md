# 🧠 Gab's FinLab

Monitor fundamentalista e **valuation interativo** de ações da B3, construído sobre as
demonstrações da CVM. Quatro telas:

1. **Ações** — 90 ações em 11 setores, com cotação do dia, performance de semana,
   3 meses, 12 meses e YTD, os múltiplos que fazem sentido para cada setor e dívida
   líquida/EBITDA. Tudo ordenado da empresa **financeiramente mais sólida para a mais frágil**.
2. **Painel da empresa** — DCF e EPV com recálculo instantâneo ao mexer nos sliders,
   régua de sensibilidade, matriz WACC × perpetuidade, 10 anos de demonstrações,
   comparação com pares e uma **mesa de IA** com quatro analistas comentando os números.
3. **ETFs** — todos os fundos de índice listados na B3 (universo dinâmico), por categoria:
   tese (o que o fundo faz), taxa de administração, liquidez real (volume médio do boletim
   da B3) e patrimônio do registro CVM. ETF não tem valuation — tem custo e liquidez.
4. **BDRs** — empresas estrangeiras na B3, separadas pelos setores **GICS em inglês**, sem
   misturar com as ações brasileiras. Clicou, abre o mesmo painel de valuation das ações:
   fundamentos/score/DCF vêm do **Yahoo Finance** (gratuito, pelo papel de origem), na
   moeda de reporte (USD), e o preço justo por BDR sai de `upside = equity ÷ market cap`
   — sem depender da razão BDR/ação do programa.

```bash
git clone https://github.com/gjunqueira21-afk/EPS-VALUE-DASHBOARD-.git
cd EPS-VALUE-DASHBOARD-

.\finlab\iniciar.bat         # Windows (PowerShell ou cmd)
./finlab/iniciar.sh          # Linux / macOS
```

Abre em <http://127.0.0.1:8777>. **Funciona sem nenhuma chave de API.**
Requer Python 3.10+ no PATH — no Windows, marque *"Add python.exe to PATH"* na
instalação, senão o script avisa e para.

---

## Como funciona

```
finlab/
├── backend/            FastAPI: coleta, normalização contábil, score, proxy de IA
│   ├── universe.py     as 90 ações, seus setores e o CD_CVM de cada uma
│   ├── cvm.py          lê os parquets do pipeline CVM e monta séries anuais
│   ├── market.py       cotações e macro, com três provedores encadeados
│   ├── metrics.py      margens, retornos, alavancagem, múltiplos
│   ├── scoring.py      a nota de saúde financeira (0–100)
│   ├── valuation.py    premissas iniciais: WACC, crescimento, fluxo base
│   ├── agents.py       prompts dos analistas + proxy multi-provedor de LLM
│   └── app.py          rotas HTTP
├── web/                front-end sem dependências externas
│   ├── index.html      tela principal
│   ├── empresa.html    painel de valuation
│   └── assets/js/
│       ├── engine.js   o motor de DCF/EPV — roda no navegador
│       ├── charts.js   gráficos em SVG puro
│       └── ...
└── tests/              49 testes (pytest)
```

O front não carrega **nada** de CDN: fontes do sistema, gráficos em SVG escritos à mão.
O painel abre igual com ou sem internet.

O cálculo de valuation acontece no navegador, não no servidor. É por isso que arrastar
um slider recalcula os 5 anos de projeção, a perpetuidade, a régua, a matriz de
sensibilidade e os KPIs no mesmo frame.

---

## De onde vêm os dados

| Camada | Fonte | Precisa de chave? |
|---|---|---|
| Demonstrações anuais (DFP) | Parquets do pipeline em `valuation_cvm/` | não |
| Ações emitidas | Capital social da CVM; se faltar, deduzido do LPA publicado | não |
| Cotação e performance (ações) | BRAPI → Yahoo Finance → PulseFlat, nessa ordem | opcional |
| Cotação, volume e liquidez de ETFs/BDRs | Boletim diário da B3 (BDI) via PulseFlat | não |
| Lista de ETFs e patrimônio | Lista B3 + registro de fundos CVM via PulseFlat | não |
| Tese e taxa de adm. dos ETFs | Cadastro local (`etfs.py` · `ETF_META`) — não há fonte por API | não |
| Fundamentos de BDRs | Yahoo Finance pelo papel de origem (fallback: módulos BRAPI) | não |
| Selic, CDI, IPCA, dólar, Ibovespa | BCB via PulseFlat | não |
| Curva de juros (NTN-B / NTN-F) | ANBIMA via PulseFlat | não |
| Consenso de analistas e beta | BRAPI | sim |

**Sem token BRAPI** o painel usa o fechamento D-1 do [PulseFlat](https://github.com/PulseDataLabs/PulseFlat)
— CSVs públicos servidos pelo GitHub, que costumam passar até em rede corporativa restrita.
Com token, você ganha preço intradiário, dividend yield, beta e preço-alvo de analistas:
basta preencher `BRAPI_TOKEN` em `finlab/.env` (veja `.env.example`).

Todo fechamento que o painel vê é gravado em `finlab/data/history.csv`. As janelas de
3 meses, 12 meses e YTD aparecem conforme o histórico local se aprofunda.

### Atualizar a base da CVM

O FinLab lê os parquets gerados pelo pipeline que já existia neste repositório:

```bash
cd valuation_cvm
python -m src.main --start-year 2016
```

---

## A nota de saúde financeira

Nota de 0 a 100, **explicável linha a linha** na aba *Nota de saúde*. Cada indicador vira
uma nota por interpolação entre âncoras de mercado; os pilares entram com peso fixo:

| Pilar | Peso | Indicadores |
|---|---|---|
| Rentabilidade | 26% | ROE, ROIC, margem líquida |
| Alavancagem | 24% | Dív.líq/EBITDA, Dív.líq/PL |
| Margem operacional | 14% | Margem EBITDA |
| Crescimento | 16% | CAGR 3a de receita e de EBITDA |
| Geração de caixa | 14% | FCO/EBITDA, margem de FCL |
| Consistência | 6% | anos com lucro nos últimos 5 |

**Bancos e seguradoras usam outro conjunto** (rentabilidade 38%, margem 18%, crescimento
20%, solidez 16%, consistência 8%): dívida líquida/EBITDA e conversão de caixa não têm
significado num balanço de instituição financeira, e por isso aparecem como `n/a`.

Indicador ausente **não pune nem premia**: o peso é redistribuído dentro do pilar e a
cobertura de dados cai. Empresa com nota parcial ganha o marcador ◐.

---

## O modelo de valuation

- **DCF** de fluxo de caixa livre da firma. Fluxos anuais, desconto no fim do período,
  perpetuidade por Gordon exigindo WACC > g — quando isso não vale, o painel devolve
  um aviso, não um número.
- **Fluxo base**: FCO − capex, direto do DFC da CVM. O padrão é a média de 3 anos,
  para suavizar capital de giro e capex lumpy; dá para trocar pelo último exercício
  ou normalizar manualmente.
- **Custo de capital**: `Ke = Rf + β×ERP + prêmio adicional`, `Kd = CDI + spread`,
  `WACC = We·Ke + Wd·Kd·(1−t)`. O Rf padrão é o **prefixado ~10 anos da ANBIMA** — um
  modelo com perpetuidade precisa de juro longo, não da Selic overnight, que é cíclica.
  Um clique troca para Selic à vista ou NTN-B + IPCA.
  O risco-país já está embutido no juro brasileiro, por isso **não** somamos prêmio-país.
- **EPV (Greenwald)**: EBIT normalizado de 3 anos, depois de imposto, capitalizado ao
  WACC, sem crescimento. É a leitura de "quanto vale o poder de lucro atual".
- **DCF reverso**: o crescimento que o preço de hoje embute.
- **Units** (BPAC11, KLBN11, SANB11, TAEE11, ENGI11, IGTI11) têm o número de ações
  dividido pela composição da unit — sem isso, valor de mercado e todo múltiplo derivado
  sairiam inflados.

O motor JavaScript é validado por teste contra uma implementação independente em Python,
casa decimal a casa decimal (`finlab/tests/test_engine.py`).

---

## A mesa de IA

Quatro agentes leem **exatamente o que está na tela** — fundamentos da CVM, múltiplos,
macro do dia, suas premissas e o resultado do modelo:

| Agente | O que entrega |
|---|---|
| 📊 Analista de Ações BR | tese, três pontos fortes, três riscos, o que observar |
| 🌎 Analista Macro | como Selic, IPCA e câmbio deveriam mover as premissas |
| 🎯 Gestor | veredito, tamanho de posição, gatilhos, o que invalida a tese |
| 🧪 Engenheiro de Premissas | devolve um JSON de premissas que você aplica com um clique |

Configure até **4 slots** em *⚙ Modelos de IA* — OpenRouter, OpenAI, Anthropic, Google,
Groq ou DeepSeek. Cada agente escolhe seu slot, então dá para usar um modelo forte no
gestor e um barato no macro.

**Sobre as chaves:** ficam no `localStorage` do seu navegador e são enviadas ao servidor
local só no instante da chamada, que apenas repassa ao provedor (isso evita CORS e as
diferenças de formato entre APIs). Nada é gravado em disco, em log ou no repositório.

Os agentes não têm acesso a resultado trimestral, guidance, fato relevante nem notícia.
São leitura crítica dos números que estão na tela.

---

## Testes

```bash
python -m pytest finlab/tests -q
```

49 testes cobrindo extração contábil da CVM (incluindo as armadilhas de escala do LPA e
das units), consistência dos múltiplos, as curvas do score, as premissas de valuation,
o proxy de LLM nos três formatos de API e o motor de DCF contra referência independente.

---

## Limites conhecidos

- Os múltiplos usam o **último exercício fechado** da CVM, não 12 meses móveis. O ano-base
  aparece ao lado de cada empresa. Isso torna P/L e EV/EBITDA mais defasados — e mais
  conservadores — que os de sites de mercado.
- EBITDA é **contábil** (EBIT + D&A do DFC), não "EBITDA ajustado" de release. Para
  empresas com impairment relevante os dois números divergem bastante.
- Sem token BRAPI, o valor de mercado é preço × ações da CVM. Se a empresa fez
  grupamento/desdobramento recente e o capital social ainda não refletiu, o múltiplo sai
  distorcido — a origem do número aparece no rodapé do card de cotação.
- DCF não se aplica a bancos e seguradoras. O painel diz isso explicitamente e mantém
  fundamentos, score e múltiplos.

---

**Isto não é recomendação de investimento.** É uma ferramenta de análise sobre dados
públicos, com todas as premissas abertas e editáveis.
