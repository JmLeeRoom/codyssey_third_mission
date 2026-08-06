#!/usr/bin/env python3
"""Mini NPU Simulator - MAC 연산 기반 패턴 판별 콘솔 애플리케이션."""

import sys

if sys.version_info < (3, 8):
    print("Python 3.8 이상이 필요합니다. 현재 버전: {}".format(sys.version))
    sys.exit(1)

import json
import math
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

Grid = List[List[float]]

EPSILON = 1e-9
PERF_REPEAT = 10
REQUIRED_SIZES = [3, 5, 13, 25]

CASE_KEY_RE = re.compile(r'^size_(\d+)_(.+)$')
FILTER_KEY_RE = re.compile(r'^size_(\d+)$')


# ---------------------------------------------------------------------------
# 1. Grid 검증
# ---------------------------------------------------------------------------

def validate_grid(grid, expected_n=None):
    # type: (Any, Optional[int]) -> Tuple[bool, Optional[Grid], int, Optional[str]]
    """정방 n×n 숫자 행렬인지 검증하고, 성공 시 float로 정규화한 행렬을 반환한다."""
    if not isinstance(grid, list) or len(grid) == 0:
        return False, None, 0, "행렬이 비어 있거나 리스트가 아닙니다."

    n = len(grid)
    normalized = []  # type: Grid
    for row in grid:
        if not isinstance(row, list) or len(row) != n:
            return False, None, 0, "정방 행렬(n×n)이 아닙니다. 행 길이가 행 수와 일치하지 않습니다."
        normalized_row = []
        for value in row:
            if isinstance(value, bool):
                return False, None, 0, "불리언(true/false) 값은 숫자로 취급하지 않습니다."
            if not isinstance(value, (int, float)):
                return False, None, 0, "숫자로 변환할 수 없는 원소가 포함되어 있습니다."
            f_value = float(value)
            if math.isnan(f_value) or math.isinf(f_value):
                return False, None, 0, "NaN 또는 무한대 값은 허용되지 않습니다."
            normalized_row.append(f_value)
        normalized.append(normalized_row)

    if expected_n is not None and n != expected_n:
        return False, None, 0, "기대 크기 {}와 실제 크기 {}가 일치하지 않습니다.".format(expected_n, n)

    return True, normalized, n, None


# ---------------------------------------------------------------------------
# 2. MAC 연산
# ---------------------------------------------------------------------------

def mac(pattern, filter_grid):
    # type: (Grid, Grid) -> float
    """패턴과 필터를 위치별로 곱하고 누적 합산한다(순수 반복문 구현)."""
    n = len(pattern)
    m = len(filter_grid)
    if n != m:
        raise ValueError("패턴과 필터의 크기가 다릅니다: {0}x{0} vs {1}x{1}".format(n, m))

    total = 0.0
    for r in range(n):
        pattern_row = pattern[r]
        filter_row = filter_grid[r]
        if len(pattern_row) != n or len(filter_row) != n:
            raise ValueError("행 길이가 정방 행렬 크기와 일치하지 않습니다.")
        for c in range(n):
            total += pattern_row[c] * filter_row[c]
    return total


# ---------------------------------------------------------------------------
# 3. 라벨 정규화
# ---------------------------------------------------------------------------

def normalize_label(raw):
    # type: (Any) -> Optional[str]
    """+/cross/Cross -> "Cross", x/X -> "X". 알 수 없는 값은 None."""
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower()
    if key in ("+", "cross"):
        return "Cross"
    if key == "x":
        return "X"
    return None


def validate_filter_set(filters_raw, expected_n=None):
    # type: (Any, Optional[int]) -> Tuple[bool, Optional[Dict[str, Grid]], Optional[str]]
    """{"cross": grid, "x": grid} 형태의 원본 필터 묶음을 표준 라벨(Cross/X)로 정규화한다."""
    if not isinstance(filters_raw, dict):
        return False, None, "필터 묶음이 객체(dict) 형식이 아닙니다."

    normalized = {}  # type: Dict[str, Grid]
    for raw_key, grid in filters_raw.items():
        label = normalize_label(raw_key)
        if label is None:
            continue  # 명세에 없는 부가 키는 무시한다.
        if label in normalized:
            return False, None, "필터 라벨이 중복됩니다: {} (원본 키 '{}')".format(label, raw_key)
        ok, normalized_grid, _n, err = validate_grid(grid, expected_n)
        if not ok:
            return False, None, "{} 필터 오류: {}".format(label, err)
        normalized[label] = normalized_grid

    if "Cross" not in normalized or "X" not in normalized:
        return False, None, "Cross 또는 X 필터가 없습니다."

    return True, normalized, None


