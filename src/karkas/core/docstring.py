"""Docstring parsing and cleaning utilities for Karkas."""

import inspect
import re


def clean_summary(doc: str | None) -> str:
    """Extract strictly the first concise summary sentence from a docstring.

    Strips reST / Google doc tags (:param, :return, Args:, etc.), multiline bullets,
    and returns a clean, single-line description suitable for catalogs and diagrams.
    """
    if not doc:
        return ""

    cleaned = inspect.cleandoc(doc).strip()
    if not cleaned:
        return ""

    # Stop before any parameter or return block
    lines = cleaned.splitlines()
    summary_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if summary_lines:
                break
            continue

        # Check for tags
        if stripped.startswith((":", "@", "Args:", "Returns:", "Raises:", "Yields:")):
            break
        if re.match(r"^-[ ]+", stripped) or re.match(r"^\*[ ]+", stripped):
            break

        summary_lines.append(stripped)

    if not summary_lines:
        return ""

    full_summary = " ".join(summary_lines).strip()

    # Match first sentence ending with a dot, exclamation, or question mark
    sentence_match = re.search(r"^(.*?[.!?])(?:\s+|$)", full_summary)
    if sentence_match:
        result = sentence_match.group(1).strip()
    else:
        result = full_summary

    # Ensure no internal double-brackets or mermaid-breaking chars
    result = result.replace("[[", "").replace("]]", "").replace('"', "'")
    return result


def format_docstring_markdown(raw_doc: str | None) -> str:
    """Format a docstring into clean GitHub-flavored markdown.

    Converts reST tags (:param, :return, :raises) into readable markdown lists.
    """
    if not raw_doc:
        return ""

    cleaned = inspect.cleandoc(raw_doc).strip()
    if not cleaned:
        return ""

    lines = cleaned.splitlines()
    summary_parts: list[str] = []
    params: list[tuple[str, str]] = []
    returns: list[str] = []
    raises: list[tuple[str, str]] = []

    mode = "summary"
    current_item: list[str] = []
    current_key = ""

    def flush_current():
        nonlocal current_key, current_item, mode
        if not current_key and not current_item:
            return
        text = " ".join(current_item).strip()
        if mode == "param":
            params.append((current_key, text))
        elif mode == "return":
            returns.append(text)
        elif mode == "raises":
            raises.append((current_key, text))
        current_key = ""
        current_item = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if mode == "summary":
                flush_current()
            continue

        # Check for :param name: or :ivar name:
        param_match = re.match(r"^:(?:param|ivar)\s+([a-zA-Z0-9_]+):\s*(.*)$", stripped)
        if param_match:
            flush_current()
            mode = "param"
            current_key = param_match.group(1)
            if param_match.group(2):
                current_item.append(param_match.group(2))
            continue

        # Check for :return: or :returns:
        return_match = re.match(r"^:returns?:\s*(.*)$", stripped)
        if return_match:
            flush_current()
            mode = "return"
            current_key = "return"
            if return_match.group(1):
                current_item.append(return_match.group(1))
            continue

        # Check for :raises Exception:
        raises_match = re.match(r"^:raises?\s+([a-zA-Z0-9_]+):\s*(.*)$", stripped)
        if raises_match:
            flush_current()
            mode = "raises"
            current_key = raises_match.group(1)
            if raises_match.group(2):
                current_item.append(raises_match.group(2))
            continue

        # Skip :type ...: tags
        if re.match(r"^:type\s+.*:$", stripped):
            continue

        if mode == "summary":
            summary_parts.append(stripped)
        else:
            current_item.append(stripped)

    flush_current()

    md_output: list[str] = []
    if summary_parts:
        md_output.append(" ".join(summary_parts))

    if params:
        md_output.append("\n**Parameters:**")
        for p_name, p_desc in params:
            desc_str = f" — {p_desc}" if p_desc else ""
            md_output.append(f"- `{p_name}`{desc_str}")

    if returns:
        md_output.append("\n**Returns:**")
        for r_desc in returns:
            md_output.append(f"- {r_desc}")

    if raises:
        md_output.append("\n**Raises:**")
        for r_name, r_desc in raises:
            desc_str = f" — {r_desc}" if r_desc else ""
            md_output.append(f"- `{r_name}`{desc_str}")

    return "\n".join(md_output)
