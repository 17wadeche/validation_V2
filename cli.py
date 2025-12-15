from __future__ import annotations
import argparse
import sys
from pathlib import Path
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
ROOT = Path(__file__).parent
sys.path.append(str(ROOT / "src"))
from validation_agent import ValidationAgent  # type: ignore  # noqa: E402
from validation_agent.docx_utils import DocxExportError, draft_to_docx_bytes  # type: ignore  # noqa: E402
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Medtronic validation drafts")
    parser.add_argument("template", type=Path, help="Path to the validation template file")
    parser.add_argument("examples", type=Path, help="Path to JSON list of example validations")
    parser.add_argument("code", nargs="+", type=Path, help="Paths to source code or directories")
    parser.add_argument("--output", "-o", type=Path, help="Optional path to write the draft")
    parser.add_argument("--docx-output", type=Path, help="Optional path to write the draft as a Word document")
    parser.add_argument("--plan-only", action="store_true", help="Return a planning JSON instead of a draft")
    parser.add_argument("--plan-output", type=Path, help="Optional path to write the planning JSON")
    parser.add_argument("--plan-input", type=Path, help="Existing planning JSON to guide drafting")
    return parser.parse_args()
def main() -> None:
    args = parse_args()
    agent = ValidationAgent()
    plan_context = None
    if args.plan_only or args.plan_output:
        plan_context = agent.plan_document(args.template, args.examples, args.code)
        if args.plan_output:
            args.plan_output.write_text(plan_context, encoding="utf-8")
        if not args.plan_only:
            pass
        else:
            if not args.plan_output:
                print(plan_context)
            return
    if args.plan_input:
        plan_context = Path(args.plan_input).read_text(encoding="utf-8")
    draft = agent.generate_draft(
        args.template, args.examples, args.code, plan_context=plan_context
    )
    if args.output:
        args.output.write_text(draft, encoding="utf-8")
    if args.docx_output:
        try:
            docx_bytes = draft_to_docx_bytes(draft)
            args.docx_output.write_bytes(docx_bytes)
        except DocxExportError as exc:
            raise SystemExit(str(exc))
    if not args.output and not args.docx_output:
        print(draft)
if __name__ == "__main__":
    main()