# ---------------------------------------------------------------------------
# 4. 점수 비교와 판정
# ---------------------------------------------------------------------------

def judge_scores(score_left, score_right, label_left, label_right, epsilon=EPSILON):
    # type: (float, float, str, str, float) -> str
    """epsilon 기반 동점 처리 후 더 높은 점수의 라벨을 반환한다."""
    if abs(score_left - score_right) < epsilon:
        return "UNDECIDED"
    if score_left > score_right:
        return label_left
    return label_right


# ---------------------------------------------------------------------------
# 5. 성능 측정
# ---------------------------------------------------------------------------

def _validate_repeat_count(repeat):
    # type: (Any) -> None
    """성능 측정 반복 횟수가 양의 정수인지 확인한다."""
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat <= 0:
        raise ValueError("반복 횟수는 1 이상의 정수여야 합니다.")


def measure_mac_time(pattern, filter_grid, repeat=PERF_REPEAT):
    # type: (Grid, Grid, int) -> float
    """mac() 호출 구간만 반복 측정하여 평균 시간(ms)을 반환한다. I/O는 포함하지 않는다."""
    _validate_repeat_count(repeat)
    start = time.perf_counter()
    for _ in range(repeat):
        mac(pattern, filter_grid)
    elapsed = time.perf_counter() - start
    return (elapsed * 1000.0) / repeat


def print_performance_table(rows):
    # type: (List[Tuple[int, float, int]]) -> None
    print("{0:<10}{1:>18}{2:>14}".format("크기", "평균 시간(ms)", "연산 횟수"))
    print("-" * 42)
    for n, avg_ms, n_squared in rows:
        size_label = "{0}×{0}".format(n)
        print("{0:<10}{1:>18.4f}{2:>14}".format(size_label, avg_ms, n_squared))


# ---------------------------------------------------------------------------
# 6. (보너스) 패턴 생성기
# ---------------------------------------------------------------------------

def generate_cross_pattern(n):
    # type: (int) -> Grid
    """N×N Cross(십자가) 패턴을 생성한다. 짝수 N은 중심을 n//2 행/열로 정의한다."""
    mid = n // 2
    return [[1.0 if (r == mid or c == mid) else 0.0 for c in range(n)] for r in range(n)]


def generate_x_pattern(n):
    # type: (int) -> Grid
    """N×N X 패턴을 생성한다. 짝수 N은 두 대각선(주/부)을 기준으로 정의한다."""
    return [[1.0 if (r == c or r + c == n - 1) else 0.0 for c in range(n)] for r in range(n)]


def build_performance_rows(filters_by_size):
    # type: (Dict[int, Dict[str, Grid]]) -> List[Tuple[int, float, int]]
    """모드 2 성능 표: 3×3은 생성 표본, 나머지는 로드된 필터(없으면 생성 표본)로 측정한다."""
    rows = []
    for n in REQUIRED_SIZES:
        pattern = generate_cross_pattern(n)
        if n in filters_by_size and "Cross" in filters_by_size[n]:
            filter_grid = filters_by_size[n]["Cross"]
        else:
            filter_grid = generate_cross_pattern(n)
        avg_ms = measure_mac_time(pattern, filter_grid, PERF_REPEAT)
        rows.append((n, avg_ms, n * n))
    return rows


# ---------------------------------------------------------------------------
# 6-1. (보너스) 1차원 배열 메모리 접근 최적화
# ---------------------------------------------------------------------------

def flatten(grid):
    # type: (Grid) -> List[float]
    """n×n 2차원 리스트를 길이 n²의 1차원 리스트로 변환한다."""
    flat = []  # type: List[float]
    for row in grid:
        flat.extend(row)
    return flat


