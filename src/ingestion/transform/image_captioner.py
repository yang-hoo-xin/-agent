"""Image Captioner transform for enriching chunks with image descriptions.

Performance Optimizations:
1. Only processes images that are actually referenced in chunk text (via [IMAGE: id] placeholder)
2. Uses caption cache to avoid redundant Vision API calls for the same image
3. Skips chunks without image references entirely
4. Parallel processing of unique images with thread-safe caching
"""

import re
import hashlib
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Dict

from src.core.settings import Settings
from src.core.types import Chunk
from src.core.trace.trace_context import TraceContext
from src.ingestion.transform.base_transform import BaseTransform
from src.libs.llm.base_vision_llm import BaseVisionLLM, ImageInput
from src.libs.llm.llm_factory import LLMFactory
from src.observability.logger import get_logger

logger = get_logger(__name__)

# Regex to find image placeholders: [IMAGE: some_id]
IMAGE_PLACEHOLDER_PATTERN = re.compile(r'\[IMAGE:\s*([^\]]+)\]')

# Default max parallel workers for Vision API calls
DEFAULT_MAX_WORKERS = 3  # Lower than text LLM due to higher cost/latency


class ImageCaptioner(BaseTransform):
    """Generates captions for images referenced in chunks using Vision LLM.
    
    This transform identifies chunks containing image references, uses a Vision LLM
    to generate descriptive captions, and enriches the chunk text/metadata with
    these captions to improve retrieval for visual content.
    
    Key Features:
    - Only processes images actually referenced in chunk text (not all images in metadata)
    - Caches captions to avoid redundant Vision API calls
    - Thread-safe caption cache for potential future parallelization
    """
    
    def __init__(
        self, 
        settings: Settings, 
        llm: Optional[BaseVisionLLM] = None
    ):
        self.settings = settings
        self.llm = None
        # Caption cache: image_id -> caption string (thread-safe with lock)
        self._caption_cache: Dict[str, str] = {}
        self._captions_by_id = {}
        self._key_locks = {}
        self.last_observation = {"api_calls": 0, "cache_hits": 0, "failed": 0, "status": "not_run"}
        self._cache_lock = threading.Lock()
        
        # Check if vision LLM is enabled in settings
        if self.settings.vision_llm and self.settings.vision_llm.enabled:
             try:
                 self.llm = llm or LLMFactory.create_vision_llm(settings)
             except Exception as e:
                 logger.error(f"Failed to initialize Vision LLM: {e}")
                 # We don't raise here to allow pipeline to continue without captioning
                 # effectively falling back to no-op for this transform
        else:
             logger.warning("Vision LLM is disabled or not configured. ImageCaptioner will skip processing.")
        
        self.prompt = self._load_prompt()
        
    def _load_prompt(self) -> str:
        """Load the image captioning prompt from configuration."""
        # Assuming standard relative path. In production, logic might be robust.
        from src.core.settings import resolve_path
        prompt_path = resolve_path("config/prompts/image_captioning.txt")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").strip()
        return "Describe this image in detail for indexing purposes."

    def _find_referenced_image_ids(self, text: str) -> List[str]:
        """Extract image IDs actually referenced in the chunk text.
        
        Args:
            text: Chunk text content
            
        Returns:
            List of image IDs found in [IMAGE: id] placeholders
        """
        matches = IMAGE_PLACEHOLDER_PATTERN.findall(text)
        return [m.strip() for m in matches]

    def _get_caption(
        self, 
        img_id: str, 
        img_path: str, 
        trace: Optional[TraceContext] = None
    ) -> Optional[str]:
        """Get caption for an image, using cache if available. Thread-safe.
        
        Args:
            img_id: Image identifier
            img_path: Path to image file
            trace: Optional trace context
            
        Returns:
            Caption string or None if failed
        """
        if not img_path or not Path(img_path).is_file():
            with self._cache_lock:
                self.last_observation["failed"] += 1
            return None
        identity = {"image_sha256": hashlib.sha256(Path(img_path).read_bytes()).hexdigest(),
            "prompt_sha256": hashlib.sha256(self.prompt.encode()).hexdigest(),
            "provider": self.settings.vision_llm.provider, "model": self.settings.vision_llm.model,
            "model_revision": getattr(self.settings.vision_llm, "model_revision", None),
            "context_window": getattr(self.settings.vision_llm, "context_window", None),
            "max_tokens": getattr(self.settings.vision_llm, "max_tokens", None),
            "base_url": getattr(self.settings.vision_llm, "base_url", None)}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self._cache_lock:
            lock = self._key_locks.setdefault(key, threading.Lock())
        with lock:
            return self._caption_bound(img_id, img_path, key, identity, trace)

    def _caption_bound(self, img_id, img_path, key, identity, trace):
        started = time.perf_counter()
        with self._cache_lock:
            if key in self._caption_cache:
                self.last_observation["cache_hits"] += 1
                self._captions_by_id[img_id] = self._caption_cache[key]
                if trace is not None:
                    trace.record_stage("image_caption_cache", {**identity, "cache_hit": True, "api_calls": 0})
                return self._caption_cache[key]
        
        # Validate path
        if not img_path or not Path(img_path).exists():
            logger.warning(f"Image path not found: {img_path}")
            return None
        
        try:
            with self._cache_lock:
                self.last_observation["api_calls"] += 1
            image_input = ImageInput(path=img_path)
            response = self.llm.chat_with_image(
                text=self.prompt,
                image=image_input,
                trace=trace
            )
            caption = response.content
            if not isinstance(caption, str) or not caption.strip():
                raise ValueError("IMAGE_CAPTION_EMPTY")
            if hashlib.sha256(Path(img_path).read_bytes()).hexdigest() != identity["image_sha256"]:
                raise ValueError("IMAGE_CHANGED_DURING_CAPTION")
            
            # Cache the result (thread-safe write)
            with self._cache_lock:
                self._caption_cache[key] = caption
                self._captions_by_id[img_id] = caption
            if trace is not None:
                trace.record_stage("image_caption_call", {**identity, "cache_hit": False, "api_calls": 1,
                    "status": "succeeded", "usage": getattr(response, "usage", None)},
                    elapsed_ms=(time.perf_counter() - started) * 1000)
            logger.debug(f"Generated and cached caption for image {img_id}")
            
            return caption
            
        except Exception as e:
            with self._cache_lock:
                self.last_observation["failed"] += 1
            if trace is not None:
                trace.record_stage("image_caption_call", {**identity, "cache_hit": False, "api_calls": 1,
                    "status": "failed", "error_type": type(e).__name__}, elapsed_ms=(time.perf_counter() - started) * 1000)
            logger.error(f"Failed to caption image {img_path}: {e}")
            return None

    def transform(
        self,
        chunks: List[Chunk],
        trace: Optional[TraceContext] = None
    ) -> List[Chunk]:
        """Process chunks and add captions for referenced images.
        
        Only processes images that are actually referenced in chunk text
        via [IMAGE: id] placeholders. Uses caching to avoid redundant API calls.
        Parallel processing for unique images.
        """
        if not self.llm:
            self.last_observation = {"status": "disabled_or_initialization_failed", "api_calls": 0, "cache_hits": 0, "failed": 0}
            return chunks
        
        # Build image lookup from all chunks' metadata
        image_lookup: Dict[str, dict] = {}
        for chunk in chunks:
            if chunk.metadata and "images" in chunk.metadata:
                for img_meta in chunk.metadata.get("images", []):
                    img_id = img_meta.get("id")
                    if img_id and img_id not in image_lookup:
                        image_lookup[img_id] = img_meta
        
        logger.info(f"Found {len(image_lookup)} unique images in document")
        
        with self._cache_lock:
            self._captions_by_id.clear()
            self.last_observation = {"status": "running", "api_calls": 0, "cache_hits": 0, "failed": 0}
        
        # First pass: collect all unique image IDs that need captioning
        images_to_caption: Dict[str, str] = {}  # img_id -> img_path
        for chunk in chunks:
            referenced_ids = self._find_referenced_image_ids(chunk.text)
            for img_id in referenced_ids:
                if img_id not in images_to_caption:
                    img_meta = image_lookup.get(img_id)
                    if img_meta and img_meta.get("path"):
                        images_to_caption[img_id] = img_meta.get("path")
        
        # Parallel caption generation for all unique images
        if images_to_caption:
            self._generate_captions_parallel(images_to_caption, trace)
        
        # Second pass: apply captions to chunks
        processed_chunks = []
        total_captions_added = 0
        
        for chunk in chunks:
            referenced_ids = self._find_referenced_image_ids(chunk.text)
            
            if not referenced_ids:
                processed_chunks.append(chunk)
                continue
            
            new_text = chunk.text
            captions = []
            
            for img_id in referenced_ids:
                img_id_stripped = img_id.strip()
                
                # Get caption from cache (already populated by parallel processing)
                with self._cache_lock:
                    caption = self._captions_by_id.get(img_id_stripped)
                
                if caption:
                    captions.append({"id": img_id_stripped, "caption": caption})
                    
                    placeholder = f"[IMAGE: {img_id}]"
                    replacement = f"[IMAGE: {img_id}]\n(Description: {caption})"
                    new_text = new_text.replace(placeholder, replacement)
                    total_captions_added += 1
                    
            chunk.text = new_text
            
            if captions:
                if "image_captions" not in chunk.metadata:
                    chunk.metadata["image_captions"] = []
                chunk.metadata["image_captions"].extend(captions)
            
            processed_chunks.append(chunk)
        
        with self._cache_lock:
            api_calls = self.last_observation["api_calls"]
            self.last_observation.update(status="partial" if self.last_observation["failed"] else "completed",
                images_requested=len(images_to_caption), images_captioned=len(self._captions_by_id))
        logger.info(f"Added {total_captions_added} captions, API calls: {api_calls}")
            
        return processed_chunks
    
    def _generate_captions_parallel(
        self, 
        images_to_caption: Dict[str, str],
        trace: Optional[TraceContext] = None
    ) -> None:
        """Generate captions for multiple images in parallel.
        
        Args:
            images_to_caption: Dict of img_id -> img_path
            trace: Optional trace context
        """
        if not images_to_caption:
            return
        
        max_workers = min(getattr(self.settings.ingestion, "image_max_workers", DEFAULT_MAX_WORKERS), len(images_to_caption))
        logger.debug(f"Generating captions for {len(images_to_caption)} images (max_workers={max_workers})")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._get_caption, img_id, img_path, trace): img_id
                for img_id, img_path in images_to_caption.items()
            }
            
            for future in as_completed(futures):
                img_id = futures[future]
                try:
                    caption = future.result()
                    if caption:
                        logger.debug(f"Caption generated for {img_id}")
                except Exception as e:
                    logger.error(f"Failed to generate caption for {img_id}: {e}")
