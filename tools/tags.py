from tools.schema import ToolSpec


def filter_tools_by_tags(tools: list[ToolSpec], tags: list[str] | None) -> list[ToolSpec]:
    if not tags:
        return tools

    normalized = {tag.lower().strip() for tag in tags if tag and tag.strip()}
    if not normalized:
        return tools

    filtered: list[ToolSpec] = []
    for tool in tools:
        tool_tags = {tag.lower() for tag in tool.tags}
        if normalized.issubset(tool_tags):
            filtered.append(tool)
    return filtered
