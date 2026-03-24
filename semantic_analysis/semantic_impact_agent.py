import json
from pathlib import Path
from semantic_analysis.code_chunker import CodeChunker
from semantic_analysis.code_embedder import CodeEmbedder
from semantic_analysis.similarity_engine import SimilarityEngine


class SemanticImpactAgent:
    """
    Phase 5 Agent.
    Finds semantically related code that static analysis misses.

    Flow:
      1. Chunk all repository code
      2. Embed all chunks
      3. Index in ChromaDB
      4. For each changed symbol from PR, search for similar code
      5. Return ranked semantic impact results
    """

    def __init__(
        self,
        pr_analysis_path: str = "storage/pr_analysis.json",
        function_index_path: str = "storage/function_index.json",
        class_index_path: str = "storage/class_index.json",
        repo_structure_path: str = "storage/repo_structure.json",
        virtual_repo_path: str = "datasets/virtual_repo",
        storage_path: str = "storage/semantic_index",
        similarity_threshold: float = 0.75,
        top_k: int = 10,
        embedding_model: str = "openai/text-embedding-3-small"
    ):
        self.pr_analysis_path = Path(pr_analysis_path)
        self.function_index_path = Path(function_index_path)
        self.class_index_path = Path(class_index_path)
        self.repo_structure_path = Path(repo_structure_path)
        self.virtual_repo_path = virtual_repo_path
        self.storage_path = storage_path
        self.similarity_threshold = similarity_threshold
        self.top_k = top_k

        self.chunker = CodeChunker(
            repo_structure_path=repo_structure_path,
            function_index_path=function_index_path,
            class_index_path=class_index_path,
            virtual_repo_path=virtual_repo_path
        )
        self.embedder = CodeEmbedder(model=embedding_model)
        self.engine = SimilarityEngine(storage_path=storage_path)

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def _get_changed_symbols(self) -> list[dict]:
        """
        Extract changed symbols from PR analysis.
        Returns list of {id, name, module, type} dicts.
        """
        pr_analysis = self._load_json(self.pr_analysis_path)
        function_index = self._load_json(self.function_index_path)
        class_index = self._load_json(self.class_index_path)

        changed_functions = pr_analysis.get("changed_functions", [])
        changed_classes = pr_analysis.get("changed_classes", [])
        changed_modules = pr_analysis.get("changed_modules", [])

        symbols = []

        # Find changed functions in function index
        for func_name in changed_functions:
            for key, info in function_index.items():
                if info["name"] == func_name and \
                   info["module"] in changed_modules:
                    symbols.append({
                        "id": f"{info['module']}::{func_name}",
                        "name": func_name,
                        "module": info["module"],
                        "type": "function"
                    })
                    break

        # Find changed classes in class index
        for class_name in changed_classes:
            for key, info in class_index.items():
                if info["name"] == class_name and \
                   info["module"] in changed_modules:
                    symbols.append({
                        "id": f"{info['module']}::{class_name}",
                        "name": class_name,
                        "module": info["module"],
                        "type": "class"
                    })
                    break

        # Always include changed modules themselves
        for module in changed_modules:
            symbols.append({
                "id": f"{module}::__module__",
                "name": module,
                "module": module,
                "type": "module"
            })

        return symbols

    def _get_chunk_text_for_symbol(self, symbol: dict) -> str:
        """
        Get the text representation of a changed symbol
        to use as the search query.
        """
        chunks = []

        if symbol["type"] == "function":
            chunks = self.chunker.chunk_functions()
        elif symbol["type"] == "class":
            chunks = self.chunker.chunk_classes()
        else:
            chunks = self.chunker.chunk_modules()

        for chunk in chunks:
            if chunk["id"] == symbol["id"]:
                return chunk["text"]

        return f"{symbol['type']} {symbol['name']} in {symbol['module']}"

    def _generate_reason(self, match: dict, symbol: dict) -> str:
        """Generate a human readable reason for the semantic match."""
        match_name = match.get("name", match["module"])
        symbol_name = symbol["name"]
        score = match["score"]

        if score >= 0.90:
            strength = "very similar"
        elif score >= 0.85:
            strength = "similar"
        else:
            strength = "semantically related"

        type_map = {
            "function": "function logic",
            "class": "class structure",
            "module": "module functionality"
        }
        context = type_map.get(match["type"], "code pattern")

        return f"{strength} {context} to {symbol_name}"

    def build_index(self):
        """
        Step 1+2+3: Chunk -> Embed -> Index
        Call this once per repository.
        """
        print("-- Building Semantic Index -------------------\n")

        # Check if index already exists
        if self.engine.collection_size() > 0:
            print(f"Semantic index already exists "
                  f"({self.engine.collection_size()} chunks). Skipping rebuild.\n")
            return

        # Chunk all code
        all_chunks = self.chunker.chunk_all()

        if not all_chunks:
            print("No chunks generated. Check virtual_repo exists.")
            return

        # Generate embeddings
        embedded_chunks = self.embedder.embed_chunks(all_chunks)

        # Store in ChromaDB
        self.engine.index_chunks(embedded_chunks)

    def search_semantic_impact(self, force_reindex: bool = False) -> dict:
        """
        Main Phase 5 method.
        Find semantically related code for all changed symbols.
        """
        # Rebuild index if forced or empty
        if force_reindex or self.engine.collection_size() == 0:
            self.build_index()

        changed_symbols = self._get_changed_symbols()

        if not changed_symbols:
            return {
                "changed_symbols": [],
                "semantic_related_modules": [],
                "total_semantic_matches": 0
            }

        print(f"Searching semantic impact for "
              f"{len(changed_symbols)} changed symbols...\n")

        all_matches = {}  # module -> best score

        for symbol in changed_symbols:
            print(f"  Searching for: {symbol['id']}")

            # Get text for this symbol
            query_text = self._get_chunk_text_for_symbol(symbol)

            # Generate embedding for the query
            query_embedding = self.embedder.embed_text(query_text)

            if not query_embedding:
                continue

            # Search ChromaDB
            results = self.engine.search(
                query_embedding=query_embedding,
                top_k=self.top_k
            )

            # Filter by threshold and exclude self
            for match in results:
                if match["score"] < self.similarity_threshold:
                    continue

                # Skip if it's the changed module itself
                if match["module"] in \
                   [s["module"] for s in changed_symbols]:
                    continue

                module = match["module"]

                # Keep best score per module
                if module not in all_matches or \
                   match["score"] > all_matches[module]["score"]:
                    all_matches[module] = {
                        "module": module,
                        "score": match["score"],
                        "match_type": match["type"],
                        "matched_symbol": match["name"],
                        "reason": self._generate_reason(match, symbol),
                        "changed_symbol": symbol["id"],
                        "path": match["path"]
                    }

        # Sort by score descending
        ranked_matches = sorted(
            all_matches.values(),
            key=lambda x: x["score"],
            reverse=True
        )

        # Format changed symbols for output
        changed_symbol_ids = [s["id"] for s in changed_symbols]

        result = {
            "changed_symbols": changed_symbol_ids,
            "semantic_related_modules": [
                {
                    "module": m["module"],
                    "score": m["score"],
                    "reason": m["reason"],
                    "match_type": m["match_type"],
                    "matched_symbol": m["matched_symbol"],
                    "path": m["path"],
                    "changed_symbol": m["changed_symbol"]
                }
                for m in ranked_matches
            ],
            "total_semantic_matches": len(ranked_matches)
        }

        return result

    def save(self, output_path: str = "storage/semantic_impact.json",
             force_reindex: bool = False) -> dict:
        """Run semantic analysis and save results."""
        result = self.search_semantic_impact(force_reindex=force_reindex)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump(result, f, indent=2)

        print(f"\nSaved semantic impact -> {output_path}")
        return result
