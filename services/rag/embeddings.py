import os
import math
import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, Any

class BaseEmbeddingProvider(ABC):
    """Abstract Base Class for swappable vector embedding providers."""
    model_name: str = "unknown"
    dimension: int = 384

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Embeds a single text string into a float vector."""
        pass

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embeds a batch of text strings into float vectors."""
        return [self.embed_text(t) for t in texts]

    async def embed_text_async(self, text: str) -> List[float]:
        """Asynchronously embeds text without blocking the event loop."""
        return await asyncio.to_thread(self.embed_text, text)

    async def embed_documents_async(self, texts: List[str]) -> List[List[float]]:
        """Asynchronously embeds documents without blocking the event loop."""
        return await asyncio.to_thread(self.embed_documents, texts)

class SentenceTransformersEmbeddingProvider(BaseEmbeddingProvider):
    """Real dense semantic embedding provider using sentence-transformers (all-MiniLM-L6-v2).
    Default named provider chosen for zero API cost, local inference, and high semantic quality (384-dim).
    """
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.dimension = 384
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except Exception as e:
                is_prod = os.getenv("ENVIRONMENT", "").lower() == "production"
                if is_prod:
                    raise RuntimeError(f"Failed to load SentenceTransformers model in production: {e}")
                print(f"[Embeddings] Could not load sentence-transformers model ({e}). Falling back to MockEmbeddings.")
                self._model = False

    def embed_text(self, text: str) -> List[float]:
        self._load_model()
        if self._model and self._model is not False:
            vec = self._model.encode(text, convert_to_numpy=True).tolist()
            return vec
        is_prod = os.getenv("ENVIRONMENT", "").lower() == "production"
        if is_prod:
            raise RuntimeError("In production, sentence-transformers model is required. Mock fallback is forbidden.")
        # Fallback deterministic normalized embedding
        return MockEmbeddingProvider(dimension=self.dimension).embed_text(text)

class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding provider using text-embedding-3-small (1536-dim)."""
    def __init__(self, model: str = "text-embedding-3-small", api_key: Optional[str] = None):
        self.model = model
        self.model_name = model
        self.dimension = 1536 if "large" not in model else 3072
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

    def embed_text(self, text: str) -> List[float]:
        is_prod = os.getenv("ENVIRONMENT", "").lower() == "production"
        if not self.api_key or self.api_key.startswith("sk-mock"):
            if is_prod:
                raise RuntimeError("In production, valid OPENAI_API_KEY is required. Mock fallback is forbidden.")
            return MockEmbeddingProvider(dimension=self.dimension).embed_text(text)
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            response = client.embeddings.create(input=[text], model=self.model)
            return response.data[0].embedding
        except Exception as e:
            if is_prod:
                raise RuntimeError(f"OpenAI embedding API call failed in production: {e}")
            print(f"[Embeddings] OpenAI API call failed: {e}. Falling back to MockEmbeddings.")
            return MockEmbeddingProvider(dimension=self.dimension).embed_text(text)

class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic stem/ngram semantic vector generator for offline and fast test environments."""
    def __init__(self, dimension: int = 384):
        is_prod = os.getenv("ENVIRONMENT", "").lower() == "production"
        if is_prod:
            raise RuntimeError("Mock embeddings cannot be used in production. A real embedding provider (OpenAI or SentenceTransformers) is required.")
        self.dimension = dimension
        self.model_name = f"mock-embedding-{dimension}"

    def embed_text(self, text: str) -> List[float]:
        is_prod = os.getenv("ENVIRONMENT", "").lower() == "production"
        if is_prod:
            raise RuntimeError("In production, mock embedding provider is strictly prohibited.")
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
    In production (ENVIRONMENT=production), mock provider is prohibited and will raise RuntimeError.
    """
    is_prod = os.getenv("ENVIRONMENT", "").lower() == "production"
    selected = provider_name or os.getenv("EMBEDDING_PROVIDER", "sentence_transformers" if is_prod else "mock")
    selected_lower = selected.lower()

    if selected_lower in ("openai", "openai_embeddings"):
        return OpenAIEmbeddingProvider()
    elif selected_lower in ("sentence_transformers", "sentence-transformers"):
        return SentenceTransformersEmbeddingProvider()
    else:
        if is_prod:
            raise RuntimeError("In production, a real embedding provider (OpenAI or SentenceTransformers) is required. Mock embeddings are prohibited.")
        return MockEmbeddingProvider()
