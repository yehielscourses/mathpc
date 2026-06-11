#!/usr/bin/env python3
"""Extrait les questions des PDF d'annales en JSON structuré."""

from __future__ import annotations

import base64
import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "json"

EXERCISE_RE = re.compile(
    r"(?:EXERCICE|Exercice)\s+(\d+|[A-Z])(?:\s+commun[^\n]*)?",
    re.IGNORECASE,
)
POINTS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*points?", re.IGNORECASE)
QUESTION_RE = re.compile(r"^(\d+)\.\s", re.MULTILINE)
SUBQUESTION_RE = re.compile(r"^([a-z])\.\s", re.MULTILINE)
CODE_HINTS = (
    "def ",
    "for ",
    "import ",
    "return ",
    "while ",
    "class ",
    "print(",
    "input(",
    "elif ",
    "else:",
    "function ",
    "var ",
    "let ",
    "const ",
)
CODE_CONTEXT_RE = re.compile(
    r"(langage\s+Python|fonction\s+Python|programme\s+(?:ci-dessous|suivant)|"
    r"algorithme|pseudo[\s-]?code|code\s+ci-dessous)",
    re.IGNORECASE,
)


@dataclass
class ContentBlock:
    type: str
    page: int
    bbox: list[float]
    text: str | None = None
    image: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": self.type,
            "page": self.page,
            "bbox": self.bbox,
        }
        if self.text is not None:
            out["text"] = self.text
        if self.image is not None:
            out["image"] = self.image
        return out


@dataclass
class Question:
    id: str
    number: str
    label: str
    content: list[ContentBlock] = field(default_factory=list)
    answer: dict[str, Any] | None = None
    subquestions: list[Question] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "number": self.number,
            "label": self.label,
            "content": [b.to_dict() for b in self.content],
        }
        if self.subquestions:
            out["subquestions"] = [q.to_dict() for q in self.subquestions]
        if self.answer is not None:
            out["answer"] = self.answer
        return out


@dataclass
class Exercise:
    number: str
    title: str
    points: float | None
    subtitle: str | None
    preamble: list[ContentBlock]
    questions: list[Question]
    content_blocks: list[ContentBlock]

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "points": self.points,
            "subtitle": self.subtitle,
            "preamble": [b.to_dict() for b in self.preamble],
            "content_blocks": [b.to_dict() for b in self.content_blocks],
            "questions": [q.to_dict() for q in self.questions],
        }


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def slugify(name: str) -> str:
    stem = Path(name).stem.lower()
    stem = unicodedata.normalize("NFKD", stem)
    stem = stem.encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return stem or "annale"


MONTHS = {
    "janvier": "01",
    "fevrier": "02",
    "février": "02",
    "mars": "03",
    "avril": "04",
    "mai": "05",
    "juin": "06",
    "juillet": "07",
    "aout": "08",
    "août": "08",
    "septembre": "09",
    "octobre": "10",
    "novembre": "11",
    "decembre": "12",
    "décembre": "12",
}


