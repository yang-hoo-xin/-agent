from pathlib import Path
import json

from pypdf import PdfReader


SOURCES = [
    Path(r"C:\Users\10160\Desktop\ai_learn\大模型应用算法学习路线+八股+面试实战_3- Part 1 副本.pdf"),
    Path(r"C:\Users\10160\Desktop\ai_learn\大模型应用算法学习路线+八股+面试实战_3- Part 2 副本.pdf"),
]
OUT = Path("tmp/pdf_extract")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for part, source in enumerate(SOURCES, start=1):
        reader = PdfReader(str(source))
        pages = []
        for page_no, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append({"page": page_no, "text": text})
        (OUT / f"part{part}.json").write_text(
            json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (OUT / f"part{part}.txt").write_text(
            "\n\n".join(f"===== PAGE {p['page']} =====\n{p['text']}" for p in pages),
            encoding="utf-8",
        )
        empty = [p["page"] for p in pages if len(p["text"].strip()) < 20]
        print(
            f"part{part}: pages={len(pages)} chars={sum(len(p['text']) for p in pages)} "
            f"near_empty={len(empty)} {empty[:30]}"
        )


if __name__ == "__main__":
    main()
