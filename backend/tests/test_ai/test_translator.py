import sys
from unittest.mock import MagicMock

# Mock transformers module before any imports happen
mock_transformers = MagicMock()
sys.modules["transformers"] = mock_transformers

import pytest

from backend.app.ai.translator import CarrierTranslator, TranslationError


@pytest.fixture
def translator():
    """Provides a fresh CarrierTranslator and resets mocks."""
    mock_transformers.reset_mock()
    return CarrierTranslator()

def test_detect_language_arabic(translator):
    text = "تأخير في ميناء لوس أنجلوس"
    assert translator.detect_language(text) == "ar"

def test_detect_language_english(translator):
    text = "Delay at Port of Los Angeles"
    assert translator.detect_language(text) == "en"

def test_detect_language_mixed_defaults_to_arabic(translator):
    text = "Port delay: تأخير في ميناء"
    assert translator.detect_language(text) == "ar"

def test_detect_language_empty(translator):
    assert translator.detect_language("") == "en"

def test_translate_english_unchanged(translator):
    text = "No translation needed."
    result = translator.translate(text)
    
    assert result == text
    # Ensure model was not loaded
    mock_transformers.AutoModelForSeq2SeqLM.from_pretrained.assert_not_called()
    mock_transformers.AutoTokenizer.from_pretrained.assert_not_called()

def test_translate_arabic(translator):
    text = "مرحبا"
    expected_translation = "Hello"
    
    mock_tokenizer_instance = MagicMock()
    mock_tokenizer_instance.return_value = {"input_ids": [1, 2, 3]}
    mock_tokenizer_instance.decode.return_value = expected_translation
    mock_transformers.AutoTokenizer.from_pretrained.return_value = mock_tokenizer_instance
    
    mock_model_instance = MagicMock()
    mock_model_instance.generate.return_value = [[4, 5, 6]]
    mock_transformers.AutoModelForSeq2SeqLM.from_pretrained.return_value = mock_model_instance
    
    result = translator.translate(text)
    
    assert result == expected_translation
    mock_transformers.AutoTokenizer.from_pretrained.assert_called_once_with("Helsinki-NLP/opus-mt-ar-en")
    mock_transformers.AutoModelForSeq2SeqLM.from_pretrained.assert_called_once_with("Helsinki-NLP/opus-mt-ar-en")
    mock_model_instance.generate.assert_called_once()
    mock_tokenizer_instance.decode.assert_called_once_with([4, 5, 6], skip_special_tokens=True)

def test_model_loaded_only_once(translator):
    text = "مرحبا"
    
    mock_tokenizer_instance = MagicMock()
    mock_tokenizer_instance.decode.return_value = "Hello"
    mock_transformers.AutoTokenizer.from_pretrained.return_value = mock_tokenizer_instance
    
    mock_model_instance = MagicMock()
    mock_model_instance.generate.return_value = [[4, 5, 6]]
    mock_transformers.AutoModelForSeq2SeqLM.from_pretrained.return_value = mock_model_instance
    
    translator.translate(text)
    translator.translate(text)  # Second call
    
    # Should only be called once despite two translations
    mock_transformers.AutoTokenizer.from_pretrained.assert_called_once()
    mock_transformers.AutoModelForSeq2SeqLM.from_pretrained.assert_called_once()
    assert mock_model_instance.generate.call_count == 2

def test_translate_batch(translator):
    texts = ["Hello", "مرحبا", "World", "عالم"]
    expected_translations = ["Hello", "Hello (translated)", "World", "World (translated)"]
    
    mock_tokenizer_instance = MagicMock()
    mock_tokenizer_instance.batch_decode.return_value = ["Hello (translated)", "World (translated)"]
    mock_transformers.AutoTokenizer.from_pretrained.return_value = mock_tokenizer_instance
    
    mock_model_instance = MagicMock()
    mock_model_instance.generate.return_value = [[1], [2]]
    mock_transformers.AutoModelForSeq2SeqLM.from_pretrained.return_value = mock_model_instance
    
    results = translator.translate_batch(texts)
    
    assert results == expected_translations
    # Ensure it only processes the Arabic texts (indices 1 and 3)
    mock_tokenizer_instance.assert_called_once_with(["مرحبا", "عالم"], return_tensors="pt", padding=True, truncation=True)
    mock_model_instance.generate.assert_called_once()

def test_translation_error(translator):
    text = "مرحبا"
    
    mock_transformers.AutoTokenizer.from_pretrained.side_effect = Exception("Mock loading error")
    
    with pytest.raises(TranslationError, match="Mock loading error"):
        translator.translate(text)
