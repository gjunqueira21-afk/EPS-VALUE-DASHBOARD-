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

_BASE = "https://brapi.dev/api"
_TIMEOUT = 12


class BrapiClient:
    """Cliente para a API BRAPI.dev."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("BRAPI_TOKEN", "")
        if not self.token:
            logger.warning("BrapiClient: BRAPI_TOKEN não configurado.")

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
