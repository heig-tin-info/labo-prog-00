"""Tests de conformité du rendu du laboratoire 00.

Ils vérifient ce qui peut l'être automatiquement : l'arborescence et les
fichiers publiés dans Git, la compilation et l'exécution de hello.c, le contenu
de two-pies.txt et les éléments du rapport Word faciles à contrôler (styles,
captures d'écran, clé SSH, réponses factuelles). La qualité des réponses et
de la présentation du rapport est jugée séparément par la revue LLM
(criteria.yml).

Lancer localement, depuis la racine du dépôt et sous Ubuntu : `make test`
(pytest requis : sudo apt install python3-pytest). Chaque test qui échoue
explique ce qui manque et comment corriger.

Le dossier rendu/ doit contenir hello.c, two-pies.txt et rapport.docx ; un
README.md y est toléré, tout autre fichier est refusé.

Les réponses aux questions de l'énoncé ne sont pas écrites en clair ici mais
comparées par empreinte SHA-256, pour ne pas les révéler.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

import rendu_docx

ROOT = Path(__file__).resolve().parents[1]
RENDU = ROOT / "rendu"
REQUIRED = ("hello.c", "two-pies.txt", "rapport.docx")
ALLOWED = set(REQUIRED) | {"README.md"}

EXAMPLE_KEY = "AAAAC3NzaC1lZDI1NTE5AAAAIBiKGoMLwS80YMnoMz4AXNGlt9EoVZbZ0WE5MVPKp1DU"

# Empreintes SHA-256 des réponses attendues (en minuscules).
HEX_AFTER_TOGGLE = {"32549bff6d8404c4d121b589f4d24ac6416ed48c25163e1f08d92d67ca0bb0b3"}
BLAME_AUTHOR = {"e926835928fb0179ef467ad63d14358e18ebb5846a30040eda66ce2ee8dbf9e9"}
BLAME_YEARS = {
    "4b9a7f50c0bb198c6f5414c5a8459f5d216d34ab521ea94c060ea35cac66f900",
    "96da37e95d5cc34fe3bef6c89428df859b8a217630d0c664da1daf1539caacf5",
}


# --------------------------------------------------------------------------
# Outils
# --------------------------------------------------------------------------


def git(*args: str) -> str | None:
    """Exécute git dans le dépôt ; None si git ou le dépôt sont absents."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def tracked(path: str = ".") -> list[str] | None:
    """Fichiers publiés dans Git sous `path`, ou None hors dépôt."""
    output = git("ls-files", "-z", "--", path)
    if output is None:
        return None
    return [p for p in output.split("\0") if p]


def rendu_files() -> tuple[set[str], bool]:
    """Fichiers de rendu/ (relatifs) et indicateur « lus depuis Git »."""
    files = tracked("rendu")
    if files is not None:
        return {p[len("rendu/"):] for p in files if p.startswith("rendu/")}, True
    if not RENDU.is_dir():
        return set(), False
    return {str(p.relative_to(RENDU)) for p in RENDU.rglob("*") if p.is_file()}, False


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return text.replace("\u2019", "'").replace("\u2018", "'").replace("\u00a0", " ")


def digest(token: str) -> str:
    return hashlib.sha256(token.casefold().encode("utf-8")).hexdigest()


def any_token_matches(pattern: str, text: str, expected: set[str]) -> bool:
    return any(digest(m) in expected for m in re.findall(pattern, text))


