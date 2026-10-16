from __future__ import annotations

from pathlib import Path
import hashlib
import re

import analytics
import config


def normalize_text(text: str) -> str:
    """
    Normalize whitespace while preserving the actual document content.
    """

    if not text:
        return ""

    text = text.replace("\x00", " ")

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def chunks(
    text: str,
    size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """
    Split document text into overlapping chunks.
    """

    size = size or config.CHUNK_CHARS
    overlap = overlap or config.CHUNK_OVERLAP

    text = normalize_text(text)

    if not text:
        return []

    if overlap >= size:
        overlap = max(
            0,
            size // 5,
        )

    output = []

    step = max(
        1,
        size - overlap,
    )

    for start in range(
        0,
        len(text),
        step,
    ):
        piece = text[
            start:start + size
        ].strip()

        if piece:
            output.append(piece)

        if start + size >= len(text):
            break

    return output


def read_markdown(path: Path) -> str:
    """
    Read a Markdown file.
    """

    try:
        return path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as exc:
        print(
            f"ERROR reading Markdown file: "
            f"{path}"
        )
        print(f"       {exc}")

        return ""


def read_pdf(path: Path) -> str:
    """
    Extract text from a PDF using pypdf.
    """

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise SystemExit(
            "pypdf is required for PDF ingestion. "
            "Run: pip install pypdf"
        ) from exc

    try:
        reader = PdfReader(
            str(path)
        )

        pages = []

        for page_number, page in enumerate(
            reader.pages,
            start=1,
        ):
            try:
                page_text = (
                    page.extract_text()
                    or ""
                )

                if page_text.strip():
                    pages.append(
                        f"\n[Page {page_number}]\n"
                        f"{page_text}"
                    )

            except Exception as exc:
                print(
                    f"WARNING: Could not extract "
                    f"page {page_number} from "
                    f"{path.name}: {exc}"
                )

        return "\n".join(pages)

    except Exception as exc:
        print(
            f"ERROR reading PDF file: "
            f"{path}"
        )
        print(f"       {exc}")

        return ""


def collect_knowledge_files() -> list[tuple[Path, str]]:
    """
    Recursively discover Markdown and PDF files.
    """

    files = []

    md_extensions = {
        extension.lower()
        for extension in config.MD_EXTENSIONS
    }

    pdf_extensions = {
        extension.lower()
        for extension in config.PDF_EXTENSIONS
    }

    # ---------------------------------------------------------
    # Markdown
    # ---------------------------------------------------------

    if config.MD_DIR.exists():

        for path in sorted(
            config.MD_DIR.rglob("*")
        ):
            if not path.is_file():
                continue

            if path.suffix.lower() not in md_extensions:
                continue

            files.append(
                (
                    path,
                    "md",
                )
            )

    else:
        print(
            f"WARNING: Markdown directory "
            f"does not exist: {config.MD_DIR}"
        )

    # ---------------------------------------------------------
    # PDF
    # ---------------------------------------------------------

    if config.PDF_DIR.exists():

        for path in sorted(
            config.PDF_DIR.rglob("*")
        ):
            if not path.is_file():
                continue

            if path.suffix.lower() not in pdf_extensions:
                continue

            files.append(
                (
                    path,
                    "pdf",
                )
            )

    else:
        print(
            f"WARNING: PDF directory "
            f"does not exist: {config.PDF_DIR}"
        )

    return files


def build_index() -> None:
    """
    Build the local ChromaDB knowledge index.
    """

    chroma_dir = (
        config.DATA_DIR / "chroma"
    )

    chroma_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        import chromadb
    except ImportError as exc:
        raise SystemExit(
            "chromadb is required. "
            "Run: pip install -r requirements.txt"
        ) from exc

    print()
    print("=" * 70)
    print("INCIDENT COPILOT - KNOWLEDGE INGESTION")
    print("=" * 70)

    print()
    print(
        f"ChromaDB directory:"
        f"\n  {chroma_dir}"
    )

    # ---------------------------------------------------------
    # Create ChromaDB client
    # ---------------------------------------------------------

    client = chromadb.PersistentClient(
        path=str(chroma_dir)
    )

    # ---------------------------------------------------------
    # Rebuild knowledge collection
    # ---------------------------------------------------------

    try:
        client.delete_collection(
            "knowledge"
        )

        print(
            "Existing knowledge collection "
            "removed."
        )

    except Exception:
        print(
            "No existing knowledge collection "
            "found."
        )

    collection = client.get_or_create_collection(
        "knowledge"
    )

    documents = []
    ids = []
    metadatas = []

    knowledge_files = (
        collect_knowledge_files()
    )

    markdown_files = [
        item
        for item in knowledge_files
        if item[1] == "md"
    ]

    pdf_files = [
        item
        for item in knowledge_files
        if item[1] == "pdf"
    ]

    # ---------------------------------------------------------
    # Display discovery results
    # ---------------------------------------------------------

    print()
    print("=" * 70)
    print("KNOWLEDGE FILE DISCOVERY")
    print("=" * 70)

    print(
        f"Markdown files found : "
        f"{len(markdown_files)}"
    )

    print(
        f"PDF files found      : "
        f"{len(pdf_files)}"
    )

    if not knowledge_files:
        print()
        print(
            "WARNING: No Markdown or PDF "
            "knowledge files were found."
        )

    # ---------------------------------------------------------
    # Process every knowledge file
    # ---------------------------------------------------------

    total_characters = 0

    for path, kind in knowledge_files:

        print()
        print(
            f"[{kind.upper()}] "
            f"{path}"
        )

        # -----------------------------------------------------
        # Extract text
        # -----------------------------------------------------

        if kind == "md":
            text = read_markdown(
                path
            )

        else:
            text = read_pdf(
                path
            )

        text = normalize_text(
            text
        )

        character_count = len(
            text
        )

        total_characters += (
            character_count
        )

        print(
            f"  Extracted characters: "
            f"{character_count:,}"
        )

        if not text:
            print(
                "  WARNING: No text extracted."
            )
            continue

        # -----------------------------------------------------
        # Create chunks
        # -----------------------------------------------------

        file_chunks = chunks(
            text
        )

        print(
            f"  Chunks created: "
            f"{len(file_chunks):,}"
        )

        if not file_chunks:
            print(
                "  WARNING: No chunks created."
            )
            continue

        # -----------------------------------------------------
        # Add chunks
        # -----------------------------------------------------

        for chunk_index, chunk in enumerate(
            file_chunks
        ):
            digest_source = (
                f"{path.resolve()}:"
                f"{chunk_index}:"
                f"{chunk}"
            )

            digest = hashlib.sha1(
                digest_source.encode(
                    "utf-8"
                )
            ).hexdigest()

            ids.append(
                digest
            )

            documents.append(
                chunk
            )

            metadatas.append(
                {
                    "source": path.name,
                    "location": str(
                        path.resolve()
                    ),
                    "kind": kind,
                    "chunk": chunk_index,
                }
            )

    # ---------------------------------------------------------
    # Add documents to ChromaDB
    # ---------------------------------------------------------

    if documents:

        print()
        print(
            "Adding documents to ChromaDB..."
        )

        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

    # ---------------------------------------------------------
    # Incident data
    # ---------------------------------------------------------

    df = analytics.load_all()

    incident_files = (
        analytics.list_data_files()
    )

    # ---------------------------------------------------------
    # Final report
    # ---------------------------------------------------------

    print()
    print("=" * 70)
    print("INGESTION SUMMARY")
    print("=" * 70)

    print(
        f"Incident files        : "
        f"{len(incident_files)}"
    )

    print(
        f"Incidents loaded      : "
        f"{len(df):,}"
    )

    print(
        f"Markdown files        : "
        f"{len(markdown_files)}"
    )

    print(
        f"PDF files             : "
        f"{len(pdf_files)}"
    )

    print(
        f"Knowledge chunks      : "
        f"{len(documents):,}"
    )

    print(
        f"Knowledge characters  : "
        f"{total_characters:,}"
    )

    print(
        f"ChromaDB location     : "
        f"{chroma_dir}"
    )

    if (
        "ci_name"
        in df.columns
    ):
        sample = (
            df["ci_name"]
            .dropna()
            .drop_duplicates()
            .head(10)
            .tolist()
        )

        print(
            f"ci_name sample        : "
            f"{sample}"
        )

    print("=" * 70)

    print()
    print(
        "Knowledge ingestion completed."
    )

    print()


if __name__ == "__main__":
    build_index()