def mac_flat(pattern_flat, filter_flat, n):
    # type: (List[float], List[float], int) -> float
    """1차원 배열 기준 MAC 연산: flat[row * n + col] 접근 방식."""
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError("n은 1 이상의 정수여야 합니다.")
    if not isinstance(pattern_flat, list) or not isinstance(filter_flat, list):
        raise ValueError("1차원 MAC 입력은 리스트여야 합니다.")

    expected_length = n * n
    if len(pattern_flat) != expected_length or len(filter_flat) != expected_length:
        raise ValueError(
            "1차원 배열 길이가 n²와 일치하지 않습니다: 기대 {}, pattern {}, filter {}".format(
                expected_length,
                len(pattern_flat),
                len(filter_flat),
            )
        )

    total = 0.0
    for i in range(expected_length):
        total += pattern_flat[i] * filter_flat[i]
    return total


def measure_mac_flat_time(pattern_flat, filter_flat, n, repeat=PERF_REPEAT):
    # type: (List[float], List[float], int, int) -> float
    _validate_repeat_count(repeat)
    start = time.perf_counter()
    for _ in range(repeat):
        mac_flat(pattern_flat, filter_flat, n)
    elapsed = time.perf_counter() - start
    return (elapsed * 1000.0) / repeat


def build_flatten_comparison_rows(repeat=PERF_REPEAT):
    # type: (int) -> List[Tuple[int, float, float]]
    """동일 입력·동일 반복 횟수로 2차원 vs 1차원(flatten) MAC 성능을 비교한다."""
    rows = []
    for n in REQUIRED_SIZES:
        pattern = generate_cross_pattern(n)
        filter_grid = generate_cross_pattern(n)
        avg_2d = measure_mac_time(pattern, filter_grid, repeat)
        avg_flat = measure_mac_flat_time(flatten(pattern), flatten(filter_grid), n, repeat)
        rows.append((n, avg_2d, avg_flat))
    return rows


# ---------------------------------------------------------------------------
# 7. 모드 1 - 사용자 입력(3x3)
# ---------------------------------------------------------------------------

def read_grid_3x3(name):
    # type: (str) -> Grid
    """3줄(공백 구분) 입력을 받아 검증하고, 오류 시 행렬 전체를 재입력받는다."""
    n = 3
    while True:
        print("{} (3줄 입력, 공백 구분)".format(name))
        rows = []
        error = None
        for _ in range(n):
            line = input()  # EOFError propagates to the caller; retrying on EOF would loop forever.
            tokens = line.split()
            if len(tokens) != n:
                error = "입력 형식 오류: 각 줄에 {}개의 숫자를 공백으로 구분해 입력하세요.".format(n)
                break
            try:
                rows.append([float(tok) for tok in tokens])
            except ValueError:
                error = "입력 형식 오류: 숫자로 변환할 수 없는 값이 있습니다. 각 줄에 {}개의 숫자를 공백으로 구분해 입력하세요.".format(n)
                break

        if error:
            print(error)
            print("다시 입력해주세요.\n")
            continue

        ok, grid, _n, err = validate_grid(rows, expected_n=n)
        if not ok:
            print("입력 형식 오류: {}".format(err))
            print("다시 입력해주세요.\n")
            continue

        return grid


def format_score(score):
    # type: (float) -> str
    return "{:.10f}".format(score) if score != int(score) else "{:.1f}".format(score)


def run_mode_1():
    # type: () -> None
    print("\n#" + "-" * 40)
    print("# [1] 필터 입력")
    print("#" + "-" * 40)
    filter_a = read_grid_3x3("필터 A")
    filter_b = read_grid_3x3("필터 B")
    print("\n필터 A, 필터 B 저장 완료.")

    print("\n#" + "-" * 40)
    print("# [2] 패턴 입력")
    print("#" + "-" * 40)
    pattern = read_grid_3x3("패턴")

    print("\n#" + "-" * 40)
    print("# [3] MAC 결과")
    print("#" + "-" * 40)
    score_a = mac(pattern, filter_a)
    score_b = mac(pattern, filter_b)
    judgement = judge_scores(score_a, score_b, "A", "B")
    avg_ms = measure_mac_time(pattern, filter_a, PERF_REPEAT)

    print("A 점수: {}".format(format_score(score_a)))
    print("B 점수: {}".format(format_score(score_b)))
    print("연산 시간(평균/{}회): {:.4f} ms".format(PERF_REPEAT, avg_ms))
    if judgement == "UNDECIDED":
        print("판정: 판정 불가 (|A-B| < {:.0e}, epsilon 동점 규칙)".format(EPSILON))
    else:
        print("판정: {}".format(judgement))


