---
name: docfactory
description: Genera documentación completa, verificada y sin alucinaciones de cualquier repositorio, publicada como sitio Docsify. Pipeline de 5 fases — cartografía determinista (AST), documentación bottom-up por niveles topológicos con subagentes paralelos, verificación mecánica de citas, síntesis de arquitectura con Mermaid, y modo incremental. Úsala cuando el usuario pida documentar un proyecto/repo/sistema, generar docs, crear una wiki del código, o actualizar documentación existente de DocFactory.
---

# DocFactory — documentación de sistemas verificada y eficiente en tokens

Genera la documentación completa de un repositorio como sitio **Docsify**, con
garantía anti-alucinación: toda afirmación factual lleva cita `[archivo:líneas]`
verificada mecánicamente contra el código real.

**Scripts** (en `scripts/` junto a este archivo; todos son Python 3 sin dependencias):

| Script | Fase | Función |
|---|---|---|
| `cartographer.py <repo>` | 0 | AST → símbolos, grafo deps, niveles topológicos, repomap, manifest |
| `verify.py --repo <repo> --docs <dir\|md>` | 2 | Valida citas (gate duro), existence ratio, cobertura |
| `scaffold_docsify.py --docs-dir <dir> --name <n>` | 3 | Esqueleto Docsify (index.html, _sidebar, .nojekyll) |

## Principios innegociables

1. **Estructura por parser, prosa por LLM.** Nunca afirmes qué existe en el repo: eso lo dice `.docfactory/symbols.json`. Tú/los subagentes solo redactan prosa sobre lo que el parser encontró.
2. **Toda afirmación factual lleva cita** en formato `[ruta/archivo.ext:inicio-fin]` (líneas reales). Sin cita verificable → la afirmación se reescribe o se elimina. Nunca se publica.
3. **Lo no encontrado no se documenta.** Prohibido rellenar huecos con conocimiento genérico ("este módulo probablemente..."). Los huecos se declaran en una sección "Límites de esta documentación".
4. **Bottom-up estricto:** un módulo se documenta solo cuando sus dependencias ya tienen doc. El contexto de cada subagente = su código + los RESÚMENES de sus deps (no su código).
5. **Síntesis de alto nivel solo desde resúmenes verificados**, nunca releyendo código bruto.
6. **Verificación es código, no LLM.** El gate es `verify.py`; un LLM nunca se auto-aprueba.

## Procedimiento

### Fase 0 — Cartografía (determinista)

```bash
python3 <skill_dir>/scripts/cartographer.py <repo_abs>
```

Lee `.docfactory/summary.json` (stats, top módulos centrales, errores de parseo) y
`.docfactory/levels.json`. Si hay `parse_errors`, decláralos como huecos en Fase 3.
Lee `.docfactory/repomap.md` UNA vez: es tu vista global del sistema (presupuesto fijo).

Pregunta al usuario solo si no es obvio: dónde publicar (`<repo>/docs` por defecto)
y si hay áreas a excluir (p.ej. `analysis/` exploratorio, vendored code).

### Fase 1 — Documentación bottom-up (subagentes paralelos)

Agrupa módulos en **unidades de documentación** (un paquete/directorio cohesivo o un
módulo grande = 1 unidad; scripts triviales se agrupan). Para repos pequeños (<30
archivos) puedes documentar tú directamente sin subagentes, nivel a nivel.

Procesa niveles de `levels.json` en orden (0 → N). Dentro de un nivel, lanza
subagentes Explore/general-purpose **en paralelo** (lotes de 3-5). Contrato de
subagente (prompt):

