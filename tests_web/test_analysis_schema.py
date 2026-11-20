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
            validation_status="more_validation_needed",
        )
        with self.assertRaises(ToolError):
            tools.execute("save_analysis", args)
        self.assertIsNone(tools.result)
        self.assertEqual(tools.history, [])

    def test_every_advertised_persona_choice_can_be_saved(self):
        from unittest.mock import Mock
        from jsonschema import Draft202012Validator

        inputs = dict(
            operational={"period": "2026-04"},
            revision="revision",
            overview_reference="overview",
            scenario_reference="scenario",
            management_reference="management",
        )
        for kind, field, excluded in [
            ("management", "validation_status", "stance"),
            ("executive", "stance", "validation_status"),
        ]:
            tools = AnalysisTools(inputs, kind, Mock())
            tools.seen.update({"overview", "scenario", "management"})
            definition = next(d for d in tools.api_definitions() if d["name"] == "save_analysis")
            parameters = definition["parameters"]
            validate_api_schema(parameters)
            self.assertNotIn(excluded, parameters["properties"])
            self.assertIn(field, parameters["required"])
            self.assertIn(field, tools.instructions)
            self.assertIn("Only a human", tools.instructions)
            for choice in parameters["properties"][field]["enum"]:
                with self.subTest(kind=kind, choice=choice):
                    args = dict(
                        observations=[dict(text="Observed scope", citations=["overview"])],
                        hypotheses=[],
                        recommendations=[dict(text="Validate scope", citations=["overview"])],
                        limitations=["Prototype evidence only"],
                        **{field: choice}
                    )
                    Draft202012Validator(parameters).validate(args)
                    self.assertTrue(tools.execute("save_analysis", args)["saved"])
                    self.assertEqual(tools.result[field], choice)
                    forbidden = copy.deepcopy(args)
                    forbidden[excluded] = "more_validation_needed"
                    with self.assertRaises(ToolError):
                        tools.execute("save_analysis", forbidden)
            invalid = copy.deepcopy(args)
            invalid[field] = "pilot_supported" if kind == "management" else "not_applicable"
            with self.assertRaises(ToolError):
                tools.execute("save_analysis", invalid)

    def test_unknown_persona_cannot_obtain_executive_tools(self):
        with self.assertRaises(ValueError):
            AnalysisTools({"operational": {"period": "2026-04"}, "revision": "r"}, "unknown", None)
