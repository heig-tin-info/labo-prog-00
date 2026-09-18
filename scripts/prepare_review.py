#!/usr/bin/env python3
"""Prépare dans build/ les entrées de la revue LLM (cible `make prepare`).

Le correcteur automatique ne lit que des fichiers texte. Ce script produit :

- build/rapport.md : le rapport Word extrait en texte, avec ses styles et
  l'emplacement de ses images ;
- build/inventaire.txt : les fichiers publiés dans Git, le contenu de rendu/,
  les métadonnées du document Word et l'historique des commits.

Il ne renvoie jamais un code d'erreur : le CI l'exécute avant les tests et un
rapport absent ou illisible doit être constaté par les tests, pas bloquer le
pipeline.
"""

from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDU = ROOT / "rendu"
BUILD = ROOT / "build"

sys.path.insert(0, str(ROOT / "scripts"))
import rendu_docx  # noqa: E402


def git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.rstrip()}\n\n"


def tracked_files() -> str:
    output = git("ls-files")
    if output is None:
        return "(pas de dépôt Git : liste du disque)\n" + "\n".join(
            str(p.relative_to(ROOT))
            for p in sorted(ROOT.rglob("*"))
            if p.is_file() and ".git" not in p.parts and "build" not in p.parts
        )
    return output


def rendu_listing() -> str:
    if not RENDU.is_dir():
        return "(le dossier rendu/ n'existe pas)"
    rows = []
    for path in sorted(RENDU.rglob("*")):
        kind = "dossier" if path.is_dir() else f"{path.stat().st_size} octets"
        rows.append(f"{path.relative_to(RENDU)}  ({kind})")
    return "\n".join(rows) or "(vide)"


def report() -> tuple[str, str]:
    """Retourne (rapport.md, résumé pour l'inventaire)."""
    path = RENDU / "rapport.docx"
    if not path.is_file():
        return "(rendu/rapport.docx est absent)\n", "rendu/rapport.docx absent"
    try:
        doc = rendu_docx.load(path)
    except rendu_docx.DocxError as exc:
        message = f"rendu/rapport.docx illisible : {exc}"
        return f"({message})\n", message

    words = len(doc.text.split())
    props = "\n".join(f"{k} : {v}" for k, v in doc.properties.items()) or "(aucune)"
    headline = f"rapport lu : {len(doc.paragraphs)} paragraphes, {words} mots, {len(doc.images)} images"
    styles = "\n".join(f"{name} : {n}" for name, n in sorted(doc.style_usage().items()))
    images = "\n".join(f"{name} : {size / 1024:.0f} ko" for name, size in doc.images.items())
    summary = (
        f"{headline}\n\nMétadonnées :\n{props}\n\n"
        f"Paragraphes : {len(doc.paragraphs)}, mots : {words}\n\n"
        f"Styles utilisés :\n{styles}\n\n"
        f"Images ({len(doc.images)}) :\n{images or '(aucune)'}"
    )
    return rendu_docx.to_markdown(doc), summary


def history() -> str:
    log = git("log", "--date=short", "--format=%h  %ad  %an <%ae>  %s")
    if log is None:
        return "(pas de dépôt Git)"
    shallow = (git("rev-parse", "--is-shallow-repository") or "").strip() == "true"
    note = "\n(clone superficiel : seuls les derniers commits sont visibles)" if shallow else ""
    return log + note


def main() -> None:
    BUILD.mkdir(exist_ok=True)
    rapport_md, rapport_summary = report()
    (BUILD / "rapport.md").write_text(rapport_md, encoding="utf-8")

    inventory = (
        "# Inventaire du dépôt\n\n"
        + section("Fichiers publiés dans Git", tracked_files())
        + section("Contenu de rendu/", rendu_listing())
        + section("Rapport Word", rapport_summary)
        + section("Historique Git", history())
    )
    (BUILD / "inventaire.txt").write_text(inventory, encoding="utf-8")
    print(f"build/rapport.md et build/inventaire.txt écrits ({rapport_summary.splitlines()[0]})")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - jamais bloquer le pipeline
        traceback.print_exc()
        print("prepare_review : erreur ignorée, la revue se fera sans ces fichiers")
