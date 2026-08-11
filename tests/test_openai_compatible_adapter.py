from agent_app.models.openai_compatible import OpenAICompatibleStructuredAdapter


def test_provider_schema_removes_unsupported_lookahead_but_keeps_other_constraints() -> None:
    schema = {
        "type": "object",
        "properties": {
            "amount": {
                "anyOf": [
                    {
                        "type": "string",
                        "pattern": r"^(?!^[-+.]*$)[+-]?0*\d*\.?\d*$",
                    },
                    {"type": "number", "minimum": 0},
                ]
            },
            "step_id": {
                "type": "string",
                "pattern": r"^[a-z][a-z0-9_]{0,31}$",
            },
        },
        "required": ["amount", "step_id"],
    }

    normalized = OpenAICompatibleStructuredAdapter._provider_schema(schema)

    amount_string = normalized["properties"]["amount"]["anyOf"][0]
    assert "pattern" not in amount_string
    assert normalized["properties"]["step_id"]["pattern"] == r"^[a-z][a-z0-9_]{0,31}$"
    assert normalized["required"] == ["amount", "step_id"]
