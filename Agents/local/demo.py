"""Example Agent — a local system assistant with disk and shell tools.

This is the reference implementation of an Agent personality. Bots created in
the UI can be assigned this (or any registered) Agent to embody its skill set.
Provides server health report and trending information.
"""

from __future__ import annotations

import shutil

from Agents.app import AgentBase, get_disk_space, run_shell


class DemoAgent(AgentBase):
    name = "Demo (System Agent)"
    description = "A helpful local system assistant that can check disk space and run shell commands."
    system_prompt = (
        "You are a helpful local system assistant. You have access to tools for "
        "checking disk space and running shell commands. Use them when the user "
        "asks about the system. Be concise and safe. I can also provide server "
        "health reports and trending information when requested."
    )
    model = "qwen2.5"
    tools = [get_disk_space, run_shell]


def get_server_health() -> dict:
    """Get current server health metrics including disk space and trending."""
    import psutil
    
    # Disk space
    total, used, free = shutil.disk_usage("/")
    disk_free_gb = free // (2 ** 30)
    disk_total_gb = total // (2 ** 30)
    disk_usage_percent = (used / total) * 100 if total > 0 else 0
    
    # Memory
    mem = psutil.virtual_memory()
    memory_free_gb = mem.free // (2 ** 30)
    memory_total_gb = mem.total // (2 ** 30)
    memory_usage_percent = mem.percent
    
    # CPU
    cpu_percent = psutil.cpu_percent(interval=1)
    
    # Trending (simulated - in a real app this would come from metrics collection)
    trending = {
        "cpu_trend": "stable",  # rising, falling, stable
        "memory_trend": "stable",
        "disk_trend": "stable",
    }
    
    return {
        "disk": {
            "total_gb": disk_total_gb,
            "free_gb": disk_free_gb,
            "usage_percent": round(disk_usage_percent, 1),
        },
        "memory": {
            "total_gb": memory_total_gb,
            "free_gb": memory_free_gb,
            "usage_percent": memory_usage_percent,
        },
        "cpu": {
            "percent": cpu_percent,
            "trend": trending["cpu_trend"],
        },
    }


# Backwards-compatible CLI entry point (original demo behaviour)
if __name__ == "__main__":
    import ollama
    import shutil

    agent = DemoAgent()
    print("🤖 Local Agent Online. Type 'exit' to quit.")
    messages: list = [{"role": "system", "content": agent.system_prompt}]

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ("exit", "quit"):
                break
            # Check if user wants health report
            if "health" in user_input.lower():
                health = get_server_health()
                print(f"\nServer Health Report:")
                print(f"  Disk: {health['disk']['free_gb']}GB free of {health['disk']['total_gb']}GB ({health['disk']['usage_percent']}% used)")
                print(f"  Memory: {health['memory']['free_gb']}GB free of {health['memory']['total_gb']}GB ({health['memory']['usage_percent']}% used)")
                print(f"  CPU: {health['cpu']['percent']}% ({health['cpu']['trend']})")
            elif "trend" in user_input.lower():
                health = get_server_health()
                print(f"\nServer Trending:")
                print(f"  CPU: {health['cpu']['percent']}% ({health['cpu']['trend']})")
                print(f"  Memory: {health['memory']['usage_percent']}% trending {health['memory']['trend']}")
                print(f"  Disk: {health['disk']['usage_percent']}% trending {health['disk']['trend']}")
            else:
                result = agent.execute(user_input, conversation_history=messages)
                messages.append({"role": "user", "content": user_input})
                messages.append({"role": "assistant", "content": result.content})
                print(f"\nAgent: {result.content}")
        except KeyboardInterrupt:
            break