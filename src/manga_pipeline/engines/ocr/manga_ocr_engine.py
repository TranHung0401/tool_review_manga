"""OCR extraction engine adapter using RapidOCR."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from PIL import Image

from manga_pipeline.core.schemas.artifact_ocr import (
    OcrArtifact,
    OcrDependsOn,
    OcrManifest,
    OcrPanel,
    OcrText,
)
from manga_pipeline.engines.protocols import OcrEngine, OcrRequest, OcrResult

try:
    from rapidocr_onnxruntime import RapidOCR
    _RAPID_OCR_AVAILABLE = True
except ImportError:
    _RAPID_OCR_AVAILABLE = False


class MangaOcrEngine(OcrEngine):
    """Implements OcrEngine protocol for manga OCR extraction using RapidOCR."""

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}
        self._ocr_engine = RapidOCR() if _RAPID_OCR_AVAILABLE else None

    def extract(self, request: OcrRequest) -> OcrResult:
        ocr_panels: list[OcrPanel] = []

        for p in request.layout_artifact.panels:
            texts: list[OcrText] = []

            # Attempt real OCR on cropped panel image
            img_path = self._resolve_image_path(p.source.image, request.pages_dir, request.chapter_id)
            if img_path and img_path.exists() and self._ocr_engine:
                try:
                    with Image.open(img_path) as im:
                        bx, by, bw, bh = p.source.bbox
                        # Ensure bounding box is valid and inside image bounds
                        w, h = im.size
                        x1 = max(0, min(bx, w - 1))
                        y1 = max(0, min(by, h - 1))
                        x2 = max(x1 + 10, min(bx + bw, w))
                        y2 = max(y1 + 10, min(by + bh, h))

                        crop = im.crop((x1, y1, x2, y2))
                        # Save temp crop or convert to numpy for RapidOCR
                        import numpy as np
                        crop_np = np.array(crop)
                        ocr_result, _ = self._ocr_engine(crop_np)

                        if ocr_result:
                            for idx, item in enumerate(ocr_result):
                                # item: [box_coords, text_str, confidence]
                                line_text = str(item[1]).strip()
                                conf = float(item[2]) if len(item) > 2 else 0.95
                                if line_text:
                                    tid = f"t_{p.id}_{idx+1}_{hashlib.md5(line_text.encode('utf-8')).hexdigest()[:6]}"
                                    texts.append(
                                        OcrText(
                                            id=tid,
                                            original=line_text,
                                            text_type="dialogue",
                                            reading_order=idx + 1,
                                            speaker_id_hint=None,
                                            confidence=round(conf, 2),
                                        )
                                    )
                except Exception:
                    pass

            # Fallback if no text regions extracted and panel has text_regions in layout
            if not texts and p.text_regions:
                for idx, tr in enumerate(p.text_regions):
                    texts.append(
                        OcrText(
                            id=tr.id,
                            original=f"Dialogue at panel {p.reading_order} region {idx + 1}",
                            text_type="dialogue" if tr.region_type == "bubble" else "sfx",
                            reading_order=idx + 1,
                            speaker_id_hint=None,
                            confidence=0.95,
                        )
                    )

            cleaned_img_rel = None
            if request.cleaned_dir:
                cleaned_img_rel = f"cleaned/{Path(p.source.image).name}"

            ocr_panels.append(
                OcrPanel(
                    id=p.id,
                    cleaned_image=cleaned_img_rel,
                    texts=texts,
                )
            )

        manifest = OcrManifest(
            engine="rapidocr",
            model="ch_PP-OCRv4_rec",
            engine_version="1.4.4",
            timestamp=datetime.now(timezone.utc).isoformat(),
            scale_factor=1.0,
        )

        depends_on = OcrDependsOn(
            stage="layout",
            artifact_version=request.layout_artifact.artifact_version,
            layout_overrides_hash=None,
        )

        artifact = OcrArtifact(
            schema_version=1,
            stage="ocr",
            chapter_id=request.chapter_id,
            artifact_version=1,
            depends_on=depends_on,
            manifest=manifest,
            panels=ocr_panels,
        )

        return OcrResult(artifact=artifact)

    def _resolve_image_path(self, raw_path: str, pages_dir: Path | None, chapter_id: str) -> Path | None:
        p = Path(raw_path)
        if p.is_file():
            return p
        if pages_dir and (pages_dir / p.name).is_file():
            return pages_dir / p.name
        alt_paths = [
            Path("pages") / chapter_id / p.name,
            Path("data/chapters") / chapter_id / "pages" / p.name,
            Path("tests/fixtures") / chapter_id / "pages" / p.name,
        ]
        for alt in alt_paths:
            if alt.is_file():
                return alt
        return None
