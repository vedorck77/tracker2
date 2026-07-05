#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_30th_chile.py
=====================
Monitor de stock para productos Pokémon TCG "30th Celebration" en INGLÉS
en tiendas chilenas de TCG.

Estrategia por tienda:
  1. Tiendas Shopify  -> usa el endpoint público /products.json (rápido y confiable).
  2. Otras tiendas    -> scraping del buscador HTML con heurísticas de stock.

Uso:
    python3 monitor_30th_chile.py                  # una pasada, tabla en consola
    python3 monitor_30th_chile.py --csv out.csv    # además exporta CSV
    python3 monitor_30th_chile.py --watch 900      # revisa cada 900 s (15 min)
    python3 monitor_30th_chile.py --all-langs      # incluye también español
    python3 monitor_30th_chile.py --webhook URL    # notifica cambios (Discord/Slack/Telegram-proxy)

Requisitos:
    pip install requests beautifulsoup4

Notas:
  - Los sitios cambian; cada tienda está definida en STORES para que agregar
    o corregir una sea editar un dict, no el código.
  - Sé respetuoso: el modo --watch usa intervalos >= 300 s por defecto y
    User-Agent identificable. No hagas polling agresivo.
"""

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------------
# Configuración de tiendas
# ----------------------------------------------------------------------------
# type "shopify":  se consulta {base}/products.json (paginado).
# type "html":     se consulta search_url con el término de búsqueda y se
#                  parsean tarjetas de producto con heurísticas genéricas
#                  (funciona razonablemente en Jumpseller, WooCommerce, etc.)

STORES = [
    {
        "name": "Collector Center",
        "base": "https://collectorcenter.cl",
        "type": "shopify",
    },
    {
        "name": "Rey Mago",
        "base": "https://tiendareymago.cl",
        "type": "shopify",
    },
    {
        "name": "Piedrabruja",
        "base": "https://www.piedrabruja.cl",
        "type": "shopify",
    },
    {
        "name": "Guild Dreams",
        "base": "https://guildreams.com",
        "type": "shopify",
    },
    {
        "name": "The Way",
        "base": "https://www.theway.cl",
        "type": "html",
        "search_url": "https://www.theway.cl/search?q={q}",
    },
    {
        "name": "Geekers",
        "base": "https://www.geekers.cl",
        "type": "html",
        "search_url": "https://www.geekers.cl/search?q={q}",
    },
    {
        "name": "Santo Games",
        "base": "https://www.santogames.cl",
        "type": "html",
        "search_url": "https://www.santogames.cl/search?q={q}",
    },
    {
        "name": "Weplay",
        "base": "https://www.weplay.cl",
        "type": "html",
        "search_url": "https://www.weplay.cl/buscar?q={q}",
    },
    {
        "name": "La Comarca",
        "base": "https://www.lacomarca.cl",
        "type": "html",
        "search_url": "https://www.lacomarca.cl/search?q={q}",
    },
]

SEARCH_TERMS = ["30th celebration", "30 aniversario", "celebracion 30"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) StockMonitor30th/1.0 "
        "(uso personal; contacto del operador disponible a pedido)"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}

TIMEOUT = 20

# Palabras que indican SIN stock en HTML
OUT_OF_STOCK_HINTS = [
    "agotado", "sin stock", "sold out", "no disponible", "stock: 0", "out of stock",
]
# Palabras que indican producto en inglés
ENGLISH_HINTS = ["ingles", "inglés", "english", "(en)", " en ", "-en-", "_en_"]
SPANISH_HINTS = ["espanol", "español", "spanish", "latam"]


# ----------------------------------------------------------------------------
# Modelo de resultado
# ----------------------------------------------------------------------------
@dataclass
class Product:
    store: str
    title: str
    url: str
    price: str
    language: str        # "inglés" | "español" | "desconocido"
    in_stock: bool
    is_preorder: bool
    checked_at: str


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def norm(s: str) -> str:
    """minúsculas + sin tildes, para comparaciones robustas."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def matches_set(title: str) -> bool:
    t = norm(title)
    return ("30th" in t and "celebration" in t) or ("celebracion 30" in t) or ("30 aniversario" in t)


