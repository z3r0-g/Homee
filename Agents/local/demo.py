"""Example Agent — a local system assistant with disk and shell tools.

This is the reference implementation of an Agent personality. Bots created in
the UI can be assigned this (or any registered) Agent to embody its skill set.
"""

from __future__ import annotations

from Agents.app import AgentBase, get_disk_space, run_shell


class DemoAgent(AgentBase):
    name = "Demo System Agent"
    description = "A helpful local system assistant that can check disk space and run shell commands."
    system_prompt = (
        "You are a helpful local system assistant. You have access to tools for "
        "checking disk space and running shell commands. Use them when the user "
        "asks about the system. Be concise and safe."
    )
    model = "qwen2.5"
    tools = [get_disk_space, run_shell]


# Backwards-compatible CLI entry point (original demo behaviour)
if __name__ == "__main__":
    import ollama

    agent = DemoAgent()
    print("🤖 Local Agent Online. Type 'exit' to quit.")
    messages: list = [{"role": "system", "content": agent.system_prompt}]

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ("exit", "quit"):
                break
            result = agent.execute(user_input, conversation_history=messages)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": result.content})
            print(f"\nAgent: {result.content}")
        except KeyboardInterrupt:
            break