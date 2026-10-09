import json
from pathlib import Path


class CodeChunker:
    """
    Breaks repository code artifacts into chunks for embedding.
    Each chunk = one embeddable unit (module, class, function, method)
    """

    def __init__(
        self,
        repo_structure_path: str = "storage/repo_structure.json",
        function_index_path: str = "storage/function_index.json",
        class_index_path: str = "storage/class_index.json",
        virtual_repo_path: str = "datasets/virtual_repo"
    ):
        self.repo_structure_path = Path(repo_structure_path)
        self.function_index_path = Path(function_index_path)
        self.class_index_path = Path(class_index_path)
        self.virtual_repo_path = Path(virtual_repo_path)

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def _read_file(self, relative_path: str) -> str:
        """Read actual source code from virtual repo."""
        full_path = self.virtual_repo_path / relative_path
        if not full_path.exists():
            return ""
        try:
            return full_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _extract_function_source(self, source: str, func_name: str) -> str:
        """
        Extract source code of a specific function from a file.
        Uses simple line-by-line extraction.
        """
        lines = source.split("\n")
        result = []
        inside = False
        base_indent = None

        for line in lines:
            stripped = line.lstrip()

            # Detect function start
            if stripped.startswith(f"def {func_name}(") or \
               stripped.startswith(f"async def {func_name}("):
                inside = True
                base_indent = len(line) - len(stripped)
                result.append(line)
                continue

            if inside:
                if not line.strip():
                    result.append(line)
                    continue

                current_indent = len(line) - len(line.lstrip())

                # Function ended when we hit same or lower indentation
                if current_indent <= base_indent and line.strip():
                    break

                result.append(line)

        return "\n".join(result).strip()

    def _extract_class_source(self, source: str, class_name: str) -> str:
        """Extract source code of a specific class from a file."""
        lines = source.split("\n")
        result = []
        inside = False
        base_indent = None

        for line in lines:
            stripped = line.lstrip()

            if stripped.startswith(f"class {class_name}(") or \
               stripped.startswith(f"class {class_name}:"):
                inside = True
                base_indent = len(line) - len(stripped)
                result.append(line)
                continue

            if inside:
                if not line.strip():
                    result.append(line)
                    continue

                current_indent = len(line) - len(line.lstrip())

                if current_indent <= base_indent and line.strip():
                    break

                result.append(line)

        return "\n".join(result).strip()

    def chunk_modules(self) -> list:
        """
        Create one chunk per module - uses full file source.
        id format: module::__module__
        """
        repo_structure = self._load_json(self.repo_structure_path)
        modules = repo_structure.get("modules", [])
        chunks = []

        for module in modules:
            source = self._read_file(module["path"])
            if not source.strip():
                continue

            # Build text representation
            functions = module.get("functions", [])
            classes = module.get("classes", [])

            text = f"Module: {module['name']}\n"
            if functions:
                text += f"Functions: {', '.join(functions)}\n"
            if classes:
                text += f"Classes: {', '.join(classes)}\n"
            text += f"\nSource:\n{source[:2000]}"  # cap at 2000 chars

            chunks.append({
                "id": f"{module['name']}::__module__",
                "type": "module",
                "module": module["name"],
                "path": module["path"],
                "text": text
            })

        return chunks

    def chunk_functions(self) -> list:
        """
        Create one chunk per function.
        id format: module::function_name
        """
        function_index = self._load_json(self.function_index_path)
        repo_structure = self._load_json(self.repo_structure_path)

        # Build path lookup
        path_lookup = {
            m["name"]: m["path"]
            for m in repo_structure.get("modules", [])
        }

        chunks = []
        processed = set()

        for key, info in function_index.items():
            if info["type"] != "function":
                continue

            chunk_id = f"{info['module']}::{info['name']}"
            if chunk_id in processed:
                continue
            processed.add(chunk_id)

            module_path = path_lookup.get(info["module"], info["path"])
            source = self._read_file(module_path)
            func_source = self._extract_function_source(source, info["name"])

            if not func_source:
                func_source = f"function {info['name']} in {info['module']}"

            text = f"Function: {info['name']}\n"
            text += f"Module: {info['module']}\n"
            text += f"Source:\n{func_source[:1500]}"

            chunks.append({
                "id": chunk_id,
                "type": "function",
                "module": info["module"],
                "name": info["name"],
                "path": info["path"],
                "text": text
            })

        return chunks

    def chunk_classes(self) -> list:
        """
        Create one chunk per class.
        id format: module::ClassName
        """
        class_index = self._load_json(self.class_index_path)
        repo_structure = self._load_json(self.repo_structure_path)

        path_lookup = {
            m["name"]: m["path"]
            for m in repo_structure.get("modules", [])
        }

        chunks = []

        for key, info in class_index.items():
            module_path = path_lookup.get(info["module"], info["path"])
            source = self._read_file(module_path)
            class_source = self._extract_class_source(source, info["name"])

            if not class_source:
                class_source = f"class {info['name']} in {info['module']}"

            methods = info.get("methods", [])
            text = f"Class: {info['name']}\n"
            text += f"Module: {info['module']}\n"
            if methods:
                text += f"Methods: {', '.join(methods)}\n"
            text += f"Source:\n{class_source[:1500]}"

            chunks.append({
                "id": f"{info['module']}::{info['name']}",
                "type": "class",
                "module": info["module"],
                "name": info["name"],
                "path": info["path"],
                "text": text
            })

        return chunks

    def chunk_all(self) -> list:
        """Return all chunks: modules + functions + classes."""
        print("Chunking modules...")
        module_chunks = self.chunk_modules()
        print(f"  {len(module_chunks)} module chunks")

        print("Chunking functions...")
        function_chunks = self.chunk_functions()
        print(f"  {len(function_chunks)} function chunks")

        print("Chunking classes...")
        class_chunks = self.chunk_classes()
        print(f"  {len(class_chunks)} class chunks")

        all_chunks = module_chunks + function_chunks + class_chunks
        print(f"  Total: {len(all_chunks)} chunks\n")
        return all_chunks
