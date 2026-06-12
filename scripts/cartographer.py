#!/usr/bin/env python3
"""DocFactory Fase 0 — Cartografía determinista del repositorio.

Extrae con parsers (0 tokens LLM):
  - Inventario de símbolos por módulo (verdad de terreno canónica)
  - Grafo de dependencias módulo->módulo (imports)
  - Niveles topológicos (Tarjan SCC -> DAG -> niveles bottom-up)
  - Ranking PageRank de módulos (para el repo map)
  - Manifest de hashes (para actualización incremental)
  - repomap.md con presupuesto de caracteres

Salida en <repo>/.docfactory/
Soporte: Python (ast nativo, completo) | JS/TS (regex, best-effort) | resto (inventario).
Sin dependencias externas. Compatible Python 3.9+.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".docfactory", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
    "site-packages", ".eggs", "coverage", ".next", ".cache",
}
PY_EXT = {".py"}
JS_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
CODE_EXT = PY_EXT | JS_EXT | {
    ".go", ".rs", ".java", ".rb", ".c", ".h", ".cpp", ".hpp", ".cs",
    ".sh", ".sql", ".php", ".swift", ".kt",
}


def list_files(repo):
    """Lista archivos respetando .gitignore vía git; fallback a os.walk."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout
        files = [f for f in out.splitlines() if f.strip()]
    except Exception:
        files = []
        for root, dirs, names in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for n in names:
                files.append(os.path.relpath(os.path.join(root, n), repo))
    result = []
    for f in files:
        parts = f.split(os.sep)
        if any(p in EXCLUDE_DIRS for p in parts):
            continue
        if os.path.splitext(f)[1].lower() in CODE_EXT and os.path.isfile(os.path.join(repo, f)):
            result.append(f)
    return sorted(result)


# ---------------------------------------------------------------- Python AST

def parse_python(repo, relpath):
    """Devuelve (symbols, imports_dotted). imports = nombres dotted importados."""
    full = os.path.join(repo, relpath)
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        tree = ast.parse(src)
    except SyntaxError as e:
        return [], [], "syntax-error: %s" % e
    symbols, imports = [], []

    def sig_of(node):
        try:
            args = ast.unparse(node.args)
        except Exception:
            args = "..."
        ret = ""
        if getattr(node, "returns", None) is not None:
            try:
                ret = " -> " + ast.unparse(node.returns)
            except Exception:
                pass
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return "%s %s(%s)%s" % (prefix, node.name, args, ret)

    def add_symbol(node, kind, parent=None):
        name = node.name if parent is None else "%s.%s" % (parent, node.name)
        doc = ast.get_docstring(node) or ""
        entry = {
            "name": name,
            "kind": kind,
            "line_start": node.lineno,
            "line_end": getattr(node, "end_lineno", node.lineno),
            "doc_firstline": doc.strip().splitlines()[0] if doc.strip() else "",
        }
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entry["signature"] = sig_of(node)
        elif isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    pass
            entry["signature"] = "class %s(%s)" % (node.name, ", ".join(bases))
        symbols.append(entry)

    pkg_parts = relpath.replace("\\", "/").split("/")[:-1]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and node.level > 0:  # import relativo
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                mod = ".".join(base + ([mod] if mod else []))
            for a in node.names:
                imports.append(("%s.%s" % (mod, a.name)) if mod else a.name)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add_symbol(node, "function")
        elif isinstance(node, ast.ClassDef):
            add_symbol(node, "class")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add_symbol(sub, "method", parent=node.name)
                elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                    # campos anotados (dataclass/attrs/pydantic)
                    symbols.append({
                        "name": "%s.%s" % (node.name, sub.target.id),
                        "kind": "attribute", "line_start": sub.lineno,
                        "line_end": getattr(sub, "end_lineno", sub.lineno),
                        "doc_firstline": "",
                    })
                elif isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            symbols.append({
                                "name": "%s.%s" % (node.name, t.id),
                                "kind": "attribute", "line_start": sub.lineno,
                                "line_end": getattr(sub, "end_lineno", sub.lineno),
                                "doc_firstline": "",
                            })
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():  # constantes de módulo
                    symbols.append({
                        "name": t.id, "kind": "constant",
                        "line_start": node.lineno,
                        "line_end": getattr(node, "end_lineno", node.lineno),
                        "doc_firstline": "",
                    })
    return symbols, imports, None


