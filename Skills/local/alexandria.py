from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Skills.app import SkillBase, SkillResult

KNOWLEDGE_DIR = Path("UI/instances/knowledge")


def _get_kb_dir() -> Path:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    return KNOWLEDGE_DIR


# ════════════════════════════════════════════════════════════════
# Tools for Alexandria (Knowledge & RAG)
# ════════════════════════════════════════════════════════════════

def search_knowledge_vault(query: str) -> str:
    """Search through documents and notes in the local knowledge vault for relevant text or keywords."""
    query = (query or "").strip().lower()
    if not query:
        return "Please provide a search query."
    kb_dir = _get_kb_dir()
    files = list(kb_dir.glob("*.md")) + list(kb_dir.glob("*.txt"))
    # Also include top-level markdown documentation if available
    workspace_docs = [p for p in Path(".").glob("*.md") if p.is_file() and not p.name.startswith(".")]
    all_files = files + workspace_docs
    matches: List[str] = []
    for f in all_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            if query in text.lower():
                idx = text.lower().find(query)
                start = max(0, idx - 80)
                end = min(len(text), idx + 200)
                snippet = text[start:end].replace("\n", " ").strip()
                matches.append(f"- **{f.name}**: `...{snippet}...`")
        except Exception:
            continue
    if not matches:
        return f"No documents found matching '{query}' in the local knowledge vault."
    return f"### Knowledge Vault Matches for '{query}':\n" + "\n".join(matches[:8])


def read_document(file_name: str) -> str:
    """Read the contents of a note or document from the knowledge vault or workspace."""
    clean_name = os.path.basename((file_name or "").strip())
    if not clean_name:
        return "Please provide a file name to read."
    kb_dir = _get_kb_dir()
    target = kb_dir / clean_name
    if not target.exists():
        target = Path(".") / clean_name
    if not target.exists() or not target.is_file():
        return f"Document '{clean_name}' not found in knowledge vault."
    try:
        content = target.read_text(encoding="utf-8", errors="ignore")
        preview = content[:3000]
        if len(content) > 3000:
            preview += f"\n\n_[Truncated: showing first 3000 of {len(content)} characters]_"
        return f"### Document: {target.name}\n\n{preview}"
    except Exception as e:
        return f"Error reading document '{clean_name}': {e}"


def list_knowledge_documents() -> str:
    """List all documents, notes, and records currently stored in the local knowledge vault."""
    kb_dir = _get_kb_dir()
    docs = sorted(list(kb_dir.glob("*")), key=lambda p: p.stat().st_mtime, reverse=True)
    if not docs:
        return "The knowledge vault is currently empty. Use `save_note` to store notes or ingest documents."
    lines = ["### Local Knowledge Vault Catalog:"]
    for d in docs[:20]:
        sz = d.stat().st_size
        lines.append(f"- **{d.name}** ({sz} bytes)")
    return "\n".join(lines)


def save_note(title: str, content: str) -> str:
    """Save or append a note to the local offline knowledge vault."""
    safe_title = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', (title or "").strip()) or "note"
    if not safe_title.endswith(".md") and not safe_title.endswith(".txt"):
        safe_title += ".md"
    kb_dir = _get_kb_dir()
    target = kb_dir / safe_title
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        header = f"\n\n## Note: {safe_title} ({timestamp})\n" if target.exists() else f"# {safe_title}\n_Created: {timestamp}_\n\n"
        mode = "a" if target.exists() else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(header + (content or "") + "\n")
        return f"Successfully saved note to knowledge vault: `{safe_title}`"
    except Exception as e:
        return f"Error saving note: {e}"


def summarize_document(file_name: str) -> str:
    """Generate a structural summary of a document in the vault or workspace."""
    clean_name = os.path.basename((file_name or "").strip())
    if not clean_name:
        return "Please provide a document name to summarize."
    kb_dir = _get_kb_dir()
    target = kb_dir / clean_name
    if not target.exists():
        target = Path(".") / clean_name
    if not target.exists():
        return f"Document '{clean_name}' not found."
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
        lines = [l for l in text.splitlines() if l.strip()]
        headings = [l.strip() for l in lines if l.startswith("#")][:8]
        words = len(text.split())
        chars = len(text)
        summary = [
            f"### Summary for `{target.name}`:",
            f"- **Size**: {chars} chars, {words} words, {len(lines)} lines",
        ]
        if headings:
            summary.append("- **Key Headings**:")
            for h in headings:
                summary.append(f"  {h}")
        else:
            first_para = "\n".join(lines[:4])
            summary.append(f"- **Excerpt**: {first_para[:300]}...")
        return "\n".join(summary)
    except Exception as e:
        return f"Error summarizing '{clean_name}': {e}"


