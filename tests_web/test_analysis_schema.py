"""Offline transport-schema and local integrity regressions."""

import copy
import unittest
from contract_to_cash.web.analysis_tools import ANALYSIS_TOOLS, AnalysisTools
from contract_to_cash.web.analysis_schema import api_definitions, validate_api_schema
from contract_to_cash.agent.tools import ToolError


class AnalysisSchemaTests(unittest.TestCase):
    def test_nested_future_unsupported_keyword_is_rejected(self):
        definitions = {t["name"]: copy.deepcopy(t) for t in ANALYSIS_TOOLS}
        definitions["save_analysis"]["parameters"]["properties"]["observations"]["items"][
            "not"
        ] = {}
        with self.assertRaises(ValueError):
            api_definitions(definitions)

    def test_transport_projection_does_not_mutate_local_uniqueness(self):
        definitions = {t["name"]: copy.deepcopy(t) for t in ANALYSIS_TOOLS}
        original = copy.deepcopy(definitions)
        for tool in api_definitions(definitions):
            validate_api_schema(tool["parameters"])
        self.assertEqual(definitions, original)
        tools = AnalysisTools(
            {"operational": {"period": "2026-04"}, "revision": "r"}, "management", None
        )
        tools.seen.add("read-ref")
        args = dict(
            observations=[dict(text="Observed", citations=["read-ref", "read-ref"])],
            hypotheses=[],
            recommendations=[dict(text="Review", citations=["read-ref"])],
            limitations=["Limited"],
            stance="not_applicable",
        )
        with self.assertRaises(ToolError):
            tools.execute("save_analysis", args)
        self.assertIsNone(tools.result)
        self.assertEqual(tools.history, [])
