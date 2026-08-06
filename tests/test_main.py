"""Mini NPU 시뮬레이터의 표준 라이브러리 기반 회귀 테스트."""

import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import main


DATA_PATH = PROJECT_ROOT / "data.json"


class GridAndMacTests(unittest.TestCase):

    def test_validate_grid_normalizes_valid_grid(self):
        ok, grid, size, error = main.validate_grid(
            [[0, 1, 0], [1, 1, 1], [0, 1, 0]],
            expected_n=3,
        )

        self.assertTrue(ok)
        self.assertEqual(size, 3)
        self.assertIsNone(error)
        self.assertEqual(grid[1][1], 1.0)

    def test_validate_grid_rejects_invalid_values(self):
        invalid_cases = [
            [],
            [[1, 0], [1]],
            [[1, 0, 1], [1, 0, 1]],
            [[True, 0], [0, 1]],
            [[math.nan, 0], [0, 1]],
            [[math.inf, 0], [0, 1]],
            [[1, "x"], [0, 1]],
        ]

        for grid in invalid_cases:
            with self.subTest(grid=grid):
                ok, _normalized, _size, error = main.validate_grid(grid)
                self.assertFalse(ok)
                self.assertIsNotNone(error)

        ok, _normalized, _size, error = main.validate_grid(
            [[1, 0], [0, 1]],
            expected_n=3,
        )
        self.assertFalse(ok)
        self.assertIn("기대 크기", error)

    def test_mac_reference_examples_and_mismatch(self):
        cross = [
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 1.0],
            [0.0, 1.0, 0.0],
        ]
        x_shape = [
            [1.0, 0.0, 1.0],
            [0.0, 1.0, 0.0],
            [1.0, 0.0, 1.0],
        ]

        self.assertEqual(main.mac(cross, cross), 5.0)
        self.assertEqual(main.mac(cross, x_shape), 1.0)

        with self.assertRaises(ValueError):
            main.mac([[1.0]], [[1.0, 0.0], [0.0, 1.0]])

    def test_label_normalization_and_duplicate_filter_labels(self):
        self.assertEqual(main.normalize_label("+"), "Cross")
        self.assertEqual(main.normalize_label(" cross "), "Cross")
        self.assertEqual(main.normalize_label("X"), "X")
        self.assertIsNone(main.normalize_label("triangle"))
        self.assertIsNone(main.normalize_label(None))

        grid = [[1.0, 0.0], [0.0, 1.0]]
        ok, _filters, error = main.validate_filter_set(
            {"cross": grid, "Cross": grid, "x": grid},
            expected_n=2,
        )
        self.assertFalse(ok)
        self.assertIn("중복", error)

    def test_epsilon_policy_uses_strict_less_than(self):
        self.assertEqual(
            main.judge_scores(0.0, 0.999, "A", "B", epsilon=1.0),
            "UNDECIDED",
        )
        self.assertEqual(
            main.judge_scores(0.0, 1.0, "A", "B", epsilon=1.0),
            "B",
        )

    def test_performance_repeat_and_flatten_guards(self):
        pattern = main.generate_cross_pattern(3)

        with self.assertRaises(ValueError):
            main.measure_mac_time(pattern, pattern, repeat=0)
        with self.assertRaises(ValueError):
            main.measure_mac_flat_time(main.flatten(pattern), main.flatten(pattern), 3, repeat=False)
        with self.assertRaises(ValueError):
            main.mac_flat([1.0], [1.0], 0)
        with self.assertRaises(ValueError):
            main.mac_flat([1.0], [1.0], 2)

    def test_flattened_mac_matches_two_dimensional_mac(self):
        for size in main.REQUIRED_SIZES:
            with self.subTest(size=size):
                pattern = main.generate_cross_pattern(size)
                filter_grid = main.generate_x_pattern(size)
                flat_score = main.mac_flat(
                    main.flatten(pattern),
                    main.flatten(filter_grid),
                    size,
                )
                self.assertEqual(flat_score, main.mac(pattern, filter_grid))


