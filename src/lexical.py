"""Configurable English BM25 preprocessing. No downloaded NLP data is needed."""

import hashlib
import json
import math
import re
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path


class LexicalPreprocessor:
    def __init__(self, stopwords=False, stemming=False, preserve_words=(), stopwords_file=None):
        if type(stopwords) is not bool or type(stemming) is not bool:
            raise ValueError("stopwords and stemming must be booleans")
        self.stopwords = stopwords
        self.stemming = stemming
        self.preserve_words = sorted(set(word.casefold() for word in preserve_words))
        self.stop_words = frozenset()
        source = None
        packages = {}
        if stopwords:
            if stopwords_file:
                source = str(Path(stopwords_file).resolve())
                words = [line.strip().casefold() for line in Path(source).read_text(encoding="utf-8").splitlines()
                         if line.strip() and not line.lstrip().startswith("#")]
            else:
                from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
                words = ENGLISH_STOP_WORDS
                source = "sklearn.feature_extraction.text.ENGLISH_STOP_WORDS"
                packages["scikit-learn"] = version("scikit-learn")
            self.stop_words = frozenset(words) - set(self.preserve_words)
        self._stem = None
        if stemming:
            from nltk.stem import PorterStemmer
            stemmer = PorterStemmer(mode=PorterStemmer.NLTK_EXTENSIONS)
            self._stem = lru_cache(maxsize=50_000)(stemmer.stem)
            packages["nltk"] = version("nltk")
        self.metadata = {
            "normalization": "casefold + regex \\w+", "remove_stopwords": stopwords,
            "stopwords_source": source, "stopwords_count": len(self.stop_words),
            "stopwords_sha256": hashlib.sha256(json.dumps(sorted(self.stop_words)).encode()).hexdigest(),
            "preserve_words": self.preserve_words, "stemming": "PorterStemmer.NLTK_EXTENSIONS" if stemming else None,
            "order": ["normalize", "remove_stopwords", "stem"], "versions": packages,
        }

    def __call__(self, text):
        words = re.findall(r"\w+", text.casefold())
        if self.stopwords:
            words = [word for word in words if word not in self.stop_words]
        if self._stem:
            words = [self._stem(word) for word in words]
        return words


def build_bm25(tokenized_chunks, k1=1.5, b=0.75, epsilon=0.25):
    from rank_bm25 import BM25Okapi
    if not math.isfinite(k1) or k1 <= 0:
        raise ValueError("BM25 k1 must be finite and positive")
    if not math.isfinite(b) or not 0 <= b <= 1:
        raise ValueError("BM25 b must be finite and between 0 and 1")
    if not math.isfinite(epsilon) or epsilon < 0:
        raise ValueError("BM25 epsilon must be finite and nonnegative")
    return BM25Okapi(tokenized_chunks, k1=k1, b=b, epsilon=epsilon) if any(tokenized_chunks) else None
