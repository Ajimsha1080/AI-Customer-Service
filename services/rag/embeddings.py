import os
import math
from abc import ABC, abstractmethod
from typing import List, Optional, Any

class BaseEmbeddingProvider(ABC):
    """Abstract Base Class for swappable vector embedding providers."""

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Embeds a single text string into a float vector."""
        pass

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embeds a batch of text strings into float vectors."""
        return [self.embed_text(t) for t in texts]

class SentenceTransformersEmbeddingProvider(BaseEmbeddingProvider):
    """Real dense semantic embedding provider using sentence-transformers (all-MiniLM-L6-v2).
    Default named provider chosen for zero API cost, local inference, and high semantic quality (384-dim).
    """
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except Exception as e:
                print(f"[Embeddings] Could not load sentence-transformers model ({e}). Falling back to MockEmbeddings.")
                self._model = False

    def embed_text(self, text: str) -> List[float]:
        self._load_model()
        if self._model and self._model is not False:
            vec = self._model.encode(text, convert_to_numpy=True).tolist()
            return vec
        # Fallback deterministic normalized embedding
        return MockEmbeddingProvider().embed_text(text)

class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding provider using text-embedding-3-small (1536-dim)."""
    def __init__(self, model: str = "text-embedding-3-small", api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

    def embed_text(self, text: str) -> List[float]:
        if not self.api_key or self.api_key.startswith("sk-mock"):
            return MockEmbeddingProvider(dimension=1536).embed_text(text)
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            response = client.embeddings.create(input=[text], model=self.model)
            return response.data[0].embedding
        except Exception as e:
            print(f"[Embeddings] OpenAI API call failed: {e}. Falling back to MockEmbeddings.")
            return MockEmbeddingProvider(dimension=1536).embed_text(text)

class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic stem/ngram semantic vector generator for offline and fast test environments."""
    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    def embed_text(self, text: str) -> List[float]:
        # Normalize punctuation and tokenize
        clean_text = text.lower()
        for char in [".", "?", ",", "!", ":", ";", "(", ")", "-", "_"]:
            clean_text = clean_text.replace(char, " ")
        words = [w for w in clean_text.split() if len(w) > 1]
        
        if not words:
            words = [text.lower()]

        vector = [0.0] * self.dimension
        for word in words:
            # Use 4-character stem for basic mock semantic overlap (e.g. swim / swimming)
            stem = word[:4]
            hash_val = sum(ord(c) * (idx + 1) for idx, c in enumerate(stem))
            for i in range(self.dimension):
                vector[i] += math.sin(hash_val * (i + 1))

        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

def get_embedding_provider(provider_name: Optional[str] = None) -> BaseEmbeddingProvider:
    """Swappable factory function for embedding provider selection.
    Defaults to mock for fast offline execution, or sentence_transformers / openai if specified.
    """
    selected = provider_name or os.getenv("EMBEDDING_PROVIDER", "mock")
    selected_lower = selected.lower()

    if selected_lower in ("openai", "openai_embeddings"):
        return OpenAIEmbeddingProvider()
    elif selected_lower in ("sentence_transformers", "sentence-transformers"):
        return SentenceTransformersEmbeddingProvider()
    else:
        return MockEmbeddingProvider()
