from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import json
from typing import Iterable, List
from .document_loader import load_text_document
@dataclass
class Example:
    title: str
    context: str
    output: str
def load_examples(path: Path) -> List[Example]:
    import json
    if path.is_dir():
        return _load_examples_from_directory(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        examples = []
        for item in data:
            examples.append(
                Example(
                    title=item["title"],
                    context=item.get("context", "").strip(),
                    output=item["output"].strip(),
                )
            )
        return examples
    if suffix in {".md", ".txt", ".markdown", ".docx", ".pdf"}:
        content = load_text_document(path)
        return [Example(title=path.stem, context="", output=content)]
    raise ValueError(f"Unsupported examples source: {path}")
def _load_examples_from_directory(path: Path) -> List[Example]:
    examples: List[Example] = []
    for doc in sorted(path.iterdir()):
        if not doc.is_file():
            continue
        suffix = doc.suffix.lower()
        if suffix in {".json"}:
            examples.extend(load_examples(doc))
        elif suffix in {".md", ".txt", ".markdown", ".docx", ".pdf"}:
            content = load_text_document(doc)
            examples.append(Example(title=doc.stem, context="", output=content))
    return examples
def format_examples(examples: Iterable[Example]) -> str:
    lines = []
    for example in examples:
        lines.append(f"### Example: {example.title}\n")
        lines.append("Context:\n")
        lines.append(example.context)
        lines.append("\nExpected Output:\n")
        lines.append(example.output)
        lines.append("\n---\n")
    return "\n".join(lines).strip()
def extract_placeholders(template: str) -> List[str]:
    pattern = re.compile(r"(<[^>]+>|\[\[[^\]]+\]\]|\{[^}]+\}|_{3,})")
    found = set(match.strip() for match in pattern.findall(template))
    return sorted(found)
def build_planning_prompt(
    template: str,
    examples: Iterable[Example],
    code_context: str,
    user_instructions: str | None = None,
    release_type: str = "initial",
) -> str:
    release_label = "initial release" if release_type == "initial" else "update / change request"
    prompt_sections = [
        "You are a Medtronic validation planning assistant.",
        f"This is an {release_label}.",
        "Inspect the template and summarize what must be filled before drafting.",
        "Return JSON only with three keys: {\n"
        "  \"needs\": [ {\"token\": str, \"description\": str, \"where\": str} ],\n"
        "  \"clarifying_questions\": [str],\n"
        "  \"drafting_steps\": [ {\"section\": str, \"tokens\": [str], \"notes\": str} ]\n"
        "}.",
        "Do not generate the draft itself—focus on the fill plan and concise questions to unblock drafting.",
    ]
    if release_type != "initial":
        prompt_sections.append(
            "\nFor an update/change:\n"
            "- Treat the provided examples as the last 2–3 validation/quality assurance documents.\n"
            "- Use the code context sections labeled 'Current code/context', "
            "'Previous version (for updates)', and 'Updated version (for updates)' to understand deltas.\n"
            "- Plan to keep unchanged sections aligned with prior QA docs and focus questions on new or changed behavior."
        )
    if user_instructions and user_instructions.strip():
        prompt_sections.append(
            "\n## Additional user instructions\n"
            "Apply these instructions as constraints for drafting/mapping.\n"
            "If an instruction conflicts with the template text or the code context, DO NOT guess—"
            "add a clarifying question instead.\n"
            + user_instructions.strip()
        )
    prompt_sections.append("\n## Template\n" + template.strip())
    placeholders = extract_placeholders(template)
    if placeholders:
        prompt_sections.append(
            "\n## Detected placeholders\n"
            + "\n".join(f"- {token}" for token in placeholders)
        )
    formatted_examples = format_examples(examples)
    if formatted_examples:
        header = "\n## Reference examples\n"
        if release_type != "initial":
            header += (
                "Treat these as prior validation/quality assurance documents for this tool "
                "or similar tools. Use them as the canonical pattern for tone, sections, and level of detail.\n"
            )
        prompt_sections.append(header + formatted_examples)
    prompt_sections.append(
        "\n## Program code context\n"
        "Use the following code snapshot for grounding; flag any missing pieces that prevent filling the template.\n"
        + code_context.strip()
    )
    prompt_sections.append(
        "\n## Response rules\n"
        "- Output valid JSON only (no code fences).\n"
        "- Keep questions brief and tied to specific tokens or sections.\n"
        "- Suggest drafting steps that map tokens to template sections so a follow-on agent can place them precisely.\n"
    )
    return "\n\n".join(prompt_sections).strip() + "\n"
def build_prompt(
    template: str,
    examples: Iterable[Example],
    code_context: str,
    user_instructions: str | None = None,
    plan_context: str | None = None,
    release_type: str = "initial",
) -> str:
    prompt_sections = [
        "You are an AI assistant that drafts Medtronic validation documentation.",
        "Follow the provided template exactly, replacing placeholders (highlighted in blue in the template) with project-specific content while preserving every heading, bullet, table, and piece of surrounding text.",
        "Use the program code context to ground statements and avoid inventing functionality.",
        "Fill every placeholder you can from the provided information before asking for anything else—only ask clarifying questions for the gaps that remain.",
    ]
    release_label = "initial release" if release_type == "initial" else "update / change request"
    prompt_sections.append(
        "\n## Release context\n"
        + f"This is an {release_label}."
        + (
            "\nIf this is an update, use any comparison code/files to highlight what changed versus the prior version and ask for missing diffs."
            " Keep unchanged sections stable."
            if release_type != "initial"
            else "\nTreat this as a first release; do not assume prior versions."
        )
    )
    if user_instructions and user_instructions.strip():
        prompt_sections.append(
            "\n## Additional user instructions\n"
            "Apply these instructions as constraints for drafting/mapping.\n"
            "If an instruction conflicts with the template text or the code context, DO NOT guess—"
            "add a clarifying question instead.\n"
            + user_instructions.strip()
        )
    prompt_sections.append("\n## Template\n" + template.strip())
    placeholders = extract_placeholders(template)
    if placeholders:
        prompt_sections.append(
            "\n## Template placeholders to map\n"
            "Return structured JSON only, as: {\n"
            "  \"placeholders\": {<token>: <replacement>, ...},\n"
            "  \"answers\": [ {\n"
            "    \"placeholder\": <token or exact blue/instructional text>,\n"
            "    \"replacement\": <what to put there (or 'delete' to remove)>,\n"
            "    \"where\": \"describe the section/table cell this belongs in\"\n"
            "  } ],\n"
            "  \"questions\": [optional, only for items still unknown]\n"
            "}.\n"
            "- Map every placeholder you can infer, including long blue instructional sentences (e.g., the sample purpose statements).\n"
            "- Do NOT embed the full draft; just provide the mappings and any necessary questions.\n"
            "- Keep labels, bullets, and table headers unchanged—only tell the user what to type in place of the placeholder.\n"
            + "\n".join(f"- {token}" for token in placeholders)
        )
    formatted_examples = format_examples(examples)
    if formatted_examples:
        header = "\n## Reference examples\n"
        if release_type != "initial":
            header += (
                "Treat these as the last 2–3 validation/quality assurance documents for this tool "
                "or similar tools. Use them as:\n"
                "- The canonical tone and structure for the updated document, and\n"
                "- The prior QA baseline to keep unchanged sections consistent.\n"
            )
        else:
            header += (
                "Use these documents to match tone, structure, and level of detail for this new validation.\n"
            )
        prompt_sections.append(header + formatted_examples)
    if plan_context and plan_context.strip():
        prompt_sections.append(
            "\n## Drafting plan\n"
            "Use this plan when deciding where to place generated content. If details are missing, ask clarifying questions before replacing placeholders.\n"
            + plan_context.strip()
        )
    if release_type == "initial":
        code_intro = (
            "Use the following code snapshot to ground the validation description. "
            "Focus on behaviors, data flows, risk mitigations, and control mechanisms visible in the code."
        )
    else:
        code_intro = (
            "Use the following code snapshot to ground the validation description.\n"
            "- Sections under '## Current code/context' and lines starting with '# Current File:' describe the current implementation.\n"
            "- Sections under '## Previous version (for updates)' and '# Previous File:' describe the prior implementation.\n"
            "- Sections under '## Updated version (for updates)' and '# Updated File:' describe the new implementation after the change.\n"
            "When drafting answers, describe the behavior of the UPDATED implementation while:\n"
            "- Preserving wording consistent with prior validation docs where behavior is unchanged, and\n"
            "- Explicitly reflecting changes only where the code has actually changed."
        )
    prompt_sections.append(
        "\n## Program code context\n"
        + code_intro
        + "\n"
        + code_context.strip()
    )
    prompt_sections.append(
        "\n## Response rules\n"
        "- Preserve the template's structure conceptually; do not rewrite sections—just tell the user what to type.\n"
        "- Always include your best-effort `placeholders` map and `answers` list even if some items are blank; add `questions` only for the missing pieces.\n"
        "- Do not provide the full draft text; focus on explicit mappings from template text (blue instructions or <tokens>) to replacements.\n"
        "- Maintain clear traceability to the template placeholders and avoid inventing functionality not evidenced in the code context.\n"
        "- Add a `coverage` object that lists any `missing_tokens` and `unmapped_sections` you could not fill so gaps are explicit.\n"
        "- Never fabricate person names or signatures; leave them blank or ask a question when not provided."
    )
    return "\n\n".join(prompt_sections).strip() + "\n"
def build_functional_requirements_prompt(
    draft_prompt: str,
    code_context: str,
    plan_context: str | None = None,
    release_type: str = "initial",
) -> str:
    if release_type == "initial":
        sections: list[str] = [
            "You are a senior engineer writing clear, testable functional requirements for a software change.",
            "",
            "You will be given:",
            "1) The current validation drafting prompt (captures the template structure, tone, and expectations).",
            "2) The relevant program code / workbook / PBIX context.",
            "3) The current planning JSON for this validation (if present).",
            "",
            "Your ONLY job in this call is to derive a complete, testable set of functional requirements for THIS tool/version.It much be an exhaustive list.",
            "",
            "Functional requirements = what the tool SHALL do (externally observable behaviour):",
            "- inputs, processing, and outputs;",
            "- ALL business calculations, formulas, measures, KPIs, and calculated columns that affect what users see or what gets written to outputs;",
            "- transformations and data flows between tables/queries (joins, filters, groupings, aggregations);",
            "- error handling and validation of inputs / data / configuration (including messages, blocking vs. warnings);",
            "- modes, workflows, and options the user can select (e.g., slicers, buttons, macros, toggles);",
            "- configuration that directly affects behaviour of the tool (e.g., threshold values, flags, feature switches, status mappings);",
            "- constraints that are directly testable on the tool’s behaviour (e.g., column width limits, freeze panes, mandatory fields).",
            "",
            "Do NOT include non-functional requirements (performance, security, usability, documentation, process steps).",
            "Do NOT repeat or restate quality-system or SOP requirements.",
        ]
    else:
        sections: list[str] = [
            "You are a senior engineer reviewing a software UPDATE/CHANGE and identifying which functional requirements have changed.",
            "",
            "You will be given:",
            "1) The current validation drafting prompt (captures the template structure, tone, and expectations).",
            "2) The program code / workbook / PBIX context, including:",
            "   - '## Previous version (for updates)' / '# Previous File:' = OLD implementation",
            "   - '## Updated version (for updates)' / '# Updated File:' = NEW implementation",
            "   - '## Current code/context' / '# Current File:' = general/current state",
            "3) The current planning JSON for this validation (if present).",
            "",
            "Your job is to:",
            "A) Identify which functional requirements have CHANGED between the previous and updated versions.",
            "B) For CHANGED requirements: generate NEW requirement descriptions that reflect the updated behavior.",
            "C) For UNCHANGED requirements: copy forward the existing requirement descriptions (if available in prior docs).",
            "",
            "Focus on DELTA analysis:",
            "- What behaviors existed in the OLD version?",
            "- What behaviors exist in the NEW version?",
            "- What changed, was added, or was removed?",
            "",
            "Mark changed requirements clearly so the test documentation can be updated accordingly.",
        ]
    sections.append(
        "\n## Current drafting prompt\n"
        "This is the prompt used in the main mapping call. Use it only as background for scope and intent.\n"
        + (draft_prompt.strip() or "")
    )
    if plan_context and plan_context.strip():
        sections.append(
            "\n## Planning context (JSON)\n"
            "Treat this as a guide to which sections/tokens exist and which behaviours matter most.\n"
            + plan_context.strip()
        )
    sections.append(
        "\n## Program code / workbook / PBIX context\n"
        "Base the requirements primarily on what the implementation actually does.\n"
        + code_context.strip()
    )
    sections.append(
        "\n## Output format (IMPORTANT)\n"
        "Return VALID JSON ONLY, no markdown, no code fences.\n"
        "The top-level value MUST be an array, e.g.:\n"
        "[\n"
        "  {\"Unique Req ID\": \"F1\", \"Description\": \"...\", \"Release Implemented\": \"1.0\"},\n"
        "  {\"Unique Req ID\": \"F2\", \"Description\": \"...\", \"Release Implemented\": \"1.0\"}\n"
        "]\n"
        "\nRules:\n"
        "- Each requirement must be atomic and directly testable (one main behaviour per requirement).\n"
        "- Use IDs F1, F2, F3, ... sequentially with no gaps.\n"
        "- If you are unsure of the exact release number, use \"1.0\" as a placeholder; the caller may override it.\n"
        "- Do NOT include commentary, explanations, or any keys other than: "
        "\"Unique Req ID\", \"Description\", \"Release Implemented\".\n"
        "- Do NOT fabricate behaviours; only include behaviour supported by the drafting prompt, planning context, or code context."
    )
    return "\n\n".join(sections).strip() + "\n"
def build_design_update_prompt(
    template: str,
    examples: Iterable[Example],
    code_context: str,
    prior_json: str,
    user_instructions: str | None = None,
    plan_context: str | None = None,
    release_type: str = "initial",
) -> str:
    """
    Second-pass refinement that focuses ONLY on design-related placeholders/answers.
    - Input: template, QA examples, code/PBIX/Excel context, and prior JSON mappings.
    - Output: UPDATED JSON with the same overall structure, but richer content
      for design/UX-related fields.
    """
    release_label = (
        "initial release"
        if release_type == "initial"
        else "update / change request"
    )
    sections: list[str] = [
        "You are an AI assistant updating Medtronic validation mappings.",
        "In this pass, your ONLY goal is to enrich and refine DESIGN-related content.",
        "",
        "Treat the existing JSON as the source of truth for non-design fields.",
        "You must keep all non-design placeholders and answers unchanged unless there is a clear contradiction.",
        "",
        "Design-related content includes:",
        "- Sections, placeholders, or answers about UI/UX, layout, pages, navigation, visuals, dashboards, reports, charts.",
        "- Anything under headings like 'Design', 'Tool Design', 'Report Layout', 'User Interface', 'Screen Design', etc.",
        "",
        "You MUST ground all design commentary in QUALITY ASSURANCE documentation and actual context:",
        "- The validation template text.",
        "- The provided example validation documents (these are QA docs).",
        "- The PBIX/Excel/code context (data model, report pages, visuals, etc.).",
        "",
        "Do NOT invent features, pages, visuals, or behaviours that are not supported by this context.",
        "If you cannot support a design claim from the QA docs or code/report context, either:",
        "- Leave the design placeholder short and generic, or",
        "- Add / keep a clarifying question instead of guessing.",
    ]
    sections.append(
        "\n## Release context\n"
        f"This is an {release_label}. "
        "If this is an update, you may refine the design description to mention relevant changes, "
        "but only when they are clearly implied by the context."
    )
    if user_instructions and user_instructions.strip():
        sections.append(
            "\n## Additional user instructions\n"
            "Apply these instructions as constraints for drafting/mapping.\n"
            "If an instruction conflicts with the template text or the code context, DO NOT guess—"
            "add a clarifying question instead.\n"
            + user_instructions.strip()
        )
    sections.append("\n## Template\n" + template.strip())
    formatted_examples = format_examples(examples)
    if formatted_examples:
        sections.append(
            "\n## Quality assurance examples\n"
            "Treat these as QA reference documents for tone, structure, and what must be documented.\n"
            "Use them to constrain and justify your design descriptions.\n"
            + formatted_examples
        )
    if plan_context and plan_context.strip():
        sections.append(
            "\n## Planning JSON\n"
            "Use this only to understand which sections exist and how they relate; "
            "do NOT change its structure.\n"
            + plan_context.strip()
        )
    sections.append(
        "\n## Program code / PBIX / Excel context\n"
        "Use this to anchor discussion of report pages, visuals, and data model.\n"
        "Focus especially on sections like 'Report pages and visuals' and 'Data model'.\n"
        + code_context.strip()
    )
    sections.append(
        "\n## Prior JSON mapping\n"
        "You MUST start from this JSON. Your job is to produce a NEW JSON that:\n"
        "- Preserves the same top-level structure and keys (placeholders, answers, questions, coverage, etc.).\n"
        "- Keeps all non-design answers unchanged.\n"
        "- Enriches design-related answers with more detailed, QA-grounded descriptions.\n"
        "- You may also add clarifying questions ONLY where design details are genuinely missing.\n"
        + prior_json.strip()
    )
    sections.append(
        "\n## Response rules\n"
        "- Output VALID JSON only (no code fences).\n"
        "- Maintain the same overall JSON schema: placeholders (map), answers (list), questions (list), coverage, etc.\n"
        "- Only modify design-related placeholders/answers/questions:\n"
        "  - Look for tokens or text mentioning: design, layout, UI, UX, screen, dashboard, report page, visualization, chart, slicer, navigation, user workflow.\n"
        "  - For those fields, expand into richer, multi-sentence descriptions grounded in the QA docs and code/report context.\n"
        "- For all other fields, copy the existing values exactly.\n"
        "- If you are not sure about a specific design detail, either:\n"
        "  - Keep the existing shorter answer, or\n"
        "  - Add/retain a clarifying question (do NOT invent specifics).\n"
        "- Never fabricate person names, signatures, or regulatory identifiers.\n"
    )
    return "\n\n".join(sections).strip() + "\n"
def build_testing_alignment_prompt(
    *,
    functional_requirements: list[dict],
    existing_testing_doc,
) -> str:
    n = len(functional_requirements or [])
    existing_text = (
        json.dumps(existing_testing_doc, indent=2)
        if not isinstance(existing_testing_doc, str)
        else existing_testing_doc
    )
    req_ids = [
        str(r.get("Unique Req ID") or r.get("ID") or r.get("id") or f"F{i+1}")
        for i, r in enumerate(functional_requirements or [])
    ]
    return "\n\n".join([
        "You are updating the Testing Documentation so it matches the Functional Requirements EXACTLY (1 test per requirement).",
        "",
        "Return ONLY valid JSON (no markdown, no code fences) in EXACTLY this shape:",
        "{",
        '  "testing_documentation": [',
        '    {',
        '      "ID": "FT1",',
        f'      "REQ": "{req_ids[0] if req_ids else "F1"}",',
        '      "Description": "…",',
        '      "Outcome": "TBD",',
        '      "Pass/Fail": "TBD",',
        '      "Tester Name": "(empty)",',
        '      "Date": "(empty)"',
        '    }',
        '  ]',
        "}",
        "",
        "HARD RULES:",
        f"- There are {n} requirements. You MUST generate EXACTLY {n} test cases.",
        "- One test per requirement (NO grouping).",
        "- Same order as the requirements list.",
        "- IDs must be FT1..FTN sequentially.",
        f"- REQ must match this exact list in order: {json.dumps(req_ids)}",
        "- Do NOT invent Tester Name or Date; must be '(empty)'.",
        "- Outcome and Pass/Fail must both be exactly 'TBD'.",
        "",
        "Functional Requirements (authoritative):",
        json.dumps(functional_requirements, indent=2),
        "",
        "Existing Testing Documentation (style reference only):",
        existing_text,
    ]).strip() + "\n"
def build_update_prompt(
    template: str,
    examples: Iterable[Example],
    code_context: str,
    prior_json: str,
    user_instructions: str | None = None,
    answered: list[tuple[str, str]] | None = None,
    plan_context: str | None = None,
    release_type: str = "initial",
    missing_tokens: list[str] | None = None,
) -> str:
    answered = answered or []
    missing_tokens = [tok for tok in (missing_tokens or []) if tok]
    prompt_sections = [
        "You are an AI assistant that updates Medtronic validation mappings.",
        "You will be given the template, prior JSON mappings (placeholders/answers/questions), and new user-provided answers.",
        "Merge them into an updated JSON while preserving existing values unless they conflict with the new answers.",
        "Return JSON only with the keys: placeholders, answers (list of {question, answer, placeholder?}), and questions (still-open items).",
        "Fill every placeholder you can infer from the new answers, examples, template cues, and code context; keep unknowns blank and list them in questions.",
        "Never fabricate person names or signatures—leave them blank or move them to questions when missing.",
    ]
    release_label = "initial release" if release_type == "initial" else "update / change request"
    prompt_sections.append(
        "\n## Release context\n"
        + f"This is an {release_label}."
        + (
            "\nIf this is an update, use the new answers, comparison files, and code context to align deltas while keeping unchanged sections intact."
            if release_type != "initial"
            else "\nTreat this as a first release; do not fabricate prior-version differences."
        )
    )
    if user_instructions and user_instructions.strip():
        prompt_sections.append(
            "\n## Additional user instructions\n"
            "Apply these instructions as constraints for drafting/mapping.\n"
            "If an instruction conflicts with the template text or the code context, DO NOT guess—"
            "add a clarifying question instead.\n"
            + user_instructions.strip()
        )
    prompt_sections.append("\n## Template\n" + template.strip())
    placeholders = extract_placeholders(template)
    if placeholders:
        prompt_sections.append(
            "\n## Template placeholders to map\n" + "\n".join(f"- {token}" for token in placeholders)
        )
    formatted_examples = format_examples(examples)
    if formatted_examples:
        prompt_sections.append("\n## Reference examples\n" + formatted_examples)
    if plan_context and plan_context.strip():
        prompt_sections.append(
            "\n## Drafting plan\n"
            "Use this plan when deciding where to place generated content.\n"
            + plan_context.strip()
        )
    if missing_tokens:
        prompt_sections.append(
            "\n## Missing placeholders to fill\n"
            "Focus on filling these remaining template tokens using context."
            " Leave a token blank only if it truly cannot be inferred.\n"
            + "\n".join(f"- {tok}" for tok in missing_tokens)
        )
    prompt_sections.append(
        "\n## Program code context\n"
        "Ground replacements in the provided code details.\n"
        + code_context.strip()
    )
    prompt_sections.append(
        "\n## Prior JSON mapping\n"
        "Update this JSON instead of starting over. Keep existing answers unless replaced by new input.\n"
        + prior_json.strip()
    )
    if answered:
        answered_lines = [f"- Q: {q}\n  A: {a}" for q, a in answered if q or a]
        prompt_sections.append(
            "\n## New answers to merge\n" + "\n".join(answered_lines)
        )
    prompt_sections.append(
        "\n## Response rules\n"
        "- Output valid JSON only (no code fences).\n"
        "- Return placeholders map plus answers list and remaining questions.\n"
        "- Reuse prior values when still valid; add new inferred placeholder fills based on the answers and template cues.\n"
        "- Include a `coverage` object listing any `missing_tokens` and `unmapped_sections` that are still unresolved.\n"
        "- Do not invent person names or signatures; leave them blank or add a clarifying question.\n"
        "- If a placeholder appears multiple times, ensure the same value is reused consistently.\n"
    )
    return "\n\n".join(prompt_sections).strip() + "\n"