# ---------------------------------------------------------------------------
# 8. 모드 2 - data.json 분석
# ---------------------------------------------------------------------------

def make_case_result(case_id, status, reason_code=None, reason_message=None,
                      expected=None, prediction=None,
                      score_cross=None, score_x=None, size=None):
    # type: (...) -> Dict[str, Any]
    return {
        "case_id": case_id,
        "status": status,
        "reason_code": reason_code,
        "reason_message": reason_message,
        "expected": expected,
        "prediction": prediction,
        "score_cross": score_cross,
        "score_x": score_x,
        "size": size,
    }


def load_data_json(path):
    # type: (str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return False, None, "파일을 찾을 수 없습니다: {}".format(path)
    except json.JSONDecodeError as e:
        return False, None, "JSON 파싱 오류: {}".format(e)
    except OSError as e:
        return False, None, "파일을 읽을 수 없습니다: {}".format(e)

    if not isinstance(data, dict):
        return False, None, "최상위 JSON 구조가 객체(dict)가 아닙니다."
    if "filters" not in data or not isinstance(data["filters"], dict):
        return False, None, "filters 필드가 없거나 객체가 아닙니다."
    if "patterns" not in data or not isinstance(data["patterns"], dict):
        return False, None, "patterns 필드가 없거나 객체가 아닙니다."

    return True, data, None


def build_filters_by_size(filters_raw):
    # type: (Dict[str, Any]) -> Tuple[Dict[int, Dict[str, Grid]], List[str]]
    filters_by_size = {}  # type: Dict[int, Dict[str, Grid]]
    messages = []
    for key, value in filters_raw.items():
        m = FILTER_KEY_RE.match(key)
        if not m:
            continue
        n = int(m.group(1))
        ok, normalized, err = validate_filter_set(value, expected_n=n)
        if not ok:
            messages.append("✗ {} 필터 로드 실패: {}".format(key, err))
            continue
        filters_by_size[n] = normalized
        messages.append("✓ {} 필터 로드 완료 (Cross, X)".format(key))
    return filters_by_size, messages


def analyze_case(case_id, pattern_entry, filters_by_size):
    # type: (str, Any, Dict[int, Dict[str, Grid]]) -> Dict[str, Any]
    m = CASE_KEY_RE.match(case_id)
    if not m:
        return make_case_result(
            case_id, "FAIL", "INVALID_CASE_KEY",
            "size_{N}_{idx} 형식에서 N을 읽을 수 없습니다.")

    n_from_key = int(m.group(1))

    if not isinstance(pattern_entry, dict):
        return make_case_result(
            case_id, "FAIL", "PATTERN_GRID_INVALID",
            "패턴 항목이 객체(dict) 형식이 아닙니다.", size=n_from_key)

    expected_label = normalize_label(pattern_entry.get("expected"))

    ok, pattern_grid, pattern_n, err = validate_grid(pattern_entry.get("input"))
    if not ok:
        return make_case_result(
            case_id, "FAIL", "PATTERN_GRID_INVALID", err,
            expected=expected_label, size=n_from_key)

    if pattern_n != n_from_key:
        return make_case_result(
            case_id, "FAIL", "SIZE_MISMATCH",
            "키에서 읽은 크기 {}와 패턴 행렬 크기 {}가 다릅니다.".format(n_from_key, pattern_n),
            expected=expected_label, size=n_from_key)

    filters = filters_by_size.get(n_from_key)
    if filters is None:
        return make_case_result(
            case_id, "FAIL", "FILTER_NOT_FOUND",
            "size_{} 필터가 없습니다(로드 실패 또는 누락).".format(n_from_key),
            expected=expected_label, size=n_from_key)

    if len(filters["Cross"]) != pattern_n or len(filters["X"]) != pattern_n:
        return make_case_result(
            case_id, "FAIL", "SIZE_MISMATCH",
            "필터 크기와 패턴 크기가 다릅니다.", expected=expected_label, size=n_from_key)

    if expected_label is None:
        return make_case_result(
            case_id, "FAIL", "EXPECTED_LABEL_INVALID",
            "expected 값 '{}'을 Cross/X로 정규화할 수 없습니다.".format(pattern_entry.get("expected")),
            size=n_from_key)

    score_cross = mac(pattern_grid, filters["Cross"])
    score_x = mac(pattern_grid, filters["X"])
    prediction = judge_scores(score_cross, score_x, "Cross", "X")

    if prediction == "UNDECIDED":
        return make_case_result(
            case_id, "FAIL", "UNDECIDED",
            "동점(|Cross-X| < {:.0e}) 규칙에 따라 FAIL".format(EPSILON),
            expected=expected_label, prediction=prediction,
            score_cross=score_cross, score_x=score_x, size=n_from_key)

    if prediction != expected_label:
        return make_case_result(
            case_id, "FAIL", "PREDICTION_MISMATCH",
            "판정 {}이(가) expected {}와 다릅니다.".format(prediction, expected_label),
            expected=expected_label, prediction=prediction,
            score_cross=score_cross, score_x=score_x, size=n_from_key)

    return make_case_result(
        case_id, "PASS", None, None,
        expected=expected_label, prediction=prediction,
        score_cross=score_cross, score_x=score_x, size=n_from_key)