def detect_language(text: str) -> str:
    t = " " + norm(text) + " "
    if any(h in t for h in [norm(x) for x in SPANISH_HINTS]):
        return "español"
    if any(h in t for h in [norm(x) for x in ENGLISH_HINTS]):
        return "inglés"
    return "desconocido"


def detect_preorder(text: str) -> bool:
    t = norm(text)
    return any(k in t for k in ["preventa", "pre-venta", "preorder", "pre-order", "pre orden"])


def fmt_price_clp(value) -> str:
    try:
        n = float(value)
        return f"${n:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value or "s/i")


def get(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r
        print(f"    [!] HTTP {r.status_code} en {url}", file=sys.stderr)
    except requests.RequestException as e:
        print(f"    [!] Error de red en {url}: {e}", file=sys.stderr)
    return None


# ----------------------------------------------------------------------------
# Adaptador Shopify
# ----------------------------------------------------------------------------
def scan_shopify(store: dict) -> list[Product]:
    """Recorre /products.json paginado y filtra por set + idioma + stock."""
    results = []
    page = 1
    while page <= 20:  # tope de seguridad
        url = f"{store['base']}/products.json?limit=250&page={page}"
        r = get(url)
        if r is None:
            break
        try:
            data = r.json()
        except json.JSONDecodeError:
            print(f"    [!] {store['name']}: /products.json no devolvió JSON "
                  f"(¿no es Shopify o está protegido?)", file=sys.stderr)
            break

        products = data.get("products", [])
        if not products:
            break

        for p in products:
            title = p.get("title", "")
            if not matches_set(title):
                continue
            body = BeautifulSoup(p.get("body_html", "") or "", "html.parser").get_text(" ")
            blob = f"{title} {p.get('handle','')} {' '.join(p.get('tags', []))} {body[:500]}"
            lang = detect_language(blob)
            variants = p.get("variants", [])
            available = any(v.get("available") for v in variants)
            price = variants[0].get("price") if variants else None
            results.append(Product(
                store=store["name"],
                title=title.strip(),
                url=f"{store['base']}/products/{p.get('handle','')}",
                price=fmt_price_clp(price),
                language=lang,
                in_stock=bool(available),
                is_preorder=detect_preorder(blob),
                checked_at=datetime.now().isoformat(timespec="seconds"),
            ))
        page += 1
        time.sleep(0.6)  # cortesía
    return results


# ----------------------------------------------------------------------------
# Adaptador HTML genérico (Jumpseller / Woo / otros)
# ----------------------------------------------------------------------------
def scan_html(store: dict) -> list[Product]:
    """Busca en el buscador del sitio y parsea tarjetas de producto con
    heurísticas: cualquier <a> cuyo texto o href calce con el set."""
    results, seen = [], set()
    for term in SEARCH_TERMS:
        url = store["search_url"].format(q=requests.utils.quote(term))
        r = get(url)
        if r is None:
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            href = a["href"]
            blob = f"{text} {href}"
            if not matches_set(blob):
                continue
            if href.startswith("/"):
                href = store["base"].rstrip("/") + href
            if href in seen or "search" in href:
                continue
            seen.add(href)

            # contexto: la tarjeta contenedora suele traer precio y stock
            card = a
            for _ in range(4):
                if card.parent is not None:
                    card = card.parent
            card_text = card.get_text(" ", strip=True)[:800]

            price_m = re.search(r"\$\s?[\d\.\,]{4,}", card_text)
            out = any(h in norm(card_text) for h in OUT_OF_STOCK_HINTS)

            results.append(Product(
                store=store["name"],
                title=text[:120] or href,
                url=href,
                price=price_m.group(0) if price_m else "s/i",
                language=detect_language(blob + " " + card_text),
                in_stock=not out,
                is_preorder=detect_preorder(blob + " " + card_text),
                checked_at=datetime.now().isoformat(timespec="seconds"),
            ))
        time.sleep(0.6)
    return results


# ----------------------------------------------------------------------------
# Orquestación
# ----------------------------------------------------------------------------
def run_scan(only_english: bool = True) -> list[Product]:
    all_products: list[Product] = []
    for store in STORES:
        print(f"[*] Revisando {store['name']} ...")
        try:
            items = scan_shopify(store) if store["type"] == "shopify" else scan_html(store)
        except Exception as e:  # una tienda caída no debe botar el resto
            print(f"    [!] {store['name']} falló: {e}", file=sys.stderr)
            items = []
        if only_english:
            items = [p for p in items if p.language in ("inglés", "desconocido")]
        print(f"    -> {len(items)} producto(s) del set encontrados")
        all_products.extend(items)
    return all_products


def print_table(products: list[Product]) -> None:
    if not products:
        print("\nNo se encontraron productos 30th Celebration con los filtros actuales.")
        return
    products = sorted(products, key=lambda p: (not p.in_stock, p.store, p.title))
    print("\n" + "=" * 110)
    print(f"{'STOCK':6} {'TIENDA':17} {'IDIOMA':12} {'PRECIO':12} TÍTULO")
    print("=" * 110)
    for p in products:
        stock = "✔ SÍ " if p.in_stock else "✘ NO "
        pre = " [PREVENTA]" if p.is_preorder else ""
        print(f"{stock:6} {p.store:17.17} {p.language:12} {p.price:12} {p.title[:55]}{pre}")
        print(f"{'':6} {p.url}")
    print("=" * 110)
    disponibles = sum(1 for p in products if p.in_stock)
    print(f"Total: {len(products)} productos | Con stock/reservables: {disponibles}\n")


def export_csv(products: list[Product], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(products[0]).keys()) if products else
                           ["store", "title", "url", "price", "language",
                            "in_stock", "is_preorder", "checked_at"])
        w.writeheader()
        for p in products:
            w.writerow(asdict(p))
    print(f"[+] CSV exportado a {path}")


