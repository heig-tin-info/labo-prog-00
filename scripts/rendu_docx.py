"""Lecture minimale d'un document Word (.docx) avec la bibliothèque standard.

Un fichier .docx est une archive zip : le texte est dans word/document.xml,
les styles dans word/styles.xml, les images dans word/media/ et les
métadonnées dans docProps/core.xml. Ce module est partagé par les tests
(tests/test_rendu.py) et par scripts/prepare_review.py, sans dépendance
externe.

Les identifiants de style de Word dépendent de la langue (« Titre1 » en
français, « Heading1 » en anglais), mais leur nom canonique ne change pas
(« heading 1 », « Title », « Subtitle ») : c'est ce nom que l'on expose.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf"}


class DocxError(Exception):
    """Le fichier n'est pas un document Word exploitable."""


@dataclass
class Paragraph:
    style: str
    text: str
    images: list[str] = field(default_factory=list)


@dataclass
class Document:
    paragraphs: list[Paragraph]
    media: dict[str, int]
    properties: dict[str, str]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)

    @property
    def images(self) -> dict[str, int]:
        return {
            name: size
            for name, size in self.media.items()
            if Path(name).suffix.lower() in IMAGE_EXTENSIONS
        }

    def with_style(self, name: str) -> list[Paragraph]:
        wanted = name.casefold()
        return [p for p in self.paragraphs if p.style.casefold() == wanted]

    def style_usage(self) -> dict[str, int]:
        usage: dict[str, int] = {}
        for p in self.paragraphs:
            usage[p.style] = usage.get(p.style, 0) + 1
        return usage


def _tag(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def _style_names(archive: zipfile.ZipFile) -> dict[str, str]:
    """Associe chaque identifiant de style à son nom canonique."""
    if "word/styles.xml" not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read("word/styles.xml"))
    names: dict[str, str] = {}
    for style in root.iter(_tag("w", "style")):
        style_id = style.get(_tag("w", "styleId"))
        name = style.find("w:name", NS)
        if style_id and name is not None:
            names[style_id] = name.get(_tag("w", "val"), style_id)
    return names


def _relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    """Associe chaque identifiant de relation au chemin de sa cible."""
    path = "word/_rels/document.xml.rels"
    if path not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read(path))
    rels: dict[str, str] = {}
    for rel in root.iter(_tag("pr", "Relationship")):
        rid, target = rel.get("Id"), rel.get("Target", "")
        if rid and target:
            rels[rid] = target if target.startswith("/") else f"word/{target}"
    return {rid: t.lstrip("/") for rid, t in rels.items()}


def _properties(archive: zipfile.ZipFile) -> dict[str, str]:
    if "docProps/core.xml" not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read("docProps/core.xml"))
    wanted = {
        "creator": "dc:creator",
        "lastModifiedBy": "cp:lastModifiedBy",
        "created": "dcterms:created",
        "modified": "dcterms:modified",
        "title": "dc:title",
    }
    props: dict[str, str] = {}
    for key, xpath in wanted.items():
        node = root.find(xpath, NS)
        if node is not None and node.text:
            props[key] = node.text.strip()
    return props


def _paragraph_text(p: ET.Element) -> str:
    parts: list[str] = []
    for node in p.iter():
        if node.tag == _tag("w", "t"):
            parts.append(node.text or "")
        elif node.tag == _tag("w", "tab"):
            parts.append("\t")
        elif node.tag in (_tag("w", "br"), _tag("w", "cr")):
            parts.append("\n")
    return "".join(parts)


def load(path: str | Path) -> Document:
    """Charge un .docx ; lève DocxError si le fichier n'en est pas un."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocxError(f"archive zip illisible : {exc}") from exc

    with archive:
        names = set(archive.namelist())
        if "word/document.xml" not in names:
            raise DocxError("word/document.xml absent de l'archive")
        try:
            root = ET.fromstring(archive.read("word/document.xml"))
        except ET.ParseError as exc:
            raise DocxError(f"word/document.xml illisible : {exc}") from exc

        styles = _style_names(archive)
        rels = _relationships(archive)
        body = root.find("w:body", NS)
        if body is None:
            raise DocxError("corps du document absent")

        # Les objets de compatibilité (mc:AlternateContent) dupliquent leur
        # contenu dans une branche Fallback : on ne lit que la branche Choice.
        parents = {child: parent for parent in root.iter() for child in parent}

        def in_fallback(node: ET.Element) -> bool:
            while node in parents:
                node = parents[node]
                if node.tag == _tag("mc", "Fallback"):
                    return True
            return False

        paragraphs: list[Paragraph] = []
        for p in body.iter(_tag("w", "p")):
            if in_fallback(p):
                continue
            style_node = p.find("w:pPr/w:pStyle", NS)
            style_id = style_node.get(_tag("w", "val")) if style_node is not None else None
            style = styles.get(style_id, style_id) if style_id else "Normal"
            images = []
            for blip in p.iter(_tag("a", "blip")):
                target = rels.get(blip.get(_tag("r", "embed"), ""))
                if target:
                    images.append(target)
            paragraphs.append(Paragraph(style=style, text=_paragraph_text(p), images=images))

        media = {
            name: archive.getinfo(name).file_size
            for name in sorted(names)
            if name.startswith("word/media/")
        }
        return Document(paragraphs=paragraphs, media=media, properties=_properties(archive))


def to_markdown(doc: Document) -> str:
    """Rend le document en texte structuré, lisible par un correcteur."""
    lines: list[str] = []
    for p in doc.paragraphs:
        style = p.style.casefold()
        text = p.text.strip()
        if style == "title":
            lines.append(f"# {text}")
        elif style == "subtitle":
            lines.append(f"Sous-titre : {text}")
        elif style.startswith("heading "):
            level = style.split(" ", 1)[1]
            depth = int(level) + 1 if level.isdigit() else 2
            lines.append(f"{'#' * depth} {text}")
        elif style == "list paragraph":
            lines.append(f"- {text}")
        elif text:
            lines.append(text)
        for image in p.images:
            size = doc.media.get(image, 0)
            lines.append(f"[image : {image}, {size / 1024:.0f} ko]")
        if text or p.images:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["Document", "DocxError", "Paragraph", "load", "to_markdown"]
