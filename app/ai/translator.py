import re
import logging
from typing import List

logger = logging.getLogger(__name__)

ARABIC_PATTERN = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


class TranslationError(Exception):
    """Raised when machine translation model fails."""


class CarrierTranslator:
    def __init__(self, model_name: str = "Helsinki-NLP/opus-mt-ar-en"):
        self.model_name = model_name
        self._tokenizer = None
        self._model = None

    def detect_language(self, text: str) -> str:
        if not text or not text.strip():
            return "en"
        if ARABIC_PATTERN.search(text):
            return "ar"
        return "en"

    def _load_model(self):
        if self._tokenizer is None or self._model is None:
            try:
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
            except Exception as exc:
                raise TranslationError(f"Failed to load translation model '{self.model_name}': {exc}") from exc

    def translate(self, text: str) -> str:
        if not text or self.detect_language(text) != "ar":
            return text

        self._load_model()
        try:
            inputs = self._tokenizer(text, return_tensors="pt", padding=True, truncation=True)
            input_ids = inputs["input_ids"] if isinstance(inputs, dict) else inputs
            outputs = self._model.generate(input_ids)
            decoded = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
            return decoded
        except TranslationError:
            raise
        except Exception as exc:
            raise TranslationError(f"Translation inference failed: {exc}") from exc

    def translate_batch(self, texts: List[str]) -> List[str]:
        if not texts:
            return []

        arabic_indices = []
        arabic_texts = []

        for idx, text in enumerate(texts):
            if self.detect_language(text) == "ar":
                arabic_indices.append(idx)
                arabic_texts.append(text)

        if not arabic_texts:
            return list(texts)

        self._load_model()
        try:
            inputs = self._tokenizer(arabic_texts, return_tensors="pt", padding=True, truncation=True)
            outputs = self._model.generate(**inputs if isinstance(inputs, dict) else {"input_ids": inputs})
            decoded_list = self._tokenizer.batch_decode(outputs, skip_special_tokens=True)

            results = list(texts)
            for idx, decoded in zip(arabic_indices, decoded_list):
                results[idx] = decoded
            return results
        except TranslationError:
            raise
        except Exception as exc:
            raise TranslationError(f"Batch translation failed: {exc}") from exc
