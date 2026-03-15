import json
import chromadb
from pathlib import Path


class SimilarityEngine:
    """
    Stores embeddings in ChromaDB and performs
    vector similarity search over code artifacts.
    """

    def __init__(self, storage_path: str = "storage/semantic_index"):
        self.storage_path = storage_path
        Path(storage_path).mkdir(parents=True, exist_ok=True)

        # Persistent ChromaDB client
        self.client = chromadb.PersistentClient(path=storage_path)
        self.collection = self.client.get_or_create_collection(
            name="code_embeddings",
            metadata={"hnsw:space": "cosine"}  # cosine similarity
        )

    def index_chunks(self, embedded_chunks: list[dict]):
        """
        Store all embedded chunks in ChromaDB.
        Clears old index first to avoid stale data.
        """
        if not embedded_chunks:
            print("No chunks to index.")
            return

        # Clear existing collection
        try:
            self.client.delete_collection("code_embeddings")
            self.collection = self.client.get_or_create_collection(
                name="code_embeddings",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            pass

        ids = []
        embeddings = []
        metadatas = []
        documents = []

        for chunk in embedded_chunks:
            if not chunk.get("embedding"):
                continue

            ids.append(chunk["id"])
            embeddings.append(chunk["embedding"])
            documents.append(chunk["text"][:500])  # store preview

            # Store metadata (no embedding — too large)
            metadatas.append({
                "type": chunk["type"],
                "module": chunk["module"],
                "path": chunk.get("path", ""),
                "name": chunk.get("name", chunk["module"])
            })

        # ChromaDB batch limit is 5461
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            self.collection.add(
                ids=ids[i:i + batch_size],
                embeddings=embeddings[i:i + batch_size],
                metadatas=metadatas[i:i + batch_size],
                documents=documents[i:i + batch_size]
            )

        print(f"Indexed {len(ids)} chunks into ChromaDB\n")

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        chunk_type: str = None
    ) -> list[dict]:
        """
        Find most similar chunks to a query embedding.
        Optionally filter by chunk type (module/function/class).
        """
        where = {"type": chunk_type} if chunk_type else None

        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, self.collection.count()),
                where=where,
                include=["metadatas", "distances", "documents"]
            )
        except Exception as e:
            print(f"Search error: {e}")
            return []

        matches = []
        if not results["ids"] or not results["ids"][0]:
            return []

        for i, doc_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            # Convert cosine distance to similarity score
            score = round(1 - distance, 4)
            metadata = results["metadatas"][0][i]

            matches.append({
                "id": doc_id,
                "score": score,
                "type": metadata.get("type"),
                "module": metadata.get("module"),
                "name": metadata.get("name"),
                "path": metadata.get("path"),
                "preview": results["documents"][0][i][:200]
            })

        return sorted(matches, key=lambda x: x["score"], reverse=True)

    def collection_size(self) -> int:
        try:
            return self.collection.count()
        except Exception:
            return 0