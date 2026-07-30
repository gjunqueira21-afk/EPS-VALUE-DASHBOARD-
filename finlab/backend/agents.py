"""Agentes de análise: proxy multi-provedor de LLM + prompts especializados.

As chaves NÃO ficam no servidor. O navegador guarda os slots em
localStorage e envia a chave junto de cada chamada; o backend apenas
encaminha para o provedor escolhido (evitando CORS e diferenças de formato
entre APIs) e devolve o texto. Nada é gravado em disco nem em log.
"""

from __future__ import annotations

import json
from typing import Optional

import requests

from .settings import HTTP_TIMEOUT

PROVIDERS = {
    "openrouter": {
        "label": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "style": "openai",
        "models": ["anthropic/claude-sonnet-5", "anthropic/claude-opus-5", "openai/gpt-4.1",
                   "google/gemini-2.5-pro", "meta-llama/llama-3.3-70b-instruct",
                   "deepseek/deepseek-chat"],
        "docs": "https://openrouter.ai/keys",
    },
    "openai": {
        "label": "OpenAI",
        "url": "https://api.openai.com/v1/chat/completions",
        "style": "openai",
        "models": ["gpt-4.1", "gpt-4.1-mini", "o4-mini"],
        "docs": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic",
        "url": "https://api.anthropic.com/v1/messages",
        "style": "anthropic",
        "models": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"],
        "docs": "https://console.anthropic.com/settings/keys",
    },
    "google": {
        "label": "Google Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
        "style": "gemini",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "docs": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "style": "openai",
        "models": ["llama-3.3-70b-versatile", "qwen-2.5-32b"],
        "docs": "https://console.groq.com/keys",
    },
    "deepseek": {
        "label": "DeepSeek",
        "url": "https://api.deepseek.com/chat/completions",
        "style": "openai",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "docs": "https://platform.deepseek.com/api_keys",
    },
}


# ---------------------------------------------------------------------------
# Agentes
# ---------------------------------------------------------------------------

_COMUM = (
    "Você faz parte da mesa de análise do Gab's FinLab, um painel de valuation de ativos "
    "negociados na B3 — ações brasileiras e BDRs de empresas estrangeiras. Responda SEMPRE "
    "em português do Brasil, em tom técnico e direto, sem saudações e sem repetir os números "
    "que já estão na tela — interprete-os.\n"
    "Regras inegociáveis:\n"
    "• Use exclusivamente os dados do CONTEXTO. Se algo não estiver lá, diga que não há dado.\n"
    "• Nunca invente resultado trimestral, guidance, notícia ou preço-alvo de casa de análise.\n"
    "• As demonstrações são ANUAIS e têm defasagem — o campo ORIGEM DOS DADOS diz de onde "
    "vieram e em que moeda estão. Respeite a moeda: não confunda o valor contábil com o "
    "preço do papel na B3.\n"
    "• Nada do que você escreve é recomendação de investimento; é insumo de análise.\n"
)

