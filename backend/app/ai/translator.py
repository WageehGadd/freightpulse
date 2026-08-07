import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

class TranslationError(Exception):
    """Exception raised for translation errors."""


class CarrierTranslator:
    """
    A service for translating carrier advisories from Arabic to English.
    
    This class handles lazy loading of the Helsinki-NLP translation model
    and provides methods for language detection and translation.
    """
    
    def __init__(self) -> None:
        """Initialize the translator without loading the model."""
        self.model_name: str = "Helsinki-NLP/opus-mt-ar-en"
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._is_loaded: bool = False

    def _load_model(self) -> None:
        """
        Lazily loads the translation model and tokenizer.
        
        Raises:
            TranslationError: If the model fails to load.
        """
        if self._is_loaded:
            return
            
        logger.info("Loading translation model %s", self.model_name)
        start_time = time.time()
        
        try:
            # Import here to avoid slow startup for components not using translation
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
            self._is_loaded = True
            
            duration = time.time() - start_time
            logger.info("Successfully loaded translation model in %.2f seconds", duration)
        except Exception as e:
            logger.error("Failed to load translation model: %s", str(e))
            raise TranslationError(f"Model loading failed: {e}") from e

    def detect_language(self, text: str) -> str:
        """
        Detects if the text is primarily Arabic or English based on Unicode ranges.
        
        Args:
            text: The text to analyze.
            
        Returns:
            "ar" if Arabic characters are detected, otherwise "en".
        """
        if not text:
            return "en"
            
        # Arabic Unicode block is \u0600-\u06FF, \u0750-\u077F, \u08A0-\u08FF, etc.
        # A simple heuristic: check if there are Arabic characters in the text
        arabic_pattern = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+')
        if arabic_pattern.search(text):
            logger.debug("Detected language: Arabic")
            return "ar"
            
        logger.debug("Detected language: English")
        return "en"

    def translate(self, text: str) -> str:
        """
        Translates Arabic text to English. Returns English text unchanged.
        
        Args:
            text: The text to translate.
            
        Returns:
            The translated English text, or the original text if it's already English.
            
        Raises:
            TranslationError: If the translation process fails.
        """
        if not text.strip():
            return text
            
        detected_lang = self.detect_language(text)
        if detected_lang == "en":
            return text
            
        logger.info("Starting translation for Arabic text")
        start_time = time.time()
        
        self._load_model()
        
        try:
            inputs = self._tokenizer(text, return_tensors="pt", padding=True)  # type: ignore
            outputs = self._model.generate(**inputs)  # type: ignore
            translated_text = self._tokenizer.decode(outputs[0], skip_special_tokens=True)  # type: ignore
            
            duration = time.time() - start_time
            logger.info("Translation finished in %.2f seconds", duration)
            return translated_text
        except Exception as e:
            logger.error("Translation failed: %s", str(e))
            raise TranslationError(f"Translation failed: {e}") from e

    def translate_batch(self, texts: list[str]) -> list[str]:
        """
        Translates a batch of texts.
        
        English texts are kept unchanged. Arabic texts are translated.
        
        Args:
            texts: A list of texts to translate.
            
        Returns:
            A list of translated texts.
            
        Raises:
            TranslationError: If the translation process fails.
        """
        if not texts:
            return []
            
        results = []
        texts_to_translate = []
        indices_to_translate = []
        
        # Pre-process batch
        for i, text in enumerate(texts):
            if not text.strip() or self.detect_language(text) == "en":
                results.append(text)
            else:
                results.append("")  # Placeholder
                texts_to_translate.append(text)
                indices_to_translate.append(i)
                
        if not texts_to_translate:
            return results
            
        logger.info("Starting batch translation for %d items", len(texts_to_translate))
        start_time = time.time()
        
        self._load_model()
        
        try:
            inputs = self._tokenizer(texts_to_translate, return_tensors="pt", padding=True, truncation=True)  # type: ignore
            outputs = self._model.generate(**inputs)  # type: ignore
            
            translated_texts = self._tokenizer.batch_decode(outputs, skip_special_tokens=True)  # type: ignore
            
            # Reconstruct full list
            for i, translated_text in zip(indices_to_translate, translated_texts):
                results[i] = translated_text
                
            duration = time.time() - start_time
            logger.info("Batch translation finished in %.2f seconds", duration)
            
            return results
        except Exception as e:
            logger.error("Batch translation failed: %s", str(e))
            raise TranslationError(f"Batch translation failed: {e}") from e
