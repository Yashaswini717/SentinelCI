import os
import time
import requests


class CodeEmbedder:
    """
    Generates embeddings using OpenRouter API.
    Model: qwen/qwen3-embedding-0.6b (free, works for code)
    """

    def __init__(self, model: str = "openai/text-embedding-3-small"):
        self.model = model
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.base_url = "https://openrouter.ai/api/v1/embeddings"

        if not self.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY not set.\n"
                "Run: $env:OPENROUTER_API_KEY='your-key-here'"
            )

        print(f"CodeEmbedder ready - model: {self.model}\n")

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Make a single API call to OpenRouter embeddings endpoint."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/SentinelCI",
            "X-Title": "SentinelCI"
        }

        payload = {
            "model": self.model,
            "input": texts
        }

        response = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code != 200:
            raise Exception(
                f"OpenRouter API error: {response.status_code} "
                f"{response.text}"
            )

        data = response.json()
        return [item["embedding"] for item in data["data"]]

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        try:
            embeddings = self._call_api([text[:4096]])
            return embeddings[0] if embeddings else []
        except Exception as e:
            print(f"Embedding error: {e}")
            return []

    def embed_batch(self, texts: list[str], batch_size: int = 10) -> list[list[float]]:
        """Generate embeddings in batches."""
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            print(f"  Embedding batch {i // batch_size + 1} "
                  f"({min(i + batch_size, len(texts))}/{len(texts)})...")

            try:
                safe_batch = [t[:4096] for t in batch]
                embeddings = self._call_api(safe_batch)
                all_embeddings.extend(embeddings)

                # Small delay for rate limits
                if i + batch_size < len(texts):
                    time.sleep(0.5)

            except Exception as e:
                print(f"  Batch error: {e}")
                all_embeddings.extend([[] for _ in batch])

        return all_embeddings

    def embed_chunks(self, chunks: list[dict]) -> list[dict]:
        """Add embeddings to each chunk."""
        texts = [chunk["text"] for chunk in chunks]
        print(f"Generating embeddings for {len(texts)} chunks...")

        embeddings = self.embed_batch(texts)

        embedded_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            if embedding:
                chunk["embedding"] = embedding
                embedded_chunks.append(chunk)

        print(f"Successfully embedded {len(embedded_chunks)} chunks\n")
        return embedded_chunks