def decode_text(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if b"\x00" in raw:
        return raw.decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


# --------------------------------------------------------------------------
# Arborescence et fichiers publiés
# --------------------------------------------------------------------------


def test_dossier_rendu_existe():
    assert RENDU.is_dir(), (
        "Le dossier `rendu` doit exister à la racine du dépôt "
        "(`mkdir rendu` depuis le dossier du dépôt, puis copiez-y vos fichiers)."
    )


@pytest.mark.parametrize("name", REQUIRED)
def test_fichier_obligatoire_publie(name: str):
    files, via_git = rendu_files()
    if name in files:
        return
    by_lower = {f.casefold(): f for f in files}
    if (RENDU / name).exists() and via_git:
        hint = (
            "le fichier existe sur le disque mais n'est pas publié dans Git : "
            "`git add rendu`, puis `git commit` et `git push`"
        )
    elif name.casefold() in by_lower:
        hint = (
            f"trouvé `{by_lower[name.casefold()]}` : la casse des noms compte, "
            f"renommez-le exactement `{name}`"
        )
    elif f"{name}.txt" in files:
        hint = (
            f"trouvé `{name}.txt` : Notepad a ajouté `.txt`. Enregistrez avec le "
            "type « Tous les fichiers », ou renommez le fichier dans l'explorateur"
        )
    else:
        hint = "copiez-le dans `rendu/` depuis votre dossier `Documents\\rendu`"
    pytest.fail(f"`rendu/{name}` manque dans le rendu : {hint}.")


def test_aucun_fichier_superflu():
    files, _ = rendu_files()
    extra = sorted(files - ALLOWED)
    if not extra:
        return
    hints = []
    for f in extra:
        base = f.rsplit("/", 1)[-1]
        if f.endswith((".c.txt", ".txt.txt", ".docx.txt")):
            hint = "double extension ajoutée par Notepad, renommez le fichier"
        elif base in ("hello", "a.out") or base.endswith((".exe", ".o")):
            hint = "un exécutable ne se publie pas, supprimez-le (`rm rendu/hello`)"
        elif base.startswith("~$"):
            hint = "fichier de verrouillage de Word, fermez Word et supprimez-le"
        elif base.startswith("biscuit"):
            hint = "l'expérience du biscuit ne fait pas partie du rendu"
        elif "/" in f:
            hint = "pas de sous-dossier dans `rendu`"
        else:
            hint = "fichier non demandé"
        hints.append(f"`{f}` ({hint})")
    pytest.fail(
        "Le dossier `rendu` ne doit contenir que hello.c, two-pies.txt et "
        "rapport.docx (README.md toléré). En trop : "
        + ", ".join(hints)
        + ". Retirez-les du dépôt avec `git rm rendu/<fichier>` puis validez."
    )


def test_aucun_executable_publie():
    files = tracked()
    if files is None:
        files = [
            str(p.relative_to(ROOT))
            for p in ROOT.rglob("*")
            if p.is_file() and ".git" not in p.parts and "build" not in p.parts
        ]
    binaries = [
        f
        for f in files
        if Path(f).name in ("hello", "a.out") or f.endswith((".exe", ".o", ".obj"))
    ]
    assert not binaries, (
        "Un exécutable ne se publie pas dans un dépôt Git, seules les sources "
        f"le sont. Supprimez du dépôt : {', '.join(binaries)} "
        "(`git rm <fichier>` puis commit et push)."
    )


# --------------------------------------------------------------------------
# hello.c
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hello_source() -> bytes:
    path = RENDU / "hello.c"
    if not path.is_file():
        pytest.fail("`rendu/hello.c` est absent, impossible de le vérifier.")
    return path.read_bytes()


def test_hello_c_encode_en_utf8(hello_source: bytes):
    if b"\x00" in hello_source:
        pytest.fail(
            "`rendu/hello.c` contient des octets nuls : il a probablement été "
            "enregistré en UTF-16 par Notepad. Réenregistrez-le avec l'encodage "
            "UTF-8 (menu Enregistrer sous, liste Encodage)."
        )
    try:
        hello_source.decode("utf-8-sig")
    except UnicodeDecodeError:
        pytest.fail(
            "`rendu/hello.c` n'est pas encodé en UTF-8 (accents dans le nom de "
            "l'auteur ?). Réenregistrez-le avec l'encodage UTF-8."
        )


def test_hello_c_auteur_remplace(hello_source: bytes):
    text = decode_text(hello_source)
    match = re.search(r"Author\s*:\s*(.+)", text)
    assert match, (
        "Le commentaire d'en-tête `Author: ...` manque dans `rendu/hello.c`. "
        "Recopiez le programme de l'énoncé avec votre nom."
    )
    author = match.group(1).strip()
    assert "kernighan" not in author.casefold(), (
        "Remplacez Brian Kernighan par votre propre nom dans la ligne "
        "`Author:` de `rendu/hello.c`."
    )
    assert re.search(r"[^\W\d_]{2,}", author), (
        "La ligne `Author:` de `rendu/hello.c` ne contient pas de nom."
    )


@pytest.fixture(scope="module")
def hello_binary(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    source = RENDU / "hello.c"
    if not source.is_file():
        pytest.fail("`rendu/hello.c` est absent, impossible de le compiler.")
    gcc = shutil.which("gcc") or shutil.which("cc")
    if gcc is None:
        pytest.skip("gcc absent : lancez les tests sous Ubuntu (sudo apt install gcc)")
    exe = tmp_path_factory.mktemp("hello") / "hello"
    result = subprocess.run(
        [gcc, "-std=c17", "-Wall", "-Wextra", "-pedantic", str(source), "-o", str(exe)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return SimpleNamespace(returncode=result.returncode, stderr=result.stderr, path=exe)


def test_hello_c_compile(hello_binary: SimpleNamespace):
    assert hello_binary.returncode == 0, (
        "gcc n'arrive pas à compiler `rendu/hello.c` :\n"
        f"{hello_binary.stderr}\n"
        "Comparez votre fichier au programme de l'énoncé, caractère par caractère."
    )


def test_hello_c_compile_sans_avertissement(hello_binary: SimpleNamespace):
    if hello_binary.returncode != 0:
        pytest.fail("La compilation échoue, voir test_hello_c_compile.")
    assert not hello_binary.stderr.strip(), (
        "gcc émet des avertissements sur `rendu/hello.c` :\n"
        f"{hello_binary.stderr}\n"
        "Le programme de l'énoncé compile sans aucun avertissement."
    )


def test_hello_affiche_hello_world(hello_binary: SimpleNamespace):
    if hello_binary.returncode != 0:
        pytest.fail("La compilation échoue, voir test_hello_c_compile.")
    result = subprocess.run(
        [str(hello_binary.path)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, (
        f"Le programme se termine avec le code {result.returncode} au lieu de 0 "
        "(`return 0;`)."
    )
    assert result.stdout == "hello, world\n", (
        "Le programme doit afficher exactement `hello, world` suivi d'un retour à "
        f"la ligne ; obtenu : {result.stdout!r}."
    )


# --------------------------------------------------------------------------
# two-pies.txt
# --------------------------------------------------------------------------


def test_two_pies_contient_le_resultat():
    path = RENDU / "two-pies.txt"
    assert path.is_file(), "`rendu/two-pies.txt` est absent."
    content = decode_text(path.read_bytes()).strip()
    assert re.fullmatch(r"6[.,]28", content), (
        "`rendu/two-pies.txt` doit contenir uniquement le résultat de 3.14 × 2 "
        f"copié depuis la calculatrice et collé dans Notepad ; trouvé : {content!r}."
    )


# --------------------------------------------------------------------------
# rapport.docx
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rapport() -> rendu_docx.Document:
    path = RENDU / "rapport.docx"
    if not path.is_file():
        pytest.fail("`rendu/rapport.docx` est absent, impossible de le vérifier.")
    try:
        return rendu_docx.load(path)
    except rendu_docx.DocxError as exc:
        pytest.fail(
            f"`rendu/rapport.docx` n'est pas un document Word valide ({exc}). "
            "Un .docx est une archive zip produite par Word : enregistrez depuis "
            "Word au format « Document Word (*.docx) », ne renommez pas un autre "
            "fichier."
        )


@pytest.fixture(scope="module")
def rapport_text(rapport: rendu_docx.Document) -> str:
    return normalize(rapport.text)


def test_rapport_non_vide(rapport_text: str):
    assert len(rapport_text.strip()) >= 600, (
        "Le rapport est presque vide : il doit contenir les réponses aux neuf "
        "points de l'énoncé (dont la sortie de cowsay et votre clé publique)."
    )


def test_rapport_titre_avec_style_titre(rapport: rendu_docx.Document):
    titles = rapport.with_style("Title")
    assert titles, (
        "Aucun paragraphe n'utilise le style Word « Titre » (Title). Choisissez-le "
        "dans le menu Styles pour écrire `Rapport de laboratoire`."
    )
    assert any("rapport de laboratoire" in normalize(t.text).casefold() for t in titles), (
        "Le paragraphe en style « Titre » doit contenir `Rapport de laboratoire`."
    )


def test_rapport_sous_titre_avec_style_sous_titre(rapport: rendu_docx.Document):
    subtitles = rapport.with_style("Subtitle")
    assert subtitles, (
        "Aucun paragraphe n'utilise le style Word « Sous-titre » (Subtitle). "
        "Choisissez-le pour écrire `Laboratoire 00 : Prise en main de l'ordinateur`."
    )
    assert any("laboratoire 00" in normalize(t.text).casefold() for t in subtitles), (
        "Le paragraphe en style « Sous-titre » doit contenir `Laboratoire 00`."
    )


def test_rapport_faute_corrigee(rapport_text: str):
    lowered = rapport_text.casefold()
    assert "ordinteur" not in lowered, (
        "La faute de frappe `ordinteur` est toujours dans le rapport : corrigez-la "
        "avec un clic droit sur le mot souligné en rouge."
    )
    assert "ordinateur" in lowered, "Le sous-titre doit mentionner l'ordinateur."


def test_rapport_sections_en_titre_1(rapport: rendu_docx.Document):
    headings = rapport.with_style("heading 1")
    assert len(headings) >= 4, (
        "Le rapport doit avoir un titre de section en style « Titre 1 » "
        "(CTRL+ALT+1) pour chaque étape : Microsoft Word, premier programme, "
        f"calculatrice, Visual Studio Code, Linux, Git, GitHub. Trouvé : {len(headings)}."
    )
    assert any("word" in t.text.casefold() for t in headings), (
        "La section `Microsoft Word` en style « Titre 1 » manque."
    )


def test_rapport_contient_les_captures_ecran(rapport: rendu_docx.Document):
    count = len(rapport.images)
    assert count >= 3, (
        "Le rapport doit contenir au moins trois captures d'écran (Word, "
        f"calculatrice, Visual Studio Code) collées dans le document ; trouvé : {count}. "
        "Utilisez WIN+MAJ+S puis CTRL+V dans Word."
    )


def test_rapport_contient_la_cle_publique(rapport_text: str):
    match = re.search(
        r"ssh-(?:ed25519|rsa|ecdsa-sha2-nistp\d{3})\s+(AAAA[0-9A-Za-z+/]{20,}={0,3})",
        rapport_text,
    )
    assert match, (
        "La clé SSH publique manque dans le rapport : copiez la ligne affichée par "
        "`cat ~/.ssh/id_ed25519.pub` (elle commence par `ssh-ed25519 AAAA`)."
    )
    assert EXAMPLE_KEY not in match.group(1), (
        "La clé publique du rapport est celle de l'exemple de l'énoncé, pas la vôtre."
    )


def test_rapport_sans_cle_privee(rapport_text: str):
    assert "PRIVATE KEY" not in rapport_text.upper(), (
        "ATTENTION : votre clé PRIVÉE figure dans le rapport. Elle ne doit jamais "
        "être communiquée, à personne. Supprimez-la du rapport, puis générez une "
        "nouvelle paire avec `ssh-keygen` et remplacez la clé publique sur GitHub : "
        "l'ancienne est compromise, car l'historique Git conserve ce fichier."
    )


def test_rapport_chemin_du_dossier_utilisateur(rapport_text: str):
    assert re.search(r"[A-Za-z]:[\\/]Users[\\/]\S", rapport_text), (
        "Le chemin complet de votre dossier utilisateur manque "
        "(il ressemble à `C:\\Users\\prenom`)."
    )


def test_rapport_explique_userprofile(rapport_text: str):
    lowered = rapport_text.casefold()
    assert "userprofile" in lowered and "%" in rapport_text, (
        "Le rapport doit expliquer la notation `%userprofile%` et le rôle des `%`."
    )


def test_rapport_explique_la_nature_du_docx(rapport_text: str):
    lowered = rapport_text.casefold()
    assert any(word in lowered for word in ("zip", "xml", "archive", "compress")), (
        "La réponse sur la nature d'un fichier .docx manque (archive, compression, XML)."
    )


def test_rapport_conversion_decimale_de_deadbeef(rapport_text: str):
    assert re.search(r"3[\s'.,]?735[\s'.,]?928[\s'.,]?559", rapport_text), (
        "La conversion de DEADBEEF en décimal manque dans le rapport."
    )


def test_rapport_valeur_apres_commutation_des_bits(rapport_text: str):
    tokens = re.findall(r"(?<![0-9A-Za-z])(?:0x)?([0-9A-Fa-f]{8})(?![0-9A-Za-z])", rapport_text)
    assert any(digest(t) in HEX_AFTER_TOGGLE for t in tokens), (
        "La valeur hexadécimale obtenue après avoir commuté les bits 29 et 22 de "
        "DEADBEEF manque ou est fausse (le bit 0 est le plus à droite)."
    )


def test_rapport_contient_la_sortie_de_cowsay(rapport_text: str):
    assert "bilbon, je t'aurais" in rapport_text.casefold(), (
        "La sortie de la commande cowsay demandée (`Bilbon, je t'aurais`) manque : "
        "trouvez la bonne option dans `man cowsay` et collez le résultat."
    )


def test_rapport_reponse_git_blame(rapport_text: str):
    assert any_token_matches(r"[^\W\d_]{3,}", rapport_text, BLAME_AUTHOR), (
        "Le nom de l'auteur de la ligne DeLorean d'addrman.cpp manque ou est faux "
        "(utilisez *View git blame* sur GitHub)."
    )
    assert any_token_matches(r"\b(?:19|20)\d{2}\b", rapport_text, BLAME_YEARS), (
        "L'année où la ligne DeLorean a été écrite manque ou est fausse."
    )


# --------------------------------------------------------------------------
# Git
# --------------------------------------------------------------------------


def test_identite_git_configuree():
    output = git("log", "-1", "--format=%an%n%ae")
    if output is None:
        pytest.skip("pas de dépôt Git")
    name, _, email = output.strip().partition("\n")
    assert "emmett" not in name.casefold() and "emmett.brown" not in email.casefold(), (
        "Le dernier commit porte l'identité de l'exemple (Emmett Brown). Configurez "
        "la vôtre avec `git config --global user.name` et `user.email`, puis "
        "refaites un commit."
    )
    assert "@" in email, (
        "Le dernier commit n'a pas d'adresse e-mail : configurez "
        "`git config --global user.email`."
    )
