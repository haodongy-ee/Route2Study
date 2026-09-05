"""Tests for converting Penn location data into solver instances."""

import unittest

import pandas as pd

from research.penn_network import create_penn_instance, preference_prize


class PennInstanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.locations = pd.DataFrame(
            [
                {
                    "name": "Residence",
                    "can_be_study": 0,
                    "quiet_score": 0,
                    "collaborative_score": 0,
                    "coffee_score": 0,
                    "outlet_score": 0,
                    "default_service_minutes": 0,
                },
                {
                    "name": "Library",
                    "can_be_study": 1,
                    "quiet_score": 5,
                    "collaborative_score": 2,
                    "coffee_score": 3,
                    "outlet_score": 4,
                    "default_service_minutes": 20,
                },
                {
                    "name": "Classroom",
                    "can_be_study": 0,
                    "quiet_score": 0,
                    "collaborative_score": 0,
                    "coffee_score": 0,
                    "outlet_score": 0,
                    "default_service_minutes": 0,
                },
            ]
        )
        self.matrix = pd.DataFrame(
            (
                (0.0, 10.0, 20.0),
                (10.0, 0.0, 8.0),
                (20.0, 8.0, 0.0),
            ),
            index=("Residence", "Library", "Classroom"),
            columns=("Residence", "Library", "Classroom"),
        )

    def test_quiet_prize(self) -> None:
        prize = preference_prize(self.locations.iloc[1], "Quiet")
        self.assertEqual(prize, 10.8)

    def test_instance_uses_real_matrix_order(self) -> None:
        instance, node_names = create_penn_instance(
            self.locations,
            self.matrix,
            start_name="Residence",
            destination_name="Classroom",
            preference="Quiet",
            time_budget=60,
        )
        self.assertEqual(instance.travel_minutes[0][1], 10.0)
        self.assertEqual(instance.travel_minutes[1][2], 8.0)
        self.assertEqual(instance.service_minutes, (20.0,))
        self.assertEqual(node_names, {0: "Residence", 1: "Library", 2: "Classroom"})


if __name__ == "__main__":
    unittest.main()
