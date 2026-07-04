META_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_tools",
            "description": (
                "Search the local tool registry (not the internet) for tools to use. "
                "Call before use_tool when you are not sure which registered tool fits. "
                "In query, describe the kind of tool you need — not the user's factual question. "
                "mode=rank (default): rank tools by query; optional tags filter; returns full schemas. "
                "mode=catalog: list all tools matching tags (name/description only; no query needed). "
                "Without tags in rank mode, response may include tag_hints for matching tag families."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["rank", "catalog"],
                        "default": "rank",
                        "description": (
                            "rank: relevance search with full tool schemas. "
                            "catalog: full inventory for the given tags."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Description of the tool/capability you are looking for in the registry "
                            "(what kind of tool, not the user's question). "
                            "Required for mode=rank. Optional for mode=catalog. "
                            "Good: \"web search on the internet\", \"Google Maps driving directions\", "
                            "\"Google Calendar list events\". "
                            "Bad: \"what happened to pilot X in Formula 1\" — put that in use_tool arguments later."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of tools to return in rank mode.",
                        "default": 5,
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Tag filter. Tool must have all listed tags. "
                            "Required for mode=catalog. "
                            "Example: [\"google\", \"calendar\"]."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_tool",
            "description": (
                "Execute a registered tool by name. Use search_tools first if needed "
                "to discover the correct tool name and parameter schema. "
                "Example: {\"tool_name\":\"exa.web_search\",\"arguments\":{\"query\":\"weather in Tashkent\"}}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Exact tool name from search_tools results.",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments object matching the tool JSON schema.",
                    },
                },
                "required": ["tool_name", "arguments"],
            },
        },
    },
]
