"""
Cliente BRAPI.dev — dados de mercado B3 em tempo real.

BRAPI.dev é uma API brasileira que fornece cotações e dados fundamentais
de ações negociadas na B3.

Configure o token em .env:
    BRAPI_TOKEN=seu_token_aqui

Ou passe diretamente: BrapiClient(token="seu_token")
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from .logger import logger


def _get_brapi_token() -> str:
    """Lê o token BRAPI do .env ou do st.secrets (Streamlit Cloud)."""
    token = os.getenv("BRAPI_TOKEN", "")
    if not token:
        try:
            import streamlit as st
            token = st.secrets.get("BRAPI_TOKEN", "")
        except Exception:
            pass
    return token

_BASE = "https://brapi.dev/api"
_TIMEOUT = 12


class BrapiClient:
    """Cliente para a API BRAPI.dev."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or _get_brapi_token()
        if not self.token:
            logger.warning("BrapiClient: BRAPI_TOKEN não configurado.")

    @property
    def _headers(self) -> Dict[str, str]:
        """Autenticação via Bearer (padrão recomendado pela BRAPI)."""
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    # ------------------------------------------------------------------
    # Cotação + dados fundamentais
    # ------------------------------------------------------------------

    def get_quote(self, ticker: str) -> Optional[Dict]:
        """
        Retorna cotação completa + dados fundamentais de um ticker B3.

        Campos principais retornados:
            regularMarketPrice          Preço atual
            regularMarketChangePercent  Variação do dia (%)
            regularMarketVolume         Volume
            marketCap                   Market Cap (R$)
            sharesOutstanding           Ações em circulação
            priceEarningsRatio          P/L
            priceToBook                 P/VP
            enterpriseValue             EV
            enterpriseValueEbitda       EV/EBITDA
            dividendYield               Dividend Yield (%)
            fiftyTwoWeekHigh / Low      Máx/mín 52 semanas
        """
        if not self.token:
            logger.error("BrapiClient.get_quote: token ausente.")
            return None

        ticker = ticker.upper().strip()
        try:
            resp = requests.get(
                f"{_BASE}/quote/{ticker}",
                params={"token": self.token, "fundamental": "true"},
                timeout=_TIMEOUT,
            )

            if resp.status_code == 401:
                logger.error("BrapiClient: token inválido ou expirado.")
                return None
            if resp.status_code == 404:
                logger.warning("BrapiClient: ticker '%s' não encontrado.", ticker)
                return None
            if resp.status_code != 200:
                logger.error("BrapiClient: HTTP %d para %s", resp.status_code, ticker)
                return None

            results = resp.json().get("results", [])
            if not results:
                logger.warning("BrapiClient: sem resultados para '%s'.", ticker)
                return None

            logger.info("BrapiClient: cotação obtida para %s @ R$ %.2f",
                        ticker, results[0].get("regularMarketPrice", 0))
            return results[0]

        except requests.Timeout:
            logger.error("BrapiClient: timeout ao buscar %s.", ticker)
            return None
        except Exception as exc:
            logger.error("BrapiClient: erro inesperado para %s: %s", ticker, exc)
            return None

    # ------------------------------------------------------------------
    # Dados macro (fallback quando BCB/IPEA estiverem indisponíveis)
    # ------------------------------------------------------------------

    def get_prime_rate(self) -> Optional[float]:
        """Retorna a taxa SELIC mais recente (% a.a.) via BRAPI /v2/prime-rate."""
        if not self.token:
            return None
        try:
            resp = requests.get(
                f"{_BASE}/v2/prime-rate",
                params={"token": self.token, "country": "brazil", "historical": "false"},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json().get("prime-rate", [])
                if data:
                    return float(data[0].get("value"))
        except Exception as exc:
            logger.warning("BrapiClient.get_prime_rate: %s", exc)
        return None

    def get_inflation(self) -> Optional[float]:
        """Retorna o IPCA mais recente (% no período) via BRAPI /v2/inflation."""
        if not self.token:
            return None
        try:
            resp = requests.get(
                f"{_BASE}/v2/inflation",
                params={"token": self.token, "country": "brazil", "historical": "false"},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json().get("inflation", [])
                if data:
                    return float(data[0].get("value"))
        except Exception as exc:
            logger.warning("BrapiClient.get_inflation: %s", exc)
        return None

    def get_currency(self, pairs: str = "USD-BRL,EUR-BRL") -> List[Dict]:
        """
        Cotações de câmbio em tempo real via BRAPI /v2/currency.

        `pairs`: pares separados por vírgula (ex.: 'USD-BRL,EUR-BRL').
        Cada item retorna fromCurrency, toCurrency, name, bidPrice,
        askPrice, percentageChange, updatedAtDate, etc.
        """
        if not self.token:
            return []
        try:
            resp = requests.get(
                f"{_BASE}/v2/currency",
                params={"currency": pairs},
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json().get("currency", [])
            logger.warning("BrapiClient.get_currency: HTTP %d", resp.status_code)
        except Exception as exc:
            logger.warning("BrapiClient.get_currency: %s", exc)
        return []

    def get_macro(self, symbols: str = "selic,ipca,cdi") -> Dict[str, float]:
        """
        Indicadores macro via BRAPI /v2/macro (SELIC, IPCA, CDI numa chamada).

        Retorna {symbol: valor_float}, ex.: {"selic": 15.0, "ipca": 0.45, "cdi": 14.9}.
        Tolerante ao formato (valor pode vir como número ou string com vírgula).
        """
        out: Dict[str, float] = {}
        if not self.token:
            return out
        try:
            resp = requests.get(
                f"{_BASE}/v2/macro",
                params={"symbols": symbols, "sortOrder": "desc"},
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.warning("BrapiClient.get_macro: HTTP %d", resp.status_code)
                return out
            data = resp.json()
            items = data.get("macro") or data.get("results") or data.get("data") or []
            for it in items:
                if not isinstance(it, dict):
                    continue
                sym = str(it.get("symbol") or it.get("name") or "").strip().lower()
                raw = it.get("value")
                if raw is None:
                    raw = it.get("latest") or it.get("close")
                try:
                    val = float(str(raw).replace("%", "").replace(",", ".").strip())
                except (TypeError, ValueError):
                    val = None
                if sym and val is not None:
                    out[sym] = val
        except Exception as exc:
            logger.warning("BrapiClient.get_macro: %s", exc)
        return out

    # ------------------------------------------------------------------
    # Lista de tickers disponíveis
    # ------------------------------------------------------------------

    def list_tickers(self) -> List[str]:
        """Retorna lista de tickers de ações disponíveis na B3."""
        if not self.token:
            return []
        try:
            resp = requests.get(
                f"{_BASE}/quote/list",
                params={"token": self.token},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                return [s["stock"] for s in data.get("stocks", [])]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    # Busca de ticker pelo nome da empresa
    # ------------------------------------------------------------------

    def search_ticker(self, query: str) -> List[Dict]:
        """Busca tickers pelo nome da empresa (retorna lista de sugestões)."""
        if not self.token:
            return []
        try:
            resp = requests.get(
                f"{_BASE}/quote/list",
                params={"token": self.token, "search": query, "limit": 10},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json().get("stocks", [])
        except Exception:
            pass
        return []


# Instância global (usa BRAPI_TOKEN do .env automaticamente)
brapi = BrapiClient()
