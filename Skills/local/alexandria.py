from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from Skills.app import SkillBase, SkillResult


class AlexandriaSkill(SkillBase):
    name = "Alexandria (Document & Knowledge Ingestion / RAG)"
    description = "Keeper of the Library. Manages personal data sovereignty."

    system_prompt = "You are Alexandria, keeper of the Library."

    skills = ["document_ingest", "semantic_search", "metadata_extraction",
              "entity_tagging", "summarization", "file_watcher", "ocr_processing"]

    tools = []

    def execute(self, user_message, conversation_history=None, knowledge_path=None,
                mcp_executor=None, mcp_tools=None, images=None):
        task_lower = (user_message or "").lower()
        if any(k in task_lower for k in ["ingest", "index", "parse"]):
            content = self._ingest(user_message, mcp_executor)
        elif any(k in task_lower for k in ["search", "find", "query", "retrieve"]):
            content = self._search(user_message, mcp_executor)
        elif any(k in task_lower for k in ["summarize", "summary"]):
            content = self._summarize(user_message, mcp_executor)
        elif any(k in task_lower for k in ["metadata", "tag", "entities"]):
            content = self._metadata(user_message, mcp_executor)
        elif any(k in task_lower for k in ["watch", "folder", "drop", "monitor"]):
            content = self._watch(user_message, mcp_executor)
        else:
            content = ("## Alexandria - Library Keeper\n\n"
                       "Try: ingest/search/summarize/metadata/watch <target>")
        return SkillResult(content=content, knowledge_updated=False)
    def _ingest(self, user_message, mcp_executor):
        lines = ["## Ingestion", ""]
        if mcp_executor:
            try:
                res = mcp_executor("knowledge_ingest", {"message": user_message})
                if isinstance(res, dict) and "error" in res:
                    lines.append(f"Knowledge MCP unavailable: {res['error']}")
                    lines.append("Install/connect a knowledge MCP from Settings -> MCPs -> Marketplace.")
                else:
                    out = res.get("result", res) if isinstance(res, dict) else res
                    lines.append(str(out))
            except Exception as e:
                lines.append(f"MCP ingest unavailable: {e}")
        else:
            lines.append("MCP executor not available - running in dry mode.")
            lines.append("Provide a file path or folder to ingest; supported: PDF, Markdown, plain text, images (OCR).")
        lines.append("")
        lines.append("_Ingested content is embedded locally; no text leaves the machine._")
        return "\n".join(lines)

    def _search(self, user_message, mcp_executor):
        lines = ["## Semantic Search", ""]
        if mcp_executor:
            try:
                res = mcp_executor("knowledge_search", {"query": user_message})
                if isinstance(res, dict) and "error" in res:
                    lines.append(f"Knowledge MCP unavailable: {res['error']}")
                    lines.append("Install/connect a knowledge MCP from Settings -> MCPs -> Marketplace.")
                else:
                    out = res.get("result", res) if isinstance(res, dict) else res
                    lines.append(str(out))
            except Exception as e:
                lines.append(f"MCP search unavailable: {e}")
        else:
            lines.append("MCP executor not available - running in dry mode.")
            lines.append("Provide a query to search the local document store.")
        lines.append("")
        lines.append("_Results cite source path and chunk; embeddings computed locally._")
        return "\n".join(lines)

    def _summarize(self, user_message, mcp_executor):
        lines = ["## Summary", ""]
        if mcp_executor:
            try:
                res = mcp_executor("knowledge_summarize", {"target": user_message})
                if isinstance(res, dict) and "error" in res:
                    lines.append(f"Knowledge MCP unavailable: {res['error']}")
                    lines.append("Install/connect a knowledge MCP from Settings -> MCPs -> Marketplace.")
                else:
                    out = res.get("result", res) if isinstance(res, dict) else res
                    lines.append(str(out))
            except Exception as e:
                lines.append(f"MCP summarize unavailable: {e}")
        else:
            lines.append("MCP executor not available - running in dry mode.")
            lines.append("Provide a document path to summarize.")
        return "\n".join(lines)

    def _metadata(self, user_message, mcp_executor):
        lines = ["## Metadata & Entities", ""]
        if mcp_executor:
            try:
                res = mcp_executor("knowledge_metadata", {"target": user_message})
                if isinstance(res, dict) and "error" in res:
                    lines.append(f"Knowledge MCP unavailable: {res['error']}")
                    lines.append("Install/connect a knowledge MCP from Settings -> MCPs -> Marketplace.")
                else:
                    out = res.get("result", res) if isinstance(res, dict) else res
                    lines.append(str(out))
            except Exception as e:
                lines.append(f"MCP metadata unavailable: {e}")
        else:
            lines.append("MCP executor not available - running in dry mode.")
            lines.append("Provide a document path to extract metadata and entities.")
        return "\n".join(lines)

    def _watch(self, user_message, mcp_executor):
        lines = ["## Folder Watcher", ""]
        if mcp_executor:
            try:
                res = mcp_executor("knowledge_watch", {"target": user_message})
                if isinstance(res, dict) and "error" in res:
                    lines.append(f"Knowledge MCP unavailable: {res['error']}")
                    lines.append("Install/connect a knowledge MCP from Settings -> MCPs -> Marketplace.")
                else:
                    out = res.get("result", res) if isinstance(res, dict) else res
                    lines.append(str(out))
            except Exception as e:
                lines.append(f"MCP watch unavailable: {e}")
        else:
            lines.append("MCP executor not available - running in dry mode.")
            lines.append("Provide a folder path to monitor for dropped files.")
        lines.append("")
        lines.append("_New files are parsed, embedded, and indexed automatically._")
        return "\n".join(lines)


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

