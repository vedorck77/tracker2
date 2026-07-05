# 🎴 Pokémon 30th Celebration — Monitor de stock en tiendas chilenas

Script en Python que revisa tiendas chilenas de TCG en busca de productos
**Pokémon TCG: 30th Celebration en inglés**, detectando stock, preventas,
precios e idioma. Puede correr una sola vez, en modo vigilancia continua, o
100% en la nube con GitHub Actions (gratis, sin dejar tu PC encendido).

## Tiendas incluidas

| Tienda | Método |
|---|---|
| Collector Center | Shopify JSON |
| Rey Mago | Shopify JSON |
| Piedrabruja | Shopify JSON |
| Guild Dreams | Shopify JSON |
| The Way | Scraping HTML |
| Geekers | Scraping HTML |
| Santo Games | Scraping HTML |
| Weplay | Scraping HTML |
| La Comarca | Scraping HTML |

Agregar una tienda = agregar un diccionario a la lista `STORES` del script.

## Requisitos

Solo **Python 3.10+** (probado en 3.12) y dos librerías:

```bash
pip install -r requirements.txt
```

Funciona en Windows, macOS y Linux. No necesita nada más.

## Uso local

```bash
# Una pasada, tabla en consola
python monitor_30th_chile.py

# Exportar a CSV (se abre en Excel)
python monitor_30th_chile.py --csv resultados.csv

# Modo vigilancia: revisar cada 15 minutos, alertando stock nuevo
python monitor_30th_chile.py --watch 900

# Alertas al celular vía webhook de Discord o Slack
python monitor_30th_chile.py --watch 900 --webhook https://discord.com/api/webhooks/XXXX

# Incluir también productos en español
python monitor_30th_chile.py --all-langs
```

El script guarda el estado en `~/.stock30th_state.json`, así que las alertas
son solo de productos que **pasan de agotado a disponible** — el evento que
importa cuando se reponen preventas.

## Correrlo gratis en la nube (GitHub Actions) ☁️

La gracia de este repo: no necesitas tener el PC prendido. GitHub ejecuta el
escaneo cada 30 minutos por ti.

1. Crea un repositorio nuevo en GitHub y sube estos archivos:
   ```bash
   git init
   git add .
   git commit -m "Monitor 30th Celebration"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/pokemon-30th-stock-monitor.git
   git push -u origin main
   ```
2. (Opcional pero recomendado) Configura las alertas a Discord:
   - En tu servidor de Discord: *Ajustes del canal → Integraciones → Webhooks → Nuevo webhook → Copiar URL*.
   - En GitHub: *Settings → Secrets and variables → Actions → New repository secret*,
     con nombre `DISCORD_WEBHOOK` y la URL como valor.
3. Ve a la pestaña **Actions** del repo, habilita los workflows y ejecuta
   "Monitor stock 30th Celebration" manualmente la primera vez
   (*Run workflow*) para verificar que todo funciona.

Desde ahí corre solo cada 30 minutos. Cada ejecución deja el CSV de
resultados como artefacto descargable, y si configuraste el webhook te llega
una notificación cuando algo entra en stock.

> Nota: los crons de GitHub Actions pueden atrasarse algunos minutos en horas
> de alta carga. Para vigilancia de segundos-críticos (drops de Pokémon
> Center), complementa con el modo `--watch` local.

## Ajustes frecuentes

- **Solo la Elite Trainer Box**: edita `SEARCH_TERMS` o filtra el CSV por
  título que contenga "elite trainer".
- **Una tienda cambió su web**: si una tienda Shopify deja de responder JSON,
  cámbiala a `"type": "html"` con su URL de buscador. Si una tienda HTML
  devuelve 0 resultados de un día para otro, probablemente rediseñaron el
  sitio y hay que revisar el parser.
- **Agregar tiendas**: copia cualquier entrada de `STORES` y cambia nombre,
  base y URL de búsqueda.

## Uso responsable

El script incluye pausas entre requests, User-Agent identificable e intervalo
mínimo de 5 minutos en modo vigilancia. No lo modifiques para hacer polling
agresivo: además de poco ético, te van a bloquear la IP.

## Licencia

MIT — úsalo, modifícalo y compártelo libremente.