def normalize_match_key(filename: str) -> str:
    key = Path(filename).stem.lower()
    key = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[_-]\d+$", "", key)
    key = re.sub(r"(\d{4})j(\d)", r"\1 j\2", key, flags=re.IGNORECASE)
    for month_name, month_num in MONTHS.items():
        month_ascii = (
            unicodedata.normalize("NFKD", month_name)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        key = key.replace(month_ascii, month_num)
    replacements = [
        (r"corr(ige|igé|_)", ""),
        (r"correction", ""),
        (r"sujet[_-]?officiel", ""),
        (r"sujet", ""),
        (r"officiel", ""),
        (r"remplacement", "repl"),
        (r"metropolej1", "metropole j1"),
        (r"ameri[_\s-]?sud|amerique[_\s-]?sud", "amerique sud"),
        (r"ameri[_\s-]?nord|amerique[_\s-]?nord", "amerique nord"),
        (r"spe[_-]?physique[_-]?chimie", "pc"),
        (r"physique[_-]?chimie", "pc"),
        (r"specialite|specialite", ""),
        (r"\bspe\b", ""),
        (r"\bts\b", "eds"),
        (r"\beds\b", "eds"),
        (r"baccalaureat|bac", ""),
        (r"[_\-\.]+", " "),
        (r"\s+", " "),
    ]
    for pattern, repl in replacements:
        key = re.sub(pattern, repl, key)
    key = re.sub(r"\b(dv|fh|rr|nc|jcs|sd|vt|fk|dce|bs)\b", "", key)
    key = re.sub(r"\b\d{1,2}\s+\d{2}\s+\d{4}\b", "", key)
    key = re.sub(r"\b\d{4}\b", "", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def match_signatures(key: str) -> set[str]:
    signatures: set[str] = set()
    if m := re.search(r"\beds\s*(\d+)\b", key):
        signatures.add(f"eds:{m.group(1)}")
    if m := re.search(r"\bj\s*(\d+)\b", key):
        signatures.add(f"j:{m.group(1)}")
    if m := re.search(r"\bj(\d+)\b", key.replace(" ", "")):
        signatures.add(f"j:{m.group(1)}")
    regions = (
        "amerique sud",
        "amerique nord",
        "metropole",
        "asie",
        "polynesie",
        "caledonie",
        "madagascar",
        "suede",
        "etranger",
        "europe",
        "reunion",
        "liban",
    )
    for region in regions:
        if region in key:
            signatures.add(f"region:{region.replace(' ', '_')}")
    return signatures


def signatures_conflict(left: set[str], right: set[str]) -> bool:
    left_map = {item.split(":", 1)[0]: item for item in left if ":" in item}
    right_map = {item.split(":", 1)[0]: item for item in right if ":" in item}
    for key in left_map.keys() & right_map.keys():
        if left_map[key] != right_map[key]:
            return True
    return False


def match_corrige(sujet_path: Path, corriges: list[Path]) -> Path | None:
    if not corriges:
        return None
    sujet_key = normalize_match_key(sujet_path.name)
    sujet_sig = match_signatures(sujet_key)
    best: tuple[float, Path] | None = None
    for corrige in corriges:
        corrige_key = normalize_match_key(corrige.name)
        corrige_sig = match_signatures(corrige_key)
        if signatures_conflict(sujet_sig, corrige_sig):
            continue
        score = SequenceMatcher(None, sujet_key, corrige_key).ratio()
        sujet_tokens = set(sujet_key.split())
        corrige_tokens = set(corrige_key.split())
        if sujet_tokens and corrige_tokens:
            overlap = len(sujet_tokens & corrige_tokens) / max(len(sujet_tokens), 1)
            score = 0.55 * score + 0.45 * overlap
        if sujet_sig and corrige_sig and sujet_sig == corrige_sig:
            score += 0.2
        if best is None or score > best[0]:
            best = (score, corrige)
    if best and best[0] >= 0.45:
        return best[1]
    return None


def looks_like_code(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if any(hint in stripped for hint in CODE_HINTS):
        return True
    lines = stripped.split("\n")
    if len(lines) >= 2:
        indented = sum(1 for line in lines[1:] if line.startswith((" ", "\t")) or not line.strip())
        if indented >= max(1, len(lines) // 3):
            return True
    return False


def classify_text_block(text: str, previous_text: str = "") -> str:
    if looks_like_code(text):
        return "code"
    if CODE_CONTEXT_RE.search(previous_text) and (
        ":" in text or text.strip().startswith(("def ", "for ", "while "))
    ):
        return "code"
    return "text"


def extract_blocks(pdf_path: Path) -> list[ContentBlock]:
    doc = fitz.open(pdf_path)
    blocks: list[ContentBlock] = []
    previous_text = ""

    for page_index in range(len(doc)):
        page = doc[page_index]
        page_num = page_index + 1
        page_dict = page.get_text("dict")
        image_info: dict[int, dict[str, Any]] = {}
        min_image_bytes = 800
        min_image_dim = 80

        for block in page_dict.get("blocks", []):
            if block.get("type") != 1:
                continue
            width = block.get("width") or 0
            height = block.get("height") or 0
            if width < min_image_dim and height < min_image_dim:
                continue
            try:
                image_bytes = block.get("image")
                if not image_bytes or len(image_bytes) < min_image_bytes:
                    continue
                ext = block.get("ext", "png")
                image_info[id(block)] = {
                    "format": ext,
                    "width": width,
                    "height": height,
                    "data_base64": base64.b64encode(image_bytes).decode("ascii"),
                }
            except Exception:
                continue

        page_has_image = False
        for block in page_dict.get("blocks", []):
            bbox = [round(v, 2) for v in block["bbox"]]
            if block.get("type") == 0:
                lines: list[str] = []
                for line in block.get("lines", []):
                    line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                    lines.append(line_text)
                text = normalize_text("\n".join(lines)).strip("\n")
                if not text.strip():
                    continue
                block_type = classify_text_block(text, previous_text)
                blocks.append(
                    ContentBlock(
                        type=block_type,
                        page=page_num,
                        bbox=bbox,
                        text=text,
                    )
                )
                previous_text = text
            elif block.get("type") == 1 and id(block) in image_info:
                page_has_image = True
                blocks.append(
                    ContentBlock(
                        type="image",
                        page=page_num,
                        bbox=bbox,
                        image=image_info[id(block)],
                    )
                )

        if not page_has_image:
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.width < min_image_dim or pix.height < min_image_dim:
                        continue
                    if pix.n - pix.alpha > 3:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    data = pix.tobytes("png")
                    if len(data) < min_image_bytes:
                        continue
                    blocks.append(
                        ContentBlock(
                            type="image",
                            page=page_num,
                            bbox=[0, 0, float(pix.width), float(pix.height)],
                            image={
                                "format": "png",
                                "width": pix.width,
                                "height": pix.height,
                                "data_base64": base64.b64encode(data).decode("ascii"),
                            },
                        )
                    )
                    break
                except Exception:
                    pass

    text_chars = sum(len(b.text or "") for b in blocks if b.type in {"text", "code"})
    if text_chars < 80:
        blocks = []
        for page_index in range(len(doc)):
            page = doc[page_index]
            page_num = page_index + 1
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            data = pix.tobytes("png")
            blocks.append(
                ContentBlock(
                    type="page_image",
                    page=page_num,
                    bbox=[0, 0, float(pix.width), float(pix.height)],
                    image={
                        "format": "png",
                        "width": pix.width,
                        "height": pix.height,
                        "data_base64": base64.b64encode(data).decode("ascii"),
                        "scan_mode": True,
                    },
                )
            )

    doc.close()
    return blocks


def blocks_to_text(blocks: list[ContentBlock]) -> str:
    return "\n\n".join(b.text or "" for b in blocks if b.text)


def split_blocks_by_pattern(
    blocks: list[ContentBlock], pattern: re.Pattern[str]
) -> list[tuple[str | None, list[ContentBlock]]]:
    segments: list[tuple[str | None, list[ContentBlock]]] = []
    current_label: str | None = None
    current_blocks: list[ContentBlock] = []

    for block in blocks:
        if block.type == "image":
            current_blocks.append(block)
            continue
        text = block.text or ""
        matches = list(pattern.finditer(text))
        if not matches:
            current_blocks.append(block)
            continue

        pos = 0
        for match in matches:
            before = text[pos : match.start()].strip()
            if before or (not current_blocks and not current_label):
                if before:
                    current_blocks.append(
                        ContentBlock(
                            type=block.type,
                            page=block.page,
                            bbox=block.bbox,
                            text=before,
                        )
                    )
            elif current_blocks or current_label is not None:
                segments.append((current_label, current_blocks))
                current_blocks = []

            label = match.group(0).strip()
            number = match.group(1)
            current_label = number
            current_blocks = []
            pos = match.end()

        rest = text[pos:].strip()
        if rest:
            current_blocks.append(
                ContentBlock(
                    type=block.type,
                    page=block.page,
                    bbox=block.bbox,
                    text=rest,
                )
            )

    if current_label is not None or current_blocks:
        segments.append((current_label, current_blocks))
    return segments


def parse_questions_from_blocks(
    blocks: list[ContentBlock], exercise_id: str
) -> tuple[list[ContentBlock], list[Question]]:
    if not blocks:
        return [], []

    full_text = blocks_to_text(blocks)
    main_segments = split_blocks_by_pattern(blocks, QUESTION_RE)
    if len(main_segments) <= 1 and not QUESTION_RE.search(full_text):
        return blocks, []

    preamble: list[ContentBlock] = []
    questions: list[Question] = []

    first_label, first_blocks = main_segments[0]
    if first_label is None:
        preamble = first_blocks
        main_segments = main_segments[1:]
    else:
        main_segments = [(first_label, first_blocks)] + main_segments[1:]

    for label, q_blocks in main_segments:
        if label is None:
            preamble.extend(q_blocks)
            continue

        q_id = f"{exercise_id}-q{label}"
        sub_segments = split_blocks_by_pattern(q_blocks, SUBQUESTION_RE)
        subquestions: list[Question] = []
        main_content = q_blocks

        if len(sub_segments) > 1 or any(lbl for lbl, _ in sub_segments if lbl):
            main_content = []
            for sub_label, sub_blocks in sub_segments:
                if sub_label is None:
                    main_content.extend(sub_blocks)
                else:
                    subquestions.append(
                        Question(
                            id=f"{q_id}-{sub_label}",
                            number=sub_label,
                            label=f"{sub_label}.",
                            content=sub_blocks,
                        )
                    )

        questions.append(
            Question(
                id=q_id,
                number=label,
                label=f"{label}.",
                content=main_content,
                subquestions=subquestions,
            )
        )

    return preamble, questions


def find_exercise_starts(blocks: list[ContentBlock]) -> list[tuple[int, str, str]]:
    starts: list[tuple[int, str, str]] = []
    for index, block in enumerate(blocks):
        if not block.text:
            continue
        for match in EXERCISE_RE.finditer(block.text):
            starts.append((index, match.group(1), match.group(0).strip()))
    return starts


def parse_exercises(blocks: list[ContentBlock]) -> tuple[list[ContentBlock], list[Exercise]]:
    starts = find_exercise_starts(blocks)
    if not starts:
        return blocks, []

    header_blocks = blocks[: starts[0][0]]
    exercises: list[Exercise] = []

    for i, (start_idx, number, title) in enumerate(starts):
        end_idx = starts[i + 1][0] if i + 1 < len(starts) else len(blocks)
        exercise_blocks = blocks[start_idx:end_idx]
        exercise_id = f"ex{number}"

        points: float | None = None
        subtitle: str | None = None
        body_blocks = exercise_blocks[:]

        if body_blocks and body_blocks[0].text:
            first_text = body_blocks[0].text
            points_match = POINTS_RE.search(first_text)
            if points_match:
                points = float(points_match.group(1).replace(",", "."))
            lines = first_text.split("\n")
            if len(lines) >= 3 and "commun" in lines[2].lower():
                subtitle = lines[2].strip()

        preamble, questions = parse_questions_from_blocks(body_blocks, exercise_id)
        if not questions:
            preamble = []
            questions = []

        exercises.append(
            Exercise(
                number=number,
                title=title,
                points=points,
                subtitle=subtitle,
                preamble=preamble,
                questions=questions,
                content_blocks=body_blocks,
            )
        )

    return header_blocks, exercises


def answer_dict(blocks: list[ContentBlock]) -> dict[str, Any]:
    return {
        "available": bool(blocks),
        "content": [b.to_dict() for b in blocks],
        "text": blocks_to_text(blocks),
    }


def merge_answers(sujet_exercises: list[Exercise], corrige_exercises: list[Exercise]) -> None:
    corrige_map = {ex.number: ex for ex in corrige_exercises}
    for exercise in sujet_exercises:
        corr_ex = corrige_map.get(exercise.number)
        if not corr_ex:
            continue
        corr_q_map = {q.number: q for q in corr_ex.questions}
        for question in exercise.questions:
            corr_q = corr_q_map.get(question.number)
            if not corr_q:
                continue
            question.answer = answer_dict(corr_q.content)
            corr_sub_map = {sq.number: sq for sq in corr_q.subquestions}
            for sub in question.subquestions:
                corr_sub = corr_sub_map.get(sub.number)
                if corr_sub:
                    sub.answer = answer_dict(corr_sub.content)


def extract_metadata(blocks: list[ContentBlock], pdf_path: Path, year: int) -> dict[str, Any]:
    header_text = blocks_to_text(blocks[:8])
    title_match = re.search(
        r"(Baccalauréat[^<\n]+|BACCALAURÉAT[^<\n]+|ÉPREUVE D'ENSEIGNEMENT[^<\n]+)",
        header_text,
        re.IGNORECASE,
    )
    return {
        "source_pdf": str(pdf_path.relative_to(ROOT)),
        "filename": pdf_path.name,
        "year": year,
        "title": title_match.group(1).strip() if title_match else pdf_path.stem,
        "header_text": header_text[:2000],
    }


def process_annale(
    sujet_path: Path,
    corrige_path: Path | None,
    subject: str,
    year: int,
) -> dict[str, Any]:
    sujet_blocks = extract_blocks(sujet_path)
    header_blocks, exercises = parse_exercises(sujet_blocks)

    corrige_blocks: list[ContentBlock] = []
    corrige_exercises: list[Exercise] = []
    if corrige_path and corrige_path.exists():
        corrige_blocks = extract_blocks(corrige_path)
        _, corrige_exercises = parse_exercises(corrige_blocks)
        merge_answers(exercises, corrige_exercises)

    annale_id = slugify(sujet_path.name)
    scan_only = any(b.type == "page_image" for b in sujet_blocks)
    result: dict[str, Any] = {
        "id": annale_id,
        "subject": subject,
        "year": year,
        "metadata": extract_metadata(header_blocks, sujet_path, year),
        "corrige": {
            "available": corrige_path is not None and corrige_path.exists(),
            "source_pdf": str(corrige_path.relative_to(ROOT)) if corrige_path else None,
        },
        "instructions": blocks_to_text(header_blocks),
        "instructions_blocks": [b.to_dict() for b in header_blocks],
        "exercises": [ex.to_dict() for ex in exercises],
        "scan_only": scan_only,
        "raw_block_count": len(sujet_blocks),
    }
    if scan_only:
        result["pages"] = [b.to_dict() for b in sujet_blocks if b.type == "page_image"]
    return result


def iter_sujets(base_dir: Path) -> list[tuple[Path, int]]:
    results: list[tuple[Path, int]] = []
    for year_dir in sorted(base_dir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        sujets_dir = year_dir / "sujets"
        if not sujets_dir.is_dir():
            continue
        year = int(year_dir.name)
        for pdf in sorted(sujets_dir.glob("*.pdf")):
            results.append((pdf, year))
    return results


def process_subject(subject_dir: Path, subject_name: str) -> list[dict[str, Any]]:
    annales: list[dict[str, Any]] = []
    out_subject_dir = OUTPUT_DIR / subject_name
    out_subject_dir.mkdir(parents=True, exist_ok=True)

    for sujet_path, year in iter_sujets(subject_dir):
        corriges_dir = sujet_path.parent.parent / "corriges"
        corriges = sorted(corriges_dir.glob("*.pdf")) if corriges_dir.is_dir() else []
        corrige_path = match_corrige(sujet_path, corriges)

        try:
            data = process_annale(sujet_path, corrige_path, subject_name, year)
        except Exception as exc:
            data = {
                "id": slugify(sujet_path.name),
                "subject": subject_name,
                "year": year,
                "error": str(exc),
                "metadata": {"source_pdf": str(sujet_path.relative_to(ROOT))},
            }

        out_file = out_subject_dir / f"{data['id']}.json"
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        annales.append(data)
        corrige_status = "✓" if data.get("corrige", {}).get("available") else "·"
        print(f"  [{corrige_status}] {subject_name}/{year}/{sujet_path.name} -> {out_file.name}")

    return annales


def main() -> None:
    all_annales: list[dict[str, Any]] = []

    subjects = [
        (ROOT / "math", "math"),
        (ROOT / "physique-chimie", "physique-chimie"),
    ]

    for subject_dir, subject_name in subjects:
        if not subject_dir.is_dir():
            continue
        print(f"\n=== {subject_name} ===")
        annales = process_subject(subject_dir, subject_name)
        all_annales.extend(annales)

    master = {
        "version": 1,
        "description": "Annales bac spé mathématiques et physique-chimie (2021-2025)",
        "count": len(all_annales),
        "subjects": {
            "math": sum(1 for a in all_annales if a.get("subject") == "math"),
            "physique-chimie": sum(1 for a in all_annales if a.get("subject") == "physique-chimie"),
        },
        "with_corrige": sum(1 for a in all_annales if a.get("corrige", {}).get("available")),
        "annales": [
            {
                "id": a["id"],
                "subject": a.get("subject"),
                "year": a.get("year"),
                "source_pdf": a.get("metadata", {}).get("source_pdf"),
                "corrige_pdf": a.get("corrige", {}).get("source_pdf"),
                "exercise_count": len(a.get("exercises", [])),
                "json_file": f"data/json/{a.get('subject')}/{a['id']}.json",
            }
            for a in all_annales
            if "error" not in a
        ],
        "errors": [
            {
                "id": a["id"],
                "source_pdf": a.get("metadata", {}).get("source_pdf"),
                "error": a.get("error"),
            }
            for a in all_annales
            if "error" in a
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    master_path = OUTPUT_DIR / "annales_completes.json"
    master_path.write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== Terminé ===")
    print(f"Annales extraites : {len(all_annales)}")
    print(f"Avec corrigé      : {master['with_corrige']}")
    print(f"Erreurs           : {len(master['errors'])}")
    print(f"Index             : {master_path}")


if __name__ == "__main__":
    main()
