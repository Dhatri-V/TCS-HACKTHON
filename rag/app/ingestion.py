from pathlib import Path
import json
import csv

from .schemas import Document

SUPPORTED_FILES = [".txt", ".md", ".log", ".json", ".csv"]


def load_txt(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")

    return Document(
        text=text,
        source=path.name,
        metadata={
            "type": path.suffix,
            "file": path.name
        }
    )


def load_json(path: Path):

    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, list):
        text = "\n\n".join(json.dumps(x, indent=2) for x in raw)
    else:
        text = json.dumps(raw, indent=2)

    return Document(
        text=text,
        source=path.name,
        metadata={
            "type": ".json",
            "file": path.name
        }
    )


def load_csv(path: Path):

    rows = []

    with open(path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            sentence = "\n".join(
                f"{k}: {v}" for k, v in row.items()
            )

            rows.append(sentence)

    text = "\n\n".join(rows)

    return Document(
        text=text,
        source=path.name,
        metadata={
            "type": ".csv",
            "file": path.name
        }
    )


def load_documents(folder):

    folder = Path(folder)

    documents = []

    for file in folder.rglob("*"):

        if not file.is_file():
            continue

        if file.suffix not in SUPPORTED_FILES:
            continue

        if file.suffix in [".txt", ".md", ".log"]:
            documents.append(load_txt(file))

        elif file.suffix == ".json":
            documents.append(load_json(file))

        elif file.suffix == ".csv":
            documents.append(load_csv(file))

    return documents