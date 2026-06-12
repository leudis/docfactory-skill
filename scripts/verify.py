#!/usr/bin/env python3
"""DocFactory Fase 2 — Verificación mecánica (0 tokens LLM).

Valida documentación generada contra la verdad de terreno de Fase 0:

  1. CITAS [path:a-b] o [path:a]  -> el archivo existe y el rango es válido
     (aritmética de intervalos contra el repo REAL). Gate duro: 100% o falla.
  2. EXISTENCE RATIO  -> identificadores `entre backticks` que parecen símbolos
     de código se cruzan contra symbols.json. Gate blando: reporta desconocidos.
  3. COBERTURA -> páginas con marcador <!-- docfactory:module=path --> reportan
     % de símbolos públicos del módulo mencionados en la doc.

Salida JSON por stdout. Exit code 1 si hay citas inválidas (gate duro).
Uso: verify.py --repo <repo> --docs <dir|archivo.md> [--df <repo>/.docfactory]
"""
import argparse
import json
import os
import re
import subprocess
import sys

CITE_RE = re.compile(r"\[([\w][\w./ -]*\.[A-Za-z0-9_]{1,8}):(\d+)(?:-(\d+))?\]")
TICK_RE = re.compile(r"`([^`\n]{2,80})`")
MODULE_MARK_RE = re.compile(r"<!--\s*docfactory:module=([^\s>]+)\s*-->")
# identificadores que parecen símbolos de código (snake_case, CamelCase, llamadas, dotted)
IDENT_RE = re.compile(r"^[A-Za-z_][\w.]*(\(\))?$")
COMMON_FALSE_POSITIVES = {
    # términos genéricos que suelen ir en backticks sin ser símbolos del repo
    "true", "false", "none", "null", "json", "yaml", "api", "http", "https",
    "get", "post", "put", "delete", "main", "init", "self", "cls", "str",
    "int", "float", "bool", "dict", "list", "tuple", "set", "async", "await",
    "python", "javascript", "typescript", "bash", "git", "docker", "sql",
    "readme", "todo", "args", "kwargs", "stdin", "stdout", "stderr", "utf-8",
}


def load_ground_truth(df_dir):
    with open(os.path.join(df_dir, "symbols.json"), encoding="utf-8") as fh:
        modules = json.load(fh)
    known = set()
    for mod, info in modules.items():
        known.add(mod)                                # ruta del módulo
        known.add(os.path.basename(mod))              # nombre de archivo
        base = os.path.splitext(os.path.basename(mod))[0]
        known.add(base)                               # nombre sin extensión
        for s in info.get("symbols", []):
            known.add(s["name"])                      # Clase.metodo y nombre pleno
            if "." in s["name"]:
                known.add(s["name"].split(".")[-1])   # solo el método
    return modules, known


def textual_exists(token, repo, cache):
    """Fallback: el token aparece textualmente en el código del repo (git grep -F).
    Cubre atributos de instancia, claves string y nombres no indexados por AST."""
    base = token.rstrip("()").split(".")[-1]
    if base in cache:
        return cache[base]
    try:
        rc = subprocess.run(["git", "grep", "-F", "-q", base, "--", "*.py", "*.js",
                             "*.ts", "*.sh", "*.json", "*.yaml", "*.yml"],
                            cwd=repo, capture_output=True).returncode
        found = rc == 0
    except Exception:
        found = False
    cache[base] = found
    return found


def file_line_count(repo, relpath, cache):
    if relpath in cache:
        return cache[relpath]
    full = os.path.join(repo, relpath)
    n = None
    if os.path.isfile(full):
        try:
            with open(full, "rb") as fh:
                n = sum(1 for _ in fh)
        except OSError:
            n = None
    cache[relpath] = n
    return n


def looks_like_symbol(token):
    t = token.strip()
    if not IDENT_RE.match(t):
        return False
    base = t.rstrip("()").lower()
    if base in COMMON_FALSE_POSITIVES:
        return False
    # exige señal de identificador real: _, punto, paréntesis o CamelCase
    has_signal = ("_" in t or "." in t or t.endswith("()")
                  or (t[0].isupper() and any(c.islower() for c in t) and len(t) > 2))
    return has_signal