class ModeOneTests(unittest.TestCase):

    def test_read_grid_retries_the_entire_grid_after_bad_row(self):
        inputs = [
            "0 1",
            "0 1 0",
            "1 1 1",
            "0 1 0",
        ]
        output = io.StringIO()

        with patch("builtins.input", side_effect=inputs):
            with contextlib.redirect_stdout(output):
                grid = main.read_grid_3x3("테스트 Grid")

        self.assertEqual(grid[1][1], 1.0)
        self.assertIn("다시 입력해주세요.", output.getvalue())

    def test_read_grid_retries_after_non_numeric_token(self):
        inputs = [
            "0 text 0",
            "0 1 0",
            "1 1 1",
            "0 1 0",
        ]
        output = io.StringIO()

        with patch("builtins.input", side_effect=inputs):
            with contextlib.redirect_stdout(output):
                grid = main.read_grid_3x3("테스트 Grid")

        self.assertEqual(grid[1][1], 1.0)
        self.assertIn("숫자로 변환할 수 없는 값", output.getvalue())

    def test_mode_one_reference_example(self):
        inputs = [
            "0 1 0", "1 1 1", "0 1 0",
            "1 0 1", "0 1 0", "1 0 1",
            "1 0 1", "0 1 0", "1 0 1",
        ]
        output = io.StringIO()

        with patch("builtins.input", side_effect=inputs):
            with contextlib.redirect_stdout(output):
                main.run_mode_1()

        text = output.getvalue()
        self.assertIn("A 점수: 1.0", text)
        self.assertIn("B 점수: 5.0", text)
        self.assertIn("판정: B", text)


class MenuTests(unittest.TestCase):

    def test_invalid_menu_choice_reprompts_without_traceback(self):
        output = io.StringIO()

        with patch("builtins.input", side_effect=["invalid", "0"]):
            with contextlib.redirect_stdout(output):
                main.main()

        text = output.getvalue()
        self.assertIn("잘못된 선택입니다.", text)
        self.assertGreaterEqual(text.count("[모드 선택]"), 2)


class JsonModeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ok, data, error = main.load_data_json(str(DATA_PATH))
        if not ok:
            raise RuntimeError(error)
        cls.data = data
        cls.filters, cls.messages = main.build_filters_by_size(data["filters"])

    def test_bundled_json_results_and_summary_are_consistent(self):
        results = [
            main.analyze_case(case_id, entry, self.filters)
            for case_id, entry in self.data["patterns"].items()
        ]

        self.assertEqual(len(results), 7)
        self.assertEqual(sum(r["status"] == "PASS" for r in results), 5)
        self.assertEqual(sum(r["status"] == "FAIL" for r in results), 2)
        self.assertEqual(
            {r["reason_code"] for r in results if r["status"] == "FAIL"},
            {"UNDECIDED", "SIZE_MISMATCH"},
        )

    def test_case_schema_failures_are_controlled(self):
        invalid_key = main.analyze_case("broken_key", {}, self.filters)
        self.assertEqual(invalid_key["reason_code"], "INVALID_CASE_KEY")

        missing_filter = main.analyze_case(
            "size_4_1",
            {"input": [[0.0] * 4 for _ in range(4)], "expected": "x"},
            self.filters,
        )
        self.assertEqual(missing_filter["reason_code"], "FILTER_NOT_FOUND")

        bad_expected = main.analyze_case(
            "size_5_99",
            {"input": [[0.0] * 5 for _ in range(5)], "expected": "triangle"},
            self.filters,
        )
        self.assertEqual(bad_expected["reason_code"], "EXPECTED_LABEL_INVALID")

    def test_json_load_errors_and_mode_two_do_not_raise(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            malformed_path = temp_path / "malformed.json"
            malformed_path.write_text("{not-json", encoding="utf-8")

            ok, _data, error = main.load_data_json(str(malformed_path))
            self.assertFalse(ok)
            self.assertIn("JSON 파싱 오류", error)

            ok, _data, error = main.load_data_json(str(temp_path / "missing.json"))
            self.assertFalse(ok)
            self.assertIn("찾을 수 없습니다", error)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main.run_mode_2(str(temp_path / "missing.json"))
            self.assertIn("메뉴로 돌아갑니다.", output.getvalue())

    def test_mode_two_prints_expected_sections(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            main.run_mode_2(str(DATA_PATH))

        text = output.getvalue()
        self.assertIn("size_13_1", text)
        self.assertIn("UNDECIDED", text)
        self.assertIn("총 테스트: 7개", text)
        self.assertIn("통과: 5개", text)
        self.assertIn("실패: 2개", text)
        self.assertIn("3×3", text)
        self.assertIn("5×5", text)
        self.assertIn("13×13", text)
        self.assertIn("25×25", text)


if __name__ == "__main__":
    unittest.main()
