from __future__ import annotations
from pathlib import Path
from typing import Callable, Iterable, Optional
from .document_loader import load_text_document
from .prompt_builder import Example, build_planning_prompt, build_prompt, load_examples
from .workbook_loader import extract_excel_context, extract_pbix_context
LLMCallable = Callable[[str], str]
def load_code_context(paths: Iterable[Path], max_chars: int = 12000) -> str:
    parts: list[str] = []
    total = 0
    for path in paths:
        if total >= max_chars:
            break
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if not child.is_file():
                    continue
                snippet = _read_snippet(child, max_chars - total)
                if not snippet:
                    continue
                parts.append(f"\n# File: {child}\n{snippet}\n")
                total += len(snippet)
                if total >= max_chars:
                    break
        elif path.is_file():
            snippet = _read_snippet(path, max_chars - total)
            if not snippet:
                continue
            parts.append(f"\n# File: {path}\n{snippet}\n")
            total += len(snippet)
    return "".join(parts).strip()
def _read_snippet(path: Path, remaining: int) -> str:
    if remaining <= 0:
        return ""
    suffix = path.suffix.lower()
    try:
        if suffix in {".xlsm", ".xlsx", ".xls", ".xlsb"}:
            return extract_excel_context(path, max_chars=remaining)
        if suffix == ".pbix":
            return extract_pbix_context(path, max_chars=remaining)
        return path.read_text(encoding="utf-8", errors="ignore")[:remaining]
    except Exception:
        return ""
class ValidationAgent:
    def __init__(self, llm_callable: Optional[LLMCallable] = None) -> None:
        self.llm_callable = llm_callable
    def create_prompt(
        self,
        template_path: Path,
        examples_path: Path,
        code_paths: Iterable[Path],
        plan_context: str | None = None,
        release_type: str = "initial",
    ) -> str:
        template = load_text_document(template_path)
        examples = load_examples(examples_path)
        code_context = load_code_context(code_paths)
        return build_prompt(
            template,
            examples,
            code_context,
            plan_context=plan_context,
            release_type=release_type,
        )
    def plan_document(
        self, template_path: Path, examples_path: Path, code_paths: Iterable[Path]
    ) -> str:
        template = load_text_document(template_path)
        examples = load_examples(examples_path)
        code_context = load_code_context(code_paths)
        planning_prompt = build_planning_prompt(template, examples, code_context)
        if self.llm_callable:
            return self.llm_callable(planning_prompt)
        return planning_prompt
    def generate_draft(
        self,
        template_path: Path,
        examples_path: Path,
        code_paths: Iterable[Path],
        plan_context: str | None = None,
        release_type: str = "initial",
    ) -> str:
        prompt = self.create_prompt(
            template_path,
            examples_path,
            code_paths,
            plan_context=plan_context,
            release_type=release_type,
        )
        if self.llm_callable:
            return self.llm_callable(prompt)
        return prompt