#!/usr/bin/env python3
"""DocFactory — esqueleto de sitio Docsify para la documentación generada.

Crea en <docs-dir>:
  index.html    (Docsify 4 CDN + búsqueda + Mermaid + copy-code + tema)
  .nojekyll     (para GitHub Pages)
  _sidebar.md   (placeholder si no existe; la skill lo rellena en Fase 3)
  README.md     (placeholder si no existe; home del sitio)

Idempotente: nunca sobreescribe contenido markdown existente.
Uso: scaffold_docsify.py --docs-dir <repo>/docs --name "Proyecto" [--description "..."] [--repo-url URL]
"""
import argparse
import os

INDEX_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>{name} — Documentación</title>
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, minimum-scale=1.0">
  <meta name="description" content="{description}">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/docsify@4/lib/themes/vue.css">
  <style>
    :root {{ --theme-color: #2c7be5; }}
    .markdown-section code {{ font-size: 0.85em; }}
    .sidebar-nav li a {{ font-size: 14px; }}
    .markdown-section {{ max-width: 900px; }}
  </style>
</head>
<body>
  <div id="app">Cargando documentación…</div>
  <script>
    window.$docsify = {{
      name: '{name}',
      repo: '{repo_url}',
      loadSidebar: true,
      subMaxLevel: 3,
      auto2top: true,
      search: {{
        placeholder: 'Buscar…',
        noData: 'Sin resultados',
        depth: 4
      }},
      copyCode: {{ buttonText: 'Copiar', successText: 'Copiado' }},
      notFoundPage: true
    }};
  </script>
  <script src="https://cdn.jsdelivr.net/npm/docsify@4"></script>
  <script src="https://cdn.jsdelivr.net/npm/docsify@4/lib/plugins/search.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/docsify-copy-code@2"></script>
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-python.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-bash.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-json.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/docsify-mermaid@2/dist/docsify-mermaid.js"></script>
  <script>mermaid.initialize({{ startOnLoad: true, theme: 'neutral' }});</script>
</body>
</html>
"""

SIDEBAR_PLACEHOLDER = """<!-- _sidebar.md — generado por DocFactory; se rellena en Fase 3 -->
* [Inicio](/)
"""

README_PLACEHOLDER = """# {name}

> Documentación generada por DocFactory. Pendiente de Fase 3 (síntesis).
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs-dir", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--description", default="Documentación del sistema")
    ap.add_argument("--repo-url", default="")
    args = ap.parse_args()

    os.makedirs(args.docs_dir, exist_ok=True)
    created = []

    index = os.path.join(args.docs_dir, "index.html")
    with open(index, "w", encoding="utf-8") as fh:
        fh.write(INDEX_HTML.format(name=args.name, description=args.description,
                                   repo_url=args.repo_url))
    created.append("index.html")

    nojekyll = os.path.join(args.docs_dir, ".nojekyll")
    if not os.path.exists(nojekyll):
        open(nojekyll, "w").close()
        created.append(".nojekyll")

    for fname, content in (("_sidebar.md", SIDEBAR_PLACEHOLDER),
                           ("README.md", README_PLACEHOLDER.format(name=args.name))):
        path = os.path.join(args.docs_dir, fname)
        if not os.path.exists(path):  # nunca pisar contenido existente
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            created.append(fname)

    print("Scaffold Docsify listo en %s — creados: %s" % (args.docs_dir, ", ".join(created)))
    print("Previsualizar con: python3 -m http.server 3000 --directory %s" % args.docs_dir)


if __name__ == "__main__":
    main()
