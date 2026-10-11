"""Dispatch declared materials without disguising text or images as PDF."""
import hashlib
from pathlib import Path

from src.core.types import Document


class MaterialLoader:
    extensions = (".pdf", ".txt", ".md", ".xml", ".cs", ".png")

    def __init__(self, pdf_loader, *, collection, image_storage_dir=None):
        self.pdf_loader = pdf_loader
        self.collection = collection
        self.image_storage_dir = Path(image_storage_dir) if image_storage_dir is not None else None

    def load(self, file_path):
        path = Path(file_path).resolve(strict=True)
        suffix = path.suffix.lower()
        if suffix not in self.extensions:
            raise ValueError("MATERIAL_TYPE_UNSUPPORTED")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if suffix == ".pdf":
            document = self.pdf_loader.load(str(path))
        elif suffix == ".png":
            from PIL import Image
            with Image.open(path) as image:
                if image.format != "PNG":
                    raise ValueError("MATERIAL_IMAGE_FORMAT_INVALID")
                image.verify()
            image_id = hashlib.sha256((self.collection + ":" + digest).encode()).hexdigest()
            stored_path = path
            if self.image_storage_dir is not None:
                self.image_storage_dir.mkdir(parents=True, exist_ok=True)
                stored_path = self.image_storage_dir / (image_id + ".png")
                if stored_path.exists():
                    if hashlib.sha256(stored_path.read_bytes()).hexdigest() != digest:
                        raise ValueError("MATERIAL_IMAGE_STORAGE_CHANGED")
                else:
                    with stored_path.open("xb") as stream:
                        stream.write(raw)
            placeholder = f"[IMAGE: {image_id}]"
            document = Document(id=digest, text=placeholder, metadata={
                "source_path": str(path), "doc_type": "image", "title": path.stem,
                "images": [{"id": image_id, "path": str(stored_path), "page": 0,
                            "text_offset": 0, "text_length": len(placeholder)}]})
        else:
            document = Document(id=digest, text=raw.decode("utf-8-sig"), metadata={
                "source_path": str(path), "doc_type": suffix[1:], "title": path.stem})
        document.metadata.update(source_hash=digest, original_file_sha256=digest,
                                 parsed_text_sha256=hashlib.sha256(document.text.encode()).hexdigest(),
                                 parser="pdf" if suffix == ".pdf" else "image_reference" if suffix == ".png" else "utf8_text")
        return document