def print_case_result(result):
    # type: (Dict[str, Any]) -> None
    print("--- {} ---".format(result["case_id"]))
    if result["score_cross"] is None:
        print("판정 불가(스키마 오류): {} [{}]".format(result["reason_message"], result["reason_code"]))
        return
    print("Cross 점수: {}".format(format_score(result["score_cross"])))
    print("X 점수: {}".format(format_score(result["score_x"])))
    print("판정: {} | expected: {} | {}".format(
        result["prediction"], result["expected"], result["status"]))
    if result["status"] == "FAIL":
        print("  사유: {}".format(result["reason_message"]))


def print_summary(results):
    # type: (List[Dict[str, Any]]) -> None
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = total - passed

    print("총 테스트: {}개".format(total))
    print("통과: {}개".format(passed))
    print("실패: {}개".format(failed))

    if failed > 0:
        print("\n실패 케이스:")
        for r in results:
            if r["status"] == "FAIL":
                print("- {}: {}".format(r["case_id"], r["reason_message"]))
    else:
        print(
            "\n실패 0건: expected/필터 라벨을 Cross/X로 정규화하고, "
            "epsilon({:.0e}) 동점 규칙을 모든 케이스에 동일하게 적용한 결과 "
            "판정과 expected가 모두 일치했습니다.".format(EPSILON)
        )


def run_mode_2(json_path):
    # type: (str) -> None
    print("\n#" + "-" * 40)
    print("# [1] 필터 로드")
    print("#" + "-" * 40)

    ok, data, err = load_data_json(json_path)
    if not ok:
        print("data.json을 불러올 수 없습니다: {}".format(err))
        print("메뉴로 돌아갑니다.")
        return

    filters_by_size, load_messages = build_filters_by_size(data["filters"])
    for msg in load_messages:
        print(msg)

    print("\n#" + "-" * 40)
    print("# [2] 패턴 분석 (라벨 정규화 적용)")
    print("#" + "-" * 40)

    patterns = data["patterns"]
    results = []
    for case_id, entry in patterns.items():
        result = analyze_case(case_id, entry, filters_by_size)
        results.append(result)
        print_case_result(result)

    print("\n#" + "-" * 40)
    print("# [3] 성능 분석 (평균/{}회)".format(PERF_REPEAT))
    print("#" + "-" * 40)
    perf_rows = build_performance_rows(filters_by_size)
    print_performance_table(perf_rows)

    print("\n#" + "-" * 40)
    print("# [4] 결과 요약")
    print("#" + "-" * 40)
    print_summary(results)


# ---------------------------------------------------------------------------
# 9. 진입점
# ---------------------------------------------------------------------------

def main():
    # type: () -> None
    print("=== Mini NPU Simulator ===")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "data.json")

    while True:
        print("\n[모드 선택]")
        print("1. 사용자 입력 (3x3)")
        print("2. data.json 분석")
        print("0. 종료")
        try:
            choice = input("선택: ").strip()
        except EOFError:
            print("\n입력이 종료되어 프로그램을 종료합니다.")
            break

        if choice == "1":
            try:
                run_mode_1()
            except EOFError:
                print("\n입력이 종료되어 프로그램을 종료합니다.")
                break
        elif choice == "2":
            run_mode_2(json_path)
        elif choice == "0":
            print("종료합니다.")
            break
        else:
            print("잘못된 선택입니다. 1, 2, 0 중에서 선택하세요.")


if __name__ == "__main__":
    main()
