"""Unit tests for the Route2Study research baselines."""

import unittest

from research.orienteering import (
    OrienteeringInstance,
    evaluate_route,
    solve_exact_dynamic_programming,
    solve_greedy,
    solve_nearest,
)


class OrienteeringSolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = OrienteeringInstance(
            travel_minutes=(
                (0.0, 10.0, 15.0, 20.0),
                (10.0, 0.0, 8.0, 10.0),
                (15.0, 8.0, 0.0, 15.0),
                (20.0, 10.0, 15.0, 0.0),
            ),
            prizes=(5.0, 9.0),
            service_minutes=(10.0, 10.0),
            time_budget=45.0,
            name="two_candidate_test",
        )

    def test_route_evaluation(self) -> None:
        solution = evaluate_route(self.instance, (0, 2, 3), "manual")
        self.assertTrue(solution.feasible)
        self.assertEqual(solution.reward, 9.0)
        self.assertEqual(solution.total_minutes, 40.0)

    def test_exact_solver_finds_best_candidate(self) -> None:
        solution = solve_exact_dynamic_programming(self.instance)
        self.assertTrue(solution.feasible)
        self.assertEqual(solution.reward, 9.0)
        self.assertEqual(solution.route, (0, 2, 3))

    def test_heuristics_return_feasible_routes(self) -> None:
        for solver in (solve_nearest, solve_greedy):
            with self.subTest(solver=solver.__name__):
                self.assertTrue(solver(self.instance).feasible)


if __name__ == "__main__":
    unittest.main()