AGENTS = {
    "equity": {
        "label": "Analista de Ações BR",
        "icon": "📊",
        "desc": "Lê os fundamentos e monta a tese: o que sustenta e o que ameaça o case.",
        "system": _COMUM + (
            "\nSeu papel: analista sell-side de renda variável Brasil.\n"
            "Entregue, em no máximo 200 palavras e nesta ordem:\n"
            "1. **Tese em uma frase.**\n"
            "2. **Três pontos fortes** dos fundamentos (cite o número que sustenta cada um).\n"
            "3. **Três riscos** concretos, incluindo o que o histórico mostra de fragilidade.\n"
            "4. **O que observar** no próximo resultado.\n"
            "Use markdown com listas curtas."
        ),
    },
    "macro": {
        "label": "Analista Macro",
        "icon": "🌎",
        "desc": "Traduz Selic, IPCA e câmbio em impacto direto nas premissas do modelo.",
        "system": _COMUM + (
            "\nSeu papel: economista-chefe. Conecte o macro do CONTEXTO às premissas do "
            "valuation desta empresa em específico.\n"
            "Se o ativo for uma AÇÃO BRASILEIRA, o eixo é Selic, CDI, IPCA e câmbio.\n"
            "Se for um BDR de empresa estrangeira, o eixo muda: o custo de capital do modelo "
            "é em dólar (juro do Tesouro americano), a operação da empresa é lá fora, e o "
            "câmbio BRL/USD entra como retorno adicional — ou risco — para quem compra o BDR "
            "em reais. Não trate Selic e IPCA como se fossem o driver da operação dela.\n"
            "Entregue, em no máximo 180 palavras:\n"
            "1. **Leitura do momento** (juros, inflação, câmbio).\n"
            "2. **Transmissão para a empresa**: custo de capital, custo da dívida, demanda, "
            "exposição cambial.\n"
            "3. **Direção das premissas**: diga explicitamente se Rf, spread de crédito e "
            "crescimento deveriam subir, cair ou ficar onde estão, e por quê."
        ),
    },
    "gestor": {
        "label": "Gestor",
        "icon": "🎯",
        "desc": "Veredito de portfólio: posição, gatilhos e o que invalida a tese.",
        "system": _COMUM + (
            "\nSeu papel: gestor de fundo de ações, responsável pela decisão.\n"
            "Entregue, em no máximo 180 palavras:\n"
            "1. **Veredito**: COMPRAR, MANTER ou EVITAR — uma linha de justificativa.\n"
            "2. **Tamanho de posição** sugerido em faixa (%% do book) e por quê.\n"
            "3. **Gatilhos de entrada/saída** ligados a preço, múltiplo ou alavancagem.\n"
            "4. **O que invalida a tese.**\n"
            "Seja decisivo: nada de 'depende do perfil do investidor'."
        ),
    },
    "premissas": {
        "label": "Engenheiro de Premissas",
        "icon": "🧪",
        "desc": "Propõe o conjunto de premissas mais defensável para o momento atual.",
        "system": _COMUM + (
            "\nSeu papel: quant responsável pela calibragem do modelo.\n"
            "Proponha o conjunto de premissas mais defensável para HOJE, ancorado no macro "
            "e no histórico da empresa no CONTEXTO.\n"
            "Responda EXCLUSIVAMENTE com um bloco de código JSON válido, sem texto fora dele, "
            "neste formato exato:\n"
            "```json\n"
            "{\n"
            '  "premissas": {\n'
            '    "rf": 0.14, "erp": 0.05, "beta": 1.0, "premio_extra": 0.0,\n'
            '    "spread_credito": 0.025, "wd": 0.3,\n'
            '    "growth": [0.08, 0.07, 0.06, 0.05, 0.045], "g_terminal": 0.04\n'
            "  },\n"
            '  "justificativa": "2 a 4 frases explicando as escolhas",\n'
            '  "confianca": "alta|media|baixa"\n'
            "}\n"
            "```\n"
            "Todas as taxas em decimal (0.14 = 14%). `growth` deve ter exatamente 5 elementos. "
            "g_terminal precisa ser menor que o WACC resultante."
        ),
    },
}


# ---------------------------------------------------------------------------
# Catálogo de modelos do provedor
# ---------------------------------------------------------------------------
# Cada provedor expõe os modelos que a SUA chave pode usar. Consultar a API é
# melhor do que uma lista fixa: modelos são renomeados e aposentados o tempo
# todo, e o que está liberado varia por conta.