def get_vault_stats() -> str:
    """Get statistics and health metrics for the local offline knowledge vault."""
    kb_dir = _get_kb_dir()
    docs = list(kb_dir.glob("*"))
    total_size = sum(f.stat().st_size for f in docs if f.is_file())
    return (
        "### 📚 Alexandria Knowledge Vault Status:\n"
        f"- **Status**: Online & sovereign (local-first storage)\n"
        f"- **Documents in Vault**: {len(docs)}\n"
        f"- **Storage Consumed**: {total_size / 1024:.1f} KB\n"
        f"- **Directory**: `{kb_dir}`\n"
        "- **RAG Capability**: Ready (semantic & keyword search available)"
    )


# ════════════════════════════════════════════════════════════════
# Skill definition
# ════════════════════════════════════════════════════════════════

class AlexandriaSkill(SkillBase):
    name = "Alexandria (Document & Knowledge Ingestion / RAG)"
    description = (
        "Keeper of the Library. Manages personal data sovereignty, local "
        "document search, note taking, and offline RAG knowledge."
    )

    system_prompt = (
        "You are Alexandria, the Library Keeper and steward of Homee's local network knowledge "
        "and personal data sovereignty. You maintain and expand the offline-first knowledge vault, "
        "helping users organize, search, ingest, and retrieve documents, notes, and research. "
        "You have access to tools to search the knowledge vault, read documents, list documents, "
        "summarize texts, and save new knowledge. "
        "Always use your available tools and associated MCP tools to fetch or persist local data before answering. "
        "Respond thoughtfully, helpfully, and in character as Alexandria, formatting your replies in "
        "Markdown with headings, bullet points, and source citations."
    )

    skills = [
        "document_ingest",
        "semantic_search",
        "metadata_extraction",
        "entity_tagging",
        "summarization",
        "file_watcher",
        "vault_stats",
    ]

    tools = [
        search_knowledge_vault,
        read_document,
        list_knowledge_documents,
        save_note,
        summarize_document,
        get_vault_stats,
    ]

    def execute(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        knowledge_path: Optional[str] = None,
        mcp_executor: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
        mcp_tools: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[str]] = None,
    ) -> SkillResult:
        res = super().execute(
            user_message,
            conversation_history=conversation_history,
            knowledge_path=knowledge_path,
            mcp_executor=mcp_executor,
            mcp_tools=mcp_tools,
            images=images,
        )
        if not res.error:
            return res

        # Graceful deterministic fallback if LLM is unreachable or errors
        task_lower = (user_message or "").lower()
        if any(k in task_lower for k in ["search", "find", "query", "retrieve"]):
            content = search_knowledge_vault(user_message)
        elif any(k in task_lower for k in ["list", "files", "catalog", "browse"]):
            content = list_knowledge_documents()
        elif any(k in task_lower for k in ["summarize", "summary"]):
            content = summarize_document(user_message)
        elif any(k in task_lower for k in ["save", "note", "ingest"]):
            content = save_note("quick_note", user_message)
        else:
            stats = get_vault_stats()
            content = (
                f"## 🏛️ Alexandria — Library Keeper\n\n"
                f"{stats}\n\n"
                "I am here to steward your local knowledge vault and personal data sovereignty.\n\n"
                "You can ask me to:\n"
                "- **Search vault**: `search <topic>`\n"
                "- **List documents**: `list documents`\n"
                "- **Read / Summarize**: `summarize <document>` or `read <document>`\n"
                "- **Save note**: `save note <title>: <content>`\n\n"
                f"_(Offline fallback mode active: {res.error})_"
            )
        return SkillResult(content=content, knowledge_updated=False)


AGENT = AlexandriaSkill()

Alexandria = AlexandriaSkill
LibrarianSkill = AlexandriaSkill
KnowledgeSkill = AlexandriaSkill
RAGSkill = AlexandriaSkill


if __name__ == "__main__":
    skill = AlexandriaSkill()
    print("Alexandria Library Skill Online. Type 'exit' to quit.")
    messages = [{"role": "system", "content": skill.system_prompt}]
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ("exit", "quit"):
                break
            result = skill.execute(user_input, conversation_history=messages)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": result.content})
            print(f"\nAgent: {result.content}")
        except KeyboardInterrupt:
            break