def resolve_python_import(dotted, py_index):
    """Resuelve nombre dotted al módulo del repo: x.y -> x/y.py | x/y/__init__.py.
    Prueba el nombre completo y va recortando el último segmento."""
    parts = dotted.split(".")
    while parts:
        cand = "/".join(parts)
        for suffix in (cand + ".py", cand + "/__init__.py"):
            if suffix in py_index:
                return suffix
        parts = parts[:-1]
    return None


# ---------------------------------------------------------------- JS (regex)

JS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[\w*{}\s,$]+\s+from\s+)?|require\s*\(\s*|import\s*\(\s*)['"]([^'"]+)['"]"""
)
JS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?"
    r"(?:(?:async\s+)?function\s+(\w+)|class\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=)",
    re.MULTILINE,
)


def parse_js(repo, relpath):
    full = os.path.join(repo, relpath)
    with open(full, "r", encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    symbols = []
    for m in JS_SYMBOL_RE.finditer(src):
        name = m.group(1) or m.group(2) or m.group(3)
        kind = "class" if m.group(2) else "function" if m.group(1) else "binding"
        line = src.count("\n", 0, m.start()) + 1
        symbols.append({"name": name, "kind": kind, "line_start": line,
                        "line_end": line, "doc_firstline": ""})
    imports = [m.group(1) for m in JS_IMPORT_RE.finditer(src)]
    return symbols, imports, None


def resolve_js_import(spec, importer, all_files):
    if not spec.startswith("."):
        return None  # paquete externo
    base = os.path.normpath(os.path.join(os.path.dirname(importer), spec)).replace("\\", "/")
    for cand in ([base] + [base + e for e in JS_EXT] +
                 [base + "/index" + e for e in JS_EXT]):
        if cand in all_files:
            return cand
    return None


# ------------------------------------------------------- grafo y topología

def tarjan_scc(nodes, edges):
    """SCCs de Tarjan, iterativo (sin límite de recursión)."""
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    index_of, low, on_stack = {}, {}, set()
    stack, sccs, counter = [], [], [0]

    for root in nodes:
        if root in index_of:
            continue
        work = [(root, 0)]
        while work:
            node, pi = work[-1]
            if pi == 0:
                index_of[node] = low[node] = counter[0]
                counter[0] += 1
                stack.append(node)
                on_stack.add(node)
            advanced = False
            children = adj[node]
            for i in range(pi, len(children)):
                ch = children[i]
                if ch not in index_of:
                    work[-1] = (node, i + 1)
                    work.append((ch, 0))
                    advanced = True
                    break
                elif ch in on_stack:
                    low[node] = min(low[node], index_of[ch])
            if advanced:
                continue
            if low[node] == index_of[node]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    scc.append(w)
                    if w == node:
                        break
                sccs.append(sorted(scc))
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return sccs


def topo_levels(nodes, edges):
    """Condensa ciclos y devuelve niveles: nivel 0 = sin deps internas (hojas)."""
    sccs = tarjan_scc(nodes, edges)
    comp_of = {}
    for i, scc in enumerate(sccs):
        for n in scc:
            comp_of[n] = i
    cedges = set()
    for a, b in edges:
        ca, cb = comp_of[a], comp_of[b]
        if ca != cb:
            cedges.add((ca, cb))  # ca depende de cb
    level = {}

    def comp_level(c, visiting):
        if c in level:
            return level[c]
        visiting.add(c)
        deps = [cb for (ca, cb) in cedges if ca == c]
        lv = 0 if not deps else 1 + max(comp_level(d, visiting) for d in deps)
        level[c] = lv
        return lv

    for c in range(len(sccs)):
        comp_level(c, set())
    max_lv = max(level.values()) if level else 0
    out = [[] for _ in range(max_lv + 1)]
    for c, lv in level.items():
        out[lv].extend(sccs[c])
    cycles = [scc for scc in sccs if len(scc) > 1]
    return [sorted(l) for l in out], cycles


def pagerank(nodes, edges, damping=0.85, iters=40):
    """PageRank sobre A->B (A depende de B): rank alto = muy dependido."""
    out_links = defaultdict(list)
    for a, b in edges:
        out_links[a].append(b)
    n = len(nodes) or 1
    rank = {nd: 1.0 / n for nd in nodes}
    for _ in range(iters):
        nxt = {nd: (1 - damping) / n for nd in nodes}
        for a in nodes:
            targets = out_links.get(a, [])
            if targets:
                share = damping * rank[a] / len(targets)
                for b in targets:
                    nxt[b] = nxt.get(b, 0) + share
            else:
                for nd in nodes:
                    nxt[nd] += damping * rank[a] / n
        rank = nxt
    return rank


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="DocFactory Fase 0: cartografía")
    ap.add_argument("repo", help="ruta al repositorio")
    ap.add_argument("--out", default=None, help="dir de salida (default <repo>/.docfactory)")
    ap.add_argument("--map-chars", type=int, default=16000,
                    help="presupuesto de caracteres del repomap (~tokens*4)")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    out_dir = args.out or os.path.join(repo, ".docfactory")
    os.makedirs(out_dir, exist_ok=True)

    files = list_files(repo)
    all_set = set(files)
    py_index = {f for f in files if f.endswith(".py")}

    modules, edges, errors = {}, set(), {}
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        full = os.path.join(repo, f)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                n_lines = sum(1 for _ in fh)
        except OSError:
            continue
        lang = ("python" if ext in PY_EXT else
                "javascript" if ext in JS_EXT else ext.lstrip("."))
        symbols, raw_imports, err = [], [], None
        if ext in PY_EXT:
            symbols, raw_imports, err = parse_python(repo, f)
            for imp in raw_imports:
                tgt = resolve_python_import(imp, py_index)
                if tgt and tgt != f:
                    edges.add((f, tgt))
        elif ext in JS_EXT:
            symbols, raw_imports, err = parse_js(repo, f)
            for imp in raw_imports:
                tgt = resolve_js_import(imp, f, all_set)
                if tgt and tgt != f:
                    edges.add((f, tgt))
        if err:
            errors[f] = err
        modules[f] = {"lang": lang, "lines": n_lines, "symbols": symbols}

    levels, cycles = topo_levels(files, edges)
    ranks = pagerank(files, edges)

    # manifest (hash por archivo) para modo incremental
    manifest = {}
    for f in files:
        h = hashlib.sha256()
        with open(os.path.join(repo, f), "rb") as fh:
            h.update(fh.read())
        manifest[f] = h.hexdigest()

    # repomap.md con presupuesto
    ranked = sorted(files, key=lambda f: -ranks.get(f, 0))
    dependents = defaultdict(int)
    for a, b in edges:
        dependents[b] += 1
    lines, used = ["# Repo map (rankeado por centralidad)\n"], 0
    for f in ranked:
        m = modules[f]
        head = "\n## %s  [%s, %d líneas, %d dependientes]\n" % (
            f, m["lang"], m["lines"], dependents[f])
        body = ""
        for s in m["symbols"][:40]:
            sig = s.get("signature", "%s %s" % (s["kind"], s["name"]))
            doc = ("  # " + s["doc_firstline"][:80]) if s["doc_firstline"] else ""
            body += "  %s:%d %s%s\n" % (f, s["line_start"], sig, doc)
        chunk = head + body
        if used + len(chunk) > args.map_chars:
            lines.append("\n... (%d módulos más omitidos por presupuesto)\n"
                         % (len(ranked) - ranked.index(f)))
            break
        lines.append(chunk)
        used += len(chunk)

    def dump(name, obj):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, ensure_ascii=False, sort_keys=True)

    dump("symbols.json", modules)
    dump("graph.json", {"edges": sorted(edges)})
    dump("levels.json", {"levels": levels, "cycles": cycles})
    dump("manifest.json", manifest)
    dump("summary.json", {
        "repo": repo, "n_files": len(files), "n_edges": len(edges),
        "n_levels": len(levels), "n_cycles": len(cycles),
        "n_symbols": sum(len(m["symbols"]) for m in modules.values()),
        "parse_errors": errors,
        "top10_central": [(f, round(ranks.get(f, 0), 5)) for f in ranked[:10]],
    })
    with open(os.path.join(out_dir, "repomap.md"), "w", encoding="utf-8") as fh:
        fh.write("".join(lines))

    print(json.dumps({
        "ok": True, "out": out_dir, "files": len(files), "edges": len(edges),
        "levels": [len(l) for l in levels], "cycles": len(cycles),
        "symbols": sum(len(m["symbols"]) for m in modules.values()),
        "parse_errors": len(errors),
    }, indent=1))


if __name__ == "__main__":
    main()