_MODEL_ENDPOINTS = {
    "openrouter": ("https://openrouter.ai/api/v1/models", "bearer"),
    "openai": ("https://api.openai.com/v1/models", "bearer"),
    "groq": ("https://api.groq.com/openai/v1/models", "bearer"),
    "deepseek": ("https://api.deepseek.com/models", "bearer"),
    "anthropic": ("https://api.anthropic.com/v1/models", "anthropic"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/models", "google"),
}

# Modelos de chat costumam ter estes marcadores; o resto (embeddings, áudio,
# imagem, moderação) não serve para os agentes.
_NAO_CHAT = ("embedding", "embed", "whisper", "tts", "audio", "moderation",
             "image", "dall-e", "vision-only", "rerank", "guard", "aqa")


def list_models(provider: str, api_key: str) -> dict:
    """Modelos disponíveis para a chave informada.

    Devolve {"models": [...], "fonte": "api"|"catálogo local", "aviso": str|None}.
    Nunca levanta: sem chave ou com falha de rede, cai no catálogo local.
    """
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError(f"Provedor desconhecido: {provider}")

    local = {"models": cfg["models"], "fonte": "catálogo local", "aviso": None}
    if not api_key:
        local["aviso"] = "Sem chave: mostrando sugestões. Salve a chave para listar os seus modelos."
        return local

    url, estilo = _MODEL_ENDPOINTS.get(provider, (None, None))
    if not url:
        return local

    try:
        if estilo == "anthropic":
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            params = {"limit": 100}
        elif estilo == "google":
            headers = {"x-goog-api-key": api_key}
            params = {"pageSize": 200}
        else:
            headers = {"Authorization": f"Bearer {api_key}"}
            params = {}
        resp = requests.get(url, headers=headers, params=params, timeout=max(HTTP_TIMEOUT, 30))
    except requests.RequestException:
        local["aviso"] = "Não foi possível falar com o provedor agora — mostrando sugestões."
        return local

    if resp.status_code == 401:
        local["aviso"] = "Chave rejeitada pelo provedor (401) — confira antes de salvar."
        return local
    if resp.status_code >= 400:
        local["aviso"] = f"Provedor devolveu HTTP {resp.status_code} — mostrando sugestões."
        return local

    try:
        data = resp.json()
    except ValueError:
        local["aviso"] = "Resposta inesperada do provedor — mostrando sugestões."
        return local

    ids = _extrai_ids(data, estilo)
    ids = [m for m in ids if not any(t in m.lower() for t in _NAO_CHAT)]
    if not ids:
        local["aviso"] = "O provedor não listou modelos de chat — mostrando sugestões."
        return local

    return {"models": sorted(set(ids)), "fonte": "api", "aviso": None}


def _extrai_ids(data: dict, estilo: str) -> list[str]:
    if estilo == "google":
        out = []
        for m in data.get("models") or []:
            metodos = m.get("supportedGenerationMethods") or []
            if metodos and "generateContent" not in metodos:
                continue
            nome = str(m.get("name") or "")
            out.append(nome.split("/", 1)[-1] if nome.startswith("models/") else nome)
        return [m for m in out if m]
    # OpenAI, OpenRouter, Groq, DeepSeek e Anthropic usam {"data": [{"id": ...}]}
    return [str(m.get("id")) for m in (data.get("data") or []) if m.get("id")]


CHAT_SYSTEM = _COMUM + (
    "\nSeu papel: você é a mesa inteira, em conversa. O usuário está com o painel aberto e "
    "pergunta o que quiser sobre o ativo do CONTEXTO — fundamentos, múltiplos, premissas, "
    "macro, comparação com pares, sentido de um número na tela.\n"
    "Como responder:\n"
    "• Direto ao ponto. Uma pergunta simples merece resposta curta, sem seções nem títulos.\n"
    "• Cite o número do CONTEXTO que sustenta o que você afirma.\n"
    "• Se a pergunta pedir algo que não está no CONTEXTO (notícia, trimestre, evento), diga "
    "que o painel não tem esse dado em vez de especular.\n"
    "• Se o usuário pedir uma mudança de premissa, explique o efeito esperado e diga em qual "
    "slider mexer.\n"
    "• Mantenha o fio da conversa: o histórico anterior faz parte do assunto."
)


def agent_list() -> list[dict]:
    return [{"key": k, "label": v["label"], "icon": v["icon"], "desc": v["desc"]}
            for k, v in AGENTS.items()]


def chat_conversa(provider: str, api_key: str, model: str, contexto: str,
                  historico: list[dict], pergunta: str) -> str:
    """Conversa multi-turno com o contexto do painel injetado no sistema.

    O histórico chega do navegador (a conversa vive lá) e é truncado para
    caber num prompt: as 12 últimas mensagens bastam para manter o fio.
    """
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError(f"Provedor desconhecido: {provider}")

    sistema = CHAT_SYSTEM + "\n\nCONTEXTO\n========\n" + contexto

    turnos = []
    for msg in (historico or [])[-12:]:
        papel = "assistant" if msg.get("role") == "assistant" else "user"
        texto = str(msg.get("content") or "").strip()
        if texto:
            turnos.append({"role": papel, "content": texto})
    turnos.append({"role": "user", "content": pergunta})

    style = cfg["style"]
    try:
        if style == "openai":
            resp = requests.post(
                cfg["url"],
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json",
                         "HTTP-Referer": "https://github.com/gjunqueira21-afk/eps-value-dashboard-",
                         "X-Title": "Gab's FinLab"},
                json={"model": model, "temperature": 0.3, "max_tokens": 1200,
                      "messages": [{"role": "system", "content": sistema}] + turnos},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            return _json_or_raise(resp)["choices"][0]["message"]["content"]

        if style == "anthropic":
            resp = requests.post(
                cfg["url"],
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"},
                json={"model": model, "max_tokens": 1200, "temperature": 0.3,
                      "system": sistema, "messages": turnos},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            data = _json_or_raise(resp)
            return "".join(b.get("text", "") for b in data.get("content", []))

        if style == "gemini":
            conteudos = [{"role": "model" if t["role"] == "assistant" else "user",
                          "parts": [{"text": t["content"]}]} for t in turnos]
            resp = requests.post(
                f"{cfg['url']}/{model}:generateContent",
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={"systemInstruction": {"parts": [{"text": sistema}]},
                      "contents": conteudos,
                      "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1200}},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            data = _json_or_raise(resp)
            cands = data.get("candidates") or []
            if not cands:
                raise LLMError("Resposta vazia do Gemini.")
            partes = (cands[0].get("content") or {}).get("parts") or []
            return "".join(p.get("text", "") for p in partes)
    except requests.Timeout as exc:
        raise LLMError(f"{cfg['label']} não respondeu a tempo. Tente de novo.") from exc
    except requests.RequestException as exc:
        raise LLMError(
            f"Não foi possível alcançar {cfg['label']}. Verifique a conexão "
            f"(ou o proxy da sua rede). Detalhe: {type(exc).__name__}"
        ) from exc

    raise LLMError(f"Estilo de API não suportado: {style}")


def provider_list() -> list[dict]:
    return [{"key": k, "label": v["label"], "models": v["models"], "docs": v["docs"]}
            for k, v in PROVIDERS.items()]


# ---------------------------------------------------------------------------
# Chamada ao provedor
# ---------------------------------------------------------------------------

class LLMError(Exception):
    pass


def chat(provider: str, api_key: str, model: str, system: str, user: str,
         temperature: float = 0.3, max_tokens: int = 1400) -> str:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError(f"Provedor desconhecido: {provider}")
    if not api_key:
        raise LLMError("Chave de API não configurada para este slot.")

    style = cfg["style"]
    try:
        if style == "openai":
            resp = requests.post(
                cfg["url"],
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json",
                         "HTTP-Referer": "https://github.com/gjunqueira21-afk/eps-value-dashboard-",
                         "X-Title": "Gab's FinLab"},
                json={"model": model, "temperature": temperature, "max_tokens": max_tokens,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            data = _json_or_raise(resp)
            return data["choices"][0]["message"]["content"]

        if style == "anthropic":
            resp = requests.post(
                cfg["url"],
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"},
                json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                      "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            data = _json_or_raise(resp)
            return "".join(b.get("text", "") for b in data.get("content", []))

        if style == "gemini":
            resp = requests.post(
                f"{cfg['url']}/{model}:generateContent",
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={"systemInstruction": {"parts": [{"text": system}]},
                      "contents": [{"role": "user", "parts": [{"text": user}]}],
                      "generationConfig": {"temperature": temperature,
                                           "maxOutputTokens": max_tokens}},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            data = _json_or_raise(resp)
            cands = data.get("candidates") or []
            if not cands:
                raise LLMError("Resposta vazia do Gemini.")
            parts = (cands[0].get("content") or {}).get("parts") or []
            return "".join(p.get("text", "") for p in parts)
    except requests.Timeout as exc:
        raise LLMError(f"{cfg['label']} não respondeu a tempo. Tente de novo.") from exc
    except requests.RequestException as exc:
        # A exceção crua traz o stack do urllib3 inteiro; o que interessa ao
        # usuário é que a máquina não alcançou o provedor.
        raise LLMError(
            f"Não foi possível alcançar {cfg['label']}. Verifique a conexão "
            f"(ou o proxy da sua rede) e tente de novo. Detalhe: {type(exc).__name__}"
        ) from exc

    raise LLMError(f"Estilo de API não suportado: {style}")


def _json_or_raise(resp: requests.Response) -> dict:
    if resp.status_code == 401:
        raise LLMError("Chave de API rejeitada (401). Confira o slot configurado.")
    if resp.status_code == 429:
        raise LLMError("Limite de uso atingido no provedor (429). Tente de novo em instantes.")
    if resp.status_code >= 400:
        detalhe = resp.text[:300]
        raise LLMError(f"Provedor devolveu HTTP {resp.status_code}: {detalhe}")
    try:
        return resp.json()
    except ValueError as exc:
        raise LLMError("Resposta do provedor não é JSON válido.") from exc


# ---------------------------------------------------------------------------
# Contexto enviado ao modelo
# ---------------------------------------------------------------------------

def build_context(payload: dict, assumptions: dict, resultado: dict, macro: dict) -> str:
    """Serializa um contexto compacto e legível para o modelo."""
    fund = payload.get("fundamentals", {})
    snap = payload.get("market", {})
    mult = payload.get("multiples", {})
    sc = payload.get("score", {})
    base = fund.get("base", {})
    ind = fund.get("indicadores", {})

    bdr = bool(fund.get("bdr"))
    moeda = fund.get("currency") or ("USD" if bdr else "BRL")
    # Grandezas contábeis saem na moeda de reporte (US$ nos BDRs); preço e
    # preço-alvo continuam em reais, porque é o que o usuário vê na tela.
    unidade = ("US$" if moeda == "USD" else moeda) if bdr else "R$"

    def bi(v):
        if v is None:
            return "sem dado"
        texto = f"{v / 1e9:,.2f}".replace(",", "·").replace(".", ",").replace("·", ".")
        return f"{unidade} {texto} bi"

    def pc(v):
        return "sem dado" if v is None else f"{v * 100:.1f}%"

    def mu(v):
        return "sem dado" if v is None else f"{v:.1f}x"

    series = fund.get("series", {})
    years = fund.get("years", [])

    def hist(key, fmt=bi):
        vals = series.get(key) or []
        pares = [f"{y}: {fmt(v)}" for y, v in zip(years, vals) if v is not None][-5:]
        return "; ".join(pares) or "sem dado"

    linhas = [
        f"EMPRESA: {fund.get('name')} ({fund.get('ticker')}) — setor {fund.get('sector')}",
        f"Perfil contábil: {'instituição financeira' if fund.get('financial') else 'empresa não-financeira'}",
        "",
        "ORIGEM DOS DADOS",
    ]
    if bdr:
        linhas += [
            f"  Este ativo é um BDR: recibo negociado na B3 de {fund.get('name')}, empresa "
            f"estrangeira listada como {fund.get('us_ticker')} na bolsa de origem.",
            f"  Demonstrações: {fund.get('fonte') or 'Yahoo Finance'}, na moeda de reporte "
            f"({moeda}). Todos os valores contábeis abaixo estão em {moeda}.",
            "  Preço, múltiplos por ação e preço-alvo estão em REAIS por BDR — embutem o "
            "câmbio. O custo de capital do modelo é em dólar.",
            f"  Último exercício disponível: {fund.get('last_year')}",
        ]
    else:
        linhas += [
            "  Demonstrações anuais (DFP) da CVM, em reais.",
            f"  Último exercício na base: {fund.get('last_year')}",
        ]
    linhas += [
        "",
        "MERCADO",
        f"  Preço: R$ {snap.get('price')} ({snap.get('price_source')}, {snap.get('price_date')})",
        f"  Valor de mercado: {bi(snap.get('market_cap'))}",
        f"  Performance — dia {pc(snap.get('perf', {}).get('day'))}, semana {pc(snap.get('perf', {}).get('week'))}, "
        f"3m {pc(snap.get('perf', {}).get('m3'))}, 12m {pc(snap.get('perf', {}).get('m12'))}, YTD {pc(snap.get('perf', {}).get('ytd'))}",
        "",
        "MÚLTIPLOS",
        f"  P/L {mu(mult.get('pl'))} | P/VP {mu(mult.get('pvp'))} | EV/EBITDA {mu(mult.get('ev_ebitda'))} "
        f"| DY {pc(mult.get('dy'))} | Dív.Líq/EBITDA {mu(mult.get('nd_ebitda'))}",
        "",
        "FUNDAMENTOS (último exercício)",
        f"  Receita {bi(base.get('receita'))} | EBITDA {bi(base.get('ebitda'))} | Lucro líquido {bi(base.get('lucro_liquido'))}",
        f"  PL {bi(base.get('patrimonio_liquido'))} | Dívida líquida {bi(base.get('divida_liquida'))} | FCL {bi(base.get('fcl'))}",
        f"  ROE {pc(ind.get('roe'))} | ROIC {pc(ind.get('roic'))} | Mg. EBITDA {pc(ind.get('mg_ebitda'))} | Mg. líquida {pc(ind.get('mg_liquida'))}",
        f"  CAGR 3a receita {pc(ind.get('cagr_receita_3a'))} | CAGR 3a lucro {pc(ind.get('cagr_lucro_3a'))}",
        f"  Score de saúde financeira: {sc.get('total')} / 100 (cobertura de dados {pc(sc.get('cobertura'))})",
        "",
        "HISTÓRICO",
        f"  Receita — {hist('receita')}",
        f"  EBITDA — {hist('ebitda')}",
        f"  Lucro líquido — {hist('lucro_liquido')}",
        f"  FCL — {hist('fcl')}",
        f"  Dívida líquida — {hist('divida_liquida')}",
        "",
        "MACRO",
        "  " + " | ".join(
            f"{k.upper()} {v.get('value')}" + (f" ({v.get('source')})" if v.get("source") else "")
            for k, v in (macro or {}).items() if isinstance(v, dict)
        ),
        "",
        "PREMISSAS ATUAIS DO PAINEL",
        f"  Rf {pc(assumptions.get('rf'))} | ERP {pc(assumptions.get('erp'))} | beta {assumptions.get('beta')} "
        f"({assumptions.get('beta_source')}) | prêmio extra {pc(assumptions.get('premio_extra'))}",
        f"  Ke {pc(assumptions.get('ke'))} | Kd {pc(assumptions.get('kd'))} | Wd {pc(assumptions.get('wd'))} "
        f"| WACC {pc(assumptions.get('wacc'))}",
        f"  Crescimento 5 anos: {[pc(g) for g in (assumptions.get('growth') or [])]} | perpetuidade {pc(assumptions.get('g_terminal'))}",
        f"  FCL base: {bi(assumptions.get('fcf_base'))} (modo {assumptions.get('fcf_modo')})",
        "",
        "RESULTADO DO MODELO COM ESSAS PREMISSAS",
        f"  Preço justo: R$ {resultado.get('preco_justo')} | preço de tela: R$ {assumptions.get('preco')} "
        f"| upside {pc(resultado.get('upside'))}",
        f"  EV calculado {bi(resultado.get('ev'))} | equity value {bi(resultado.get('equity_value'))} "
        f"| peso da perpetuidade {pc(resultado.get('peso_perpetuidade'))}",
        f"  EPV (poder de lucro): R$ {resultado.get('epv_por_acao')} por ação",
        f"  Crescimento implícito no preço atual (DCF reverso): {pc(resultado.get('g_implicito'))}",
    ]
    return "\n".join(linhas)


def parse_assumption_json(text: str) -> Optional[dict]:
    """Extrai o JSON de premissas da resposta do agente quant."""
    if not text:
        return None
    trecho = text
    if "```" in text:
        partes = text.split("```")
        for parte in partes:
            limpo = parte.strip()
            if limpo.startswith("json"):
                limpo = limpo[4:].strip()
            if limpo.startswith("{"):
                trecho = limpo
                break
    inicio, fim = trecho.find("{"), trecho.rfind("}")
    if inicio < 0 or fim <= inicio:
        return None
    try:
        return json.loads(trecho[inicio:fim + 1])
    except ValueError:
        return None
