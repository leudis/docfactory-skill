# DocFactory — skill de documentación verificada para Claude Code

Genera la documentación completa de cualquier repositorio de software como sitio **Docsify**, con garantía anti-alucinación: toda afirmación factual lleva cita `[archivo:líneas]` verificada mecánicamente contra el código real.

Diseñada para Claude Code. Reutilizable en cualquier proyecto, lenguaje y tamaño.

---

## Instalación

```bash
git clone https://github.com/leudis/docfactory-skill ~/.claude/skills/docfactory

# Para actualizar a la última versión
cd ~/.claude/skills/docfactory && git pull
```

Claude Code descubre la skill automáticamente. En tu próxima sesión estará disponible como `/docfactory`.

## Uso

```
/docfactory <ruta-al-repo>
```

Ejemplo:
```
/docfactory /home/user/mi-proyecto
```

La skill genera la documentación en `<repo>/docs/` como sitio Docsify listo para servir:

```bash
python3 -m http.server 3000 --directory <repo>/docs
```

---

## Qué genera

```
docs/
  index.html          ← Docsify 4 + búsqueda + Mermaid + copy-code (CDN, sin build)
  README.md           ← home: mapa del sistema, tabla de componentes
  architecture.md     ← diagramas Mermaid validados contra el código real
  getting-started.md  ← setup y variables de entorno con citas reales
  _sidebar.md         ← navegación completa
  modules/            ← una página por módulo/paquete, con citas verificadas
```

---

## Arquitectura (5 fases)

| Fase | Herramienta | Qué hace | Tokens LLM |
|---|---|---|---|
| **0. Cartografía** | `scripts/cartographer.py` | AST → símbolos, grafo de dependencias, niveles topológicos (Tarjan), PageRank, repomap con presupuesto, manifest de hashes | **0** |
| **1. Documentación** | Subagentes paralelos | Bottom-up por nivel topológico; contexto = código propio + resúmenes de dependencias; citas obligatorias | Mínimo (acotado por módulo) |
| **2. Verificación** | `scripts/verify.py` | Gate duro: citas `[file:a-b]` contra repo real, existence ratio ≥0.98, cobertura de símbolos públicos | **0** |
| **3. Síntesis** | Modelo principal + `scripts/scaffold_docsify.py` | README, architecture.md (Mermaid validado), getting-started, _sidebar | Pocas llamadas |
| **4. Incremental** | `scripts/cartographer.py` + manifest | git diff → regenera solo lo afectado | Proporcional al cambio |

### Principios anti-alucinación

1. **Estructura por parser, prosa por LLM** — el LLM nunca "descubre" qué existe; eso lo dice el AST.
2. **Toda afirmación factual lleva cita** `[ruta:inicio-fin]` verificada mecánicamente (script, no LLM).
3. **Lo no encontrado no se documenta** — los huecos se declaran explícitamente en vez de inventarse.
4. **Orden topológico bottom-up** — cada módulo se documenta solo cuando sus dependencias ya tienen doc.
5. **Verificación es código, no LLM** — el gate `verify.py` usa aritmética de intervalos y git grep.

---

## Scripts incluidos

### `scripts/cartographer.py`

```bash
python3 scripts/cartographer.py <repo>
# Salida en <repo>/.docfactory/
```

Genera en `.docfactory/`:
- `symbols.json` — inventario completo de símbolos por módulo
- `graph.json` — grafo de dependencias (aristas módulo→módulo)
- `levels.json` — niveles topológicos (Tarjan SCC + DAG)
- `repomap.md` — vista comprimida con presupuesto fijo de caracteres
- `manifest.json` — hashes SHA-256 por archivo (para modo incremental)
- `summary.json` — estadísticas y top módulos por PageRank

Soporte: **Python** (AST nativo, completo) · **JS/TS** (regex, best-effort) · otros lenguajes (inventario de archivos).
Sin dependencias externas. Compatible Python 3.9+.

### `scripts/verify.py`

```bash
python3 scripts/verify.py --repo <repo> --docs <dir|archivo.md>
# Exit code 1 si hay citas inválidas (gate duro)
```

Valida:
1. **Citas mecánicas** `[file:a-b]` — el archivo existe y el rango es válido (100% precisión, 0 tokens)
2. **Existence Ratio** — identificadores en backticks cruzados contra `symbols.json` + git grep fallback
3. **Cobertura** — % de símbolos públicos documentados (cuando la página declara `<!-- docfactory:module=ruta -->`)

### `scripts/scaffold_docsify.py`

```bash
python3 scripts/scaffold_docsify.py --docs-dir <dir> --name "Mi Proyecto" [--repo-url URL]
```

Crea el esqueleto Docsify (idempotente, nunca sobreescribe markdown existente):
- `index.html` con Docsify 4 CDN, búsqueda, Mermaid, copy-code
- `.nojekyll` para GitHub Pages
- `_sidebar.md` y `README.md` placeholder

---

## Requisitos

- Python 3.9+ (sin dependencias externas — solo stdlib)
- Claude Code con acceso a herramientas de lectura/escritura
- Git (para `list_files` con respeto a `.gitignore`)

## Resultados demostrados

Probado sobre el repositorio [btc1h](https://github.com/leudis/btc1h) (bot de trading, Python, 157 archivos, ~30k LOC):

- 21 páginas generadas
- **944 citas verificadas, 0 inválidas**
- Existence Ratio medio: 0.965 (mín 0.958)
- 0 símbolos alucinados publicados
- Estimación de consumo: ~2-4M tokens (mayoría en modelo pequeño)

---

## Créditos

Diseño basado en el estudio de literatura académica (DocAgent ACL 2025, ArchAgent arXiv 2026, Code-Craft arXiv 2025, Citation-Grounded Code Comprehension arXiv 2025, Aider repo map). Ver [`analysis/estudio_agente_documentacion_2026-06-11.md`](https://github.com/leudis/btc1h/blob/main/analysis/estudio_agente_documentacion_2026-06-11.md) para el estudio completo.
