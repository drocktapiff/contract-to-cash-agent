"""Conservative API subset; full business validation stays in AnalysisTools.

Reference: https://developers.openai.com/api/docs/guides/structured-outputs
Unknown keywords fail closed instead of silently discarding new constraints.
"""

from copy import deepcopy

KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "description",
}


def validate_api_schema(node):
    if not isinstance(node, dict) or set(node) - KEYWORDS:
        raise ValueError("Unsupported enterprise API schema keyword")
    if node.get("type") not in {
        "object",
        "array",
        "string",
        "number",
        "integer",
        "boolean",
        "null",
    }:
        raise ValueError("Unsupported enterprise API schema type")
    if node["type"] == "object":
        props = node.get("properties", {})
        if node.get("additionalProperties") is not False or set(node.get("required", [])) != set(
            props
        ):
            raise ValueError("Enterprise API objects must be strict and fully required")
        for child in props.values():
            validate_api_schema(child)
    if node["type"] == "array":
        validate_api_schema(node.get("items"))


def api_definitions(definitions):
    result = deepcopy(list(definitions.values()))

    def project(node):
        # Explicitly supported local-only constraint, never remove arbitrary keywords.
        node.pop("uniqueItems", None)
        for child in node.get("properties", {}).values():
            project(child)
        if "items" in node:
            project(node["items"])

    for tool in result:
        project(tool["parameters"])
        validate_api_schema(tool["parameters"])
    return result