def verify_file(md_path, repo, modules, known, line_cache, grep_cache):
    with open(md_path, encoding="utf-8") as fh:
        text = fh.read()

    # 1. citas mecánicas
    citations, bad_citations = [], []
    for m in CITE_RE.finditer(text):
        rel, a, b = m.group(1).strip(), int(m.group(2)), m.group(3)
        b = int(b) if b else a
        n = file_line_count(repo, rel, line_cache)
        entry = {"cite": m.group(0), "file": rel, "start": a, "end": b}
        if n is None:
            entry["error"] = "archivo no existe"
            bad_citations.append(entry)
        elif not (1 <= a <= b <= n):
            entry["error"] = "rango inválido (archivo tiene %d líneas)" % n
            bad_citations.append(entry)
        else:
            citations.append(entry)

    # 2. existence ratio sobre identificadores en backticks
    #    cruce AST primero; fallback textual (git grep) para atributos de
    #    instancia, claves string y nombres no indexados por el parser
    mentioned, unknown, textual = set(), set(), set()
    for m in TICK_RE.finditer(text):
        tok = m.group(1).strip()
        if not looks_like_symbol(tok):
            continue
        norm = tok.rstrip("()")
        mentioned.add(norm)
        if norm not in known and norm.split(".")[-1] not in known:
            if textual_exists(norm, repo, grep_cache):
                textual.add(tok)
            else:
                unknown.add(tok)
    er = (len(mentioned) - len(unknown)) / len(mentioned) if mentioned else 1.0

    # 3. cobertura si la página declara su módulo
    coverage = None
    mm = MODULE_MARK_RE.search(text)
    if mm and mm.group(1) in modules:
        mod = mm.group(1)
        pub = [s["name"] for s in modules[mod]["symbols"]
               if not s["name"].split(".")[-1].startswith("_")
               and s["kind"] in ("function", "class", "method")]
        if pub:
            body_norms = {x.split(".")[-1] for x in mentioned} | mentioned
            covered = [p for p in pub
                       if p in body_norms or p.split(".")[-1] in body_norms]
            coverage = {"module": mod, "public_symbols": len(pub),
                        "covered": len(covered),
                        "ratio": round(len(covered) / len(pub), 3),
                        "missing": sorted(set(pub) - set(covered))[:30]}

    return {
        "file": md_path,
        "citations_total": len(citations) + len(bad_citations),
        "citations_invalid": bad_citations,
        "existence_ratio": round(er, 4),
        "symbols_checked": len(mentioned),
        "verified_textual": sorted(textual),
        "unknown_symbols": sorted(unknown),
        "coverage": coverage,
    }


def main():
    ap = argparse.ArgumentParser(description="DocFactory Fase 2: verificación")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--docs", required=True, help="dir o archivo .md a verificar")
    ap.add_argument("--df", default=None, help="dir .docfactory (default <repo>/.docfactory)")
    ap.add_argument("--min-er", type=float, default=0.98,
                    help="existence ratio mínimo (gate blando, default 0.98)")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    df_dir = args.df or os.path.join(repo, ".docfactory")
    modules, known = load_ground_truth(df_dir)

    targets = []
    if os.path.isdir(args.docs):
        for root, dirs, names in os.walk(args.docs):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            targets += [os.path.join(root, n) for n in names if n.endswith(".md")]
    else:
        targets = [args.docs]

    line_cache, grep_cache = {}, {}
    reports = [verify_file(t, repo, modules, known, line_cache, grep_cache)
               for t in sorted(targets)]
    n_bad = sum(len(r["citations_invalid"]) for r in reports)
    n_cites = sum(r["citations_total"] for r in reports)
    low_er = [r["file"] for r in reports
              if r["symbols_checked"] >= 5 and r["existence_ratio"] < args.min_er]

    print(json.dumps({
        "ok": n_bad == 0,
        "files_checked": len(reports),
        "citations_total": n_cites,
        "citations_invalid_total": n_bad,
        "files_below_min_er": low_er,
        "reports": reports,
    }, indent=1, ensure_ascii=False))
    sys.exit(1 if n_bad else 0)


if __name__ == "__main__":
    main()