def notify_webhook(url: str, message: str) -> None:
    """Compatible con webhooks de Discord ({'content': ...}) y Slack ({'text': ...})."""
    for payload in ({"content": message}, {"text": message}):
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code in (200, 204):
                return
        except requests.RequestException:
            pass
    print("[!] No se pudo notificar por webhook", file=sys.stderr)


def diff_and_alert(prev: dict, current: list[Product], webhook: str | None) -> dict:
    """Compara con el estado anterior y alerta productos que PASARON a tener stock."""
    state = {p.url: p.in_stock for p in current}
    news = [p for p in current if p.in_stock and not prev.get(p.url, False)]
    for p in news:
        msg = (f"🟢 STOCK NUEVO: {p.title} — {p.store} — {p.price} — {p.url}")
        print(msg)
        if webhook:
            notify_webhook(webhook, msg)
    return state


def main() -> None:
    ap = argparse.ArgumentParser(description="Monitor de stock 30th Celebration en tiendas chilenas")
    ap.add_argument("--csv", help="Exportar resultados a CSV")
    ap.add_argument("--watch", type=int, metavar="SEGUNDOS",
                    help="Modo vigilancia: repetir cada N segundos (mínimo 300)")
    ap.add_argument("--all-langs", action="store_true",
                    help="Incluir también productos en español")
    ap.add_argument("--webhook", help="URL de webhook (Discord/Slack) para alertas de stock")
    args = ap.parse_args()

    state_file = Path.home() / ".stock30th_state.json"
    prev = {}
    if state_file.exists():
        try:
            prev = json.loads(state_file.read_text())
        except json.JSONDecodeError:
            prev = {}

    while True:
        print(f"\n===== Escaneo {datetime.now():%Y-%m-%d %H:%M:%S} =====")
        products = run_scan(only_english=not args.all_langs)
        print_table(products)
        if args.csv and products:
            export_csv(products, args.csv)
        prev = diff_and_alert(prev, products, args.webhook)
        state_file.write_text(json.dumps(prev))

        if not args.watch:
            break
        interval = max(args.watch, 300)
        print(f"[*] Próximo escaneo en {interval} s (Ctrl+C para salir)")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[*] Detenido por el usuario.")
            break


if __name__ == "__main__":
    main()
