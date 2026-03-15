import re


class DiffParser:

    FUNCTION_PATTERN = re.compile(r"(?:async\s+def|def)\s+([a-zA-Z0-9_]+)\s*\(")
    CLASS_PATTERN = re.compile(r"class\s+([a-zA-Z0-9_]+)\s*(?:\(|:)")
    HUNK_HEADER_PATTERN = re.compile(r"@@.*@@\s*(.*)")

    def extract_changed_functions(self, patch_text: str):

        analysis = self.analyze_patch(patch_text)
        return analysis["changed_functions"]

    def analyze_patch(self, patch_text: str):

        changed_functions = set()
        changed_classes = set()
        modified_symbols = set()
        lines_added = 0
        lines_deleted = 0
        current_symbol = None

        for line in patch_text.split("\n"):

            header_match = self.HUNK_HEADER_PATTERN.match(line)
            if header_match:
                current_symbol = self._extract_symbol_from_context(header_match.group(1))
                continue

            if not (line.startswith("+") or line.startswith("-")):
                continue

            if line.startswith("+++") or line.startswith("---"):
                continue

            if line.startswith("+"):
                lines_added += 1
            elif line.startswith("-"):
                lines_deleted += 1

            content = line[1:]
            function_match = self.FUNCTION_PATTERN.search(content)
            class_match = self.CLASS_PATTERN.search(content)

            if function_match:
                function_name = function_match.group(1)
                changed_functions.add(function_name)
                modified_symbols.add(function_name)
                current_symbol = function_name
                continue

            if class_match:
                class_name = class_match.group(1)
                changed_classes.add(class_name)
                modified_symbols.add(class_name)
                current_symbol = class_name
                continue

            if current_symbol and content.strip() and not content.lstrip().startswith("#"):
                modified_symbols.add(current_symbol)

        return {
            "changed_functions": sorted(changed_functions),
            "changed_classes": sorted(changed_classes),
            "modified_symbols": sorted(modified_symbols),
            "lines_added": lines_added,
            "lines_deleted": lines_deleted
        }

    def _extract_symbol_from_context(self, context: str):

        function_match = self.FUNCTION_PATTERN.search(context)
        if function_match:
            return function_match.group(1)

        class_match = self.CLASS_PATTERN.search(context)
        if class_match:
            return class_match.group(1)

        return None
