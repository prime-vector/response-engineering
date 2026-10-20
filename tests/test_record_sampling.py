"""Offline check of the sampling rule a record states.

The rule mirrors the provider, which drops temperature whenever an effort is
named; these tests hold judgement.py to that rule and do not observe the
provider itself.
"""
import os
import sys
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "evals"))
import judgement  # noqa: E402


def config_of(path):
    with open(os.path.join(ROOT, path)) as handle:
        return yaml.safe_load(handle)["intelligence"]["config"]


class AgentSampling(unittest.TestCase):
    def test_with_an_effort_the_record_names_no_temperature(self):
        # The committed variant spec, so a spec that stops naming an effort
        # or starts naming one breaks this loudly rather than quietly.
        config = config_of("evals/specs/precedent-analyst-sonnet55-medium.yaml")
        self.assertIsNotNone(config.get("temperature"))
        sampling = judgement.agent_sampling(config)
        self.assertEqual(sampling, {"temperature": None,
                                    "effort": config["reasoning_effort"]})
        self.assertEqual(judgement.sampling_label(sampling),
                         f"effort {config['reasoning_effort']}")

    def test_without_an_effort_the_record_names_the_temperature(self):
        config = config_of(".agents/precedent-analyst.yaml")
        self.assertNotIn("reasoning_effort", config)
        sampling = judgement.agent_sampling(config)
        self.assertEqual(sampling, {"temperature": config["temperature"],
                                    "effort": None})
        self.assertEqual(judgement.sampling_label(sampling),
                         f"temperature {config['temperature']}")

    def test_a_new_record_states_the_effort_not_the_spec_temperature(self):
        path = "evals/specs/precedent-analyst-sonnet55-medium.yaml"
        with open(os.path.join(ROOT, path)) as handle:
            spec = yaml.safe_load(handle)
        agent = judgement.agent_record({"spec": path, "task": "recall"}, spec)
        self.assertIsNone(agent["temperature"])
        self.assertEqual(agent["effort"],
                         spec["intelligence"]["config"]["reasoning_effort"])

    def test_a_record_made_before_effort_was_recorded_reads_as_before(self):
        self.assertEqual(judgement.sampling_label({"temperature": 0.2}),
                         "temperature 0.2")


if __name__ == "__main__":
    unittest.main()
