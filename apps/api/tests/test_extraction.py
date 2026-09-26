"""Text extraction from real uploaded resources.

The fixtures are genuine files of each format rather than stubs, so a reader that
silently returns nothing fails here instead of shipping. Covers the prompt's minimum
resource types plus the hostile cases: a zip bomb, a corrupt archive, and an image
that must not be given invented text.
"""

from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.modules.analysis import extraction

MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".png": "image/png",
}


def document(filename: str, data: bytes, mime_type: str | None = None):
    return SimpleNamespace(
        id=uuid4(),
        filename=filename,
        mime_type=mime_type or MIME_BY_EXTENSION.get(filename[filename.rfind(".") :], ""),
        storage_key=f"key/{filename}",
    )


class FakeStorage:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs

    def read(self, key: str) -> bytes:
        try:
            return self.blobs[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    instance = FakeStorage({})
    monkeypatch.setattr(extraction, "get_storage", lambda: instance)
    return instance


def make_docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    xml = (
        '<?xml version="1.0"?><w:document '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def make_pptx(slides: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for number, text in enumerate(slides, start=1):
            xml = (
                '<?xml version="1.0"?>'
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>"
            )
            archive.writestr(f"ppt/slides/slide{number}.xml", xml)
    return buffer.getvalue()


def make_xlsx(rows: list[list[str]], shared: list[str]) -> bytes:
    strings = "".join(f"<si><t>{value}</t></si>" for value in shared)
    row_xml = "".join(
        "<row>"
        + "".join(f'<c t="s"><v>{index}</v></c>' if index is not None else "<c/>" for index in row)
        + "</row>"
        for row in rows
    )
    sheet = (
        '<?xml version="1.0"?><worksheet '
        'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"{row_xml}</worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/'
            f'spreadsheetml/2006/main">{strings}</sst>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def make_pdf(text: str) -> bytes:
    """A minimal single-page PDF with a text-drawing operator."""
    escaped = text.replace("(", r"\(").replace(")", r"\)")
    content = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length "
        + str(len(content)).encode()
        + b" >>\nstream\n"
        + content.encode()
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    return bytes(out)


async def test_reads_every_supported_format(storage: FakeStorage) -> None:
    storage.blobs = {
        "key/brief.txt": b"Discuss the causes of the 1929 crash.",
        "key/notes.md": b"# Reading notes\nKey term: liquidity.",
        "key/data.csv": b"year,unemployment\n1929,3.2\n1930,8.7\n",
        "key/essay.docx": make_docx(["Introduction paragraph", "Method section"]),
        "key/deck.pptx": make_pptx(["Opening claim", "Second finding"]),
        "key/table.xlsx": make_xlsx([[0, 1], [2, 3]], ["Region", "Growth", "Total", "Notes"]),
        "key/handout.pdf": make_pdf("Submission must be 3000 words."),
    }
    documents = [
        document("brief.txt", b""),
        document("notes.md", b""),
        document("data.csv", b""),
        document("essay.docx", b""),
        document("deck.pptx", b""),
        document("table.xlsx", b""),
        document("handout.pdf", b""),
    ]

    results = {item["filename"]: item["text"] for item in await extraction.extract_texts(documents)}

    assert "1929" in results["brief.txt"]
    assert "liquidity" in results["notes.md"]
    assert "unemployment" in results["data.csv"] and "1929" in results["data.csv"]
    assert "Introduction paragraph" in results["essay.docx"]
    assert "Method section" in results["essay.docx"]
    # Slide order must survive, otherwise the argument reads backwards.
    assert results["deck.pptx"].index("Opening claim") < results["deck.pptx"].index(
        "Second finding"
    )
    # Spreadsheet cells must be resolved through the shared string table.
    assert "Growth" in results["table.xlsx"] and "Notes" in results["table.xlsx"]
    assert "3000 words" in results["handout.pdf"]


async def test_slides_beyond_nine_keep_their_order(storage: FakeStorage) -> None:
    """A plain string sort would read slide10 before slide2."""
    storage.blobs = {"key/long.pptx": make_pptx([f"slide {n}" for n in range(1, 12)])}

    results = await extraction.extract_texts([document("long.pptx", b"")])
    text = results[0]["text"]

    assert text.index("slide 2") < text.index("slide 10")
    assert text.startswith("slide 1")


async def test_images_are_listed_but_never_given_invented_text(storage: FakeStorage) -> None:
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
        "00000049454e44ae426082"
    )
    storage.blobs = {"key/graph.png": png}

    assert await extraction.extract_texts([document("graph.png", b"")]) == []


async def test_a_corrupt_archive_is_skipped_not_fatal(storage: FakeStorage) -> None:
    storage.blobs = {
        "key/broken.docx": b"PK\x03\x04 this is not really a docx",
        "key/good.txt": b"still readable",
    }

    results = await extraction.extract_texts(
        [document("broken.docx", b""), document("good.txt", b"")]
    )

    assert [item["filename"] for item in results] == ["good.txt"]


async def test_a_zip_bomb_is_refused_before_decompression(storage: FakeStorage) -> None:
    """A declared expansion far beyond the cap must be rejected, not decompressed."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "A" * (extraction._MAX_ARCHIVE_BYTES + 1))
    storage.blobs = {"key/bomb.docx": buffer.getvalue()}

    assert await extraction.extract_texts([document("bomb.docx", b"")]) == []


async def test_malformed_xml_inside_an_archive_is_skipped(storage: FakeStorage) -> None:
    """A well-formed zip holding broken XML must not fail the analysis.

    ``ElementTree.ParseError`` is not a ``ValueError``, so without an explicit catch
    a single corrupt part would abort the whole run.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><unclosed>")
    storage.blobs = {"key/broken.docx": buffer.getvalue(), "key/ok.txt": b"survivor"}

    results = await extraction.extract_texts(
        [document("broken.docx", b""), document("ok.txt", b"")]
    )

    assert [item["filename"] for item in results] == ["ok.txt"]


async def test_a_missing_object_does_not_fail_the_analysis(storage: FakeStorage) -> None:
    assert await extraction.extract_texts([document("gone.txt", b"")]) == []


async def test_the_shared_budget_is_never_exceeded(storage: FakeStorage) -> None:
    chunk = "x" * 5_000
    storage.blobs = {f"key/f{number}.txt": chunk.encode() for number in range(40)}

    results = await extraction.extract_texts(
        [document(f"f{number}.txt", b"") for number in range(40)]
    )

    total = sum(len(item["text"]) for item in results)
    assert total <= extraction.MAX_TOTAL_DOCUMENT_CHARS
    assert len(results) < 40, "the per-analysis budget should stop extraction early"