```
Documenta el módulo <X> del repo <ruta>. Lee SOLO: (a) el código de <X>,
(b) estos resúmenes de sus dependencias ya documentadas: <resúmenes ≤150 tokens c/u>.

REGLAS DURAS:
- Toda afirmación factual sobre el código lleva cita [ruta:inicio-fin] con
  números de línea REALES del archivo que leíste.
- Identificadores de código siempre `entre backticks`.
- Si algo no se puede determinar leyendo el código, NO lo afirmes: anótalo en
  la sección "No verificado".
- No describas comportamiento de dependencias más allá de sus resúmenes.

ENTREGA (texto plano, nada más):
1. Página markdown completa empezando con <!-- docfactory:module=<ruta> -->
   Secciones: Propósito · API/símbolos principales (tabla con citas) ·
   Flujo/lógica clave · Dependencias (qué usa y para qué) · No verificado.
2. Al final, separado por la línea "===RESUMEN===": resumen de ≤150 tokens
   del módulo (qué es, qué expone, de qué depende) para documentar a sus dependientes.
```

Guarda cada página en `<docs>/modules/<ruta-con-guiones>.md` y cada resumen en
`.docfactory/summaries/<ruta-con-guiones>.txt` (créalo). Los resúmenes alimentan
los niveles superiores — no pases nunca código de un módulo a otro subagente.

### Fase 2 — Verificación (gate duro)

```bash
python3 <skill_dir>/scripts/verify.py --repo <repo> --docs <docs>/modules
```

- `citations_invalid` > 0 → reenvía al subagente SOLO la página y los errores
  concretos para corregir (1 retry). Si reincide: elimina la afirmación no
  verificable y anótala en "Límites".
- `existence_ratio` < 0.98 en una página → revisa `unknown_symbols`: o es un
  símbolo mal escrito (corrige) o es invención (elimina).
- `coverage.ratio` bajo → decide si los símbolos faltantes son relevantes
  (documenta) o triviales (acepta y sigue).

No pases a Fase 3 con `"ok": false`.

### Fase 3 — Síntesis y sitio Docsify

```bash
python3 <skill_dir>/scripts/scaffold_docsify.py --docs-dir <docs> --name "<Proyecto>" --repo-url "<url-si-existe>"
```

Con SOLO los resúmenes de `.docfactory/summaries/` + `graph.json` + `summary.json`,
redacta (tú, modelo principal — esto requiere visión global):

- `<docs>/README.md` — home: qué es el sistema, mapa mental, cómo navegar la doc.
- `<docs>/architecture.md` — visión de arquitectura con diagramas **Mermaid**
  (```mermaid en fences). El diagrama de componentes se valida: cada nodo/arista
  debe corresponder a módulos/aristas reales de `graph.json`. No dibujes cajas
  que no existan.
- `<docs>/getting-started.md` — setup/ejecución SOLO si hay evidencia citada
  (README existente, Makefile, package.json, requirements, etc.).
- `<docs>/_sidebar.md` — navegación completa: Inicio, Arquitectura, Getting
  started, y módulos agrupados por directorio (usa títulos legibles).
- Sección final en README: **"Límites de esta documentación"** — huecos
  declarados, parse_errors, áreas excluidas, fecha de generación y commit
  (`git rev-parse --short HEAD`).

Re-ejecuta `verify.py` sobre `<docs>` completo (gate final). Ofrece previsualizar:
`python3 -m http.server 3000 --directory <docs>`.

### Fase 4 — Modo incremental (si ya existe `.docfactory/manifest.json` previo)

Si el usuario pide actualizar docs existentes:

1. Guarda el manifest viejo, re-ejecuta `cartographer.py`, compara hashes.
2. Cambiados/nuevos/borrados → conjunto afectado; expándelo con dependientes
   directos (1 hop en `graph.json` invertido).
3. Re-ejecuta Fases 1-3 SOLO sobre ese conjunto (los resúmenes del resto siguen
   válidos). Borra páginas de módulos eliminados y actualiza `_sidebar.md`.

## Presupuesto y modelos

- Subagentes de Fase 1 en niveles bajos: usa `model: haiku` si las unidades son
  simples; `sonnet` para módulos centrales (top PageRank). Fase 3 siempre con el
  modelo principal de la sesión.
- No releas archivos ya documentados. No pases el repomap completo a subagentes
  (solo los resúmenes de deps + su propio código).

## Reporte final al usuario

Resume: páginas generadas, citas totales y % válidas (debe ser 100%), existence
ratio medio, cobertura media, huecos declarados, tokens aproximados, y cómo servir
el sitio.
