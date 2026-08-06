# Mini NPU 시뮬레이터: 종합 실전 학습 가이드 (Mastering Mini NPU Simulator)

> **Target Audience**: 파이썬으로 인공지능(AI) 가속기 연산 원리, 수치 안정성, 안전한 CLI 및 JSON 스키마 검증 엔진, 성능 프로파일링을 학습하고자 하는 소프트웨어 개발자
> 
> **Prerequisites**: Python 3.8 이상, 파이썬 기본 리스트 및 예외 처리 지식
> 
> **Based Documents**: `docs/reference.md` 및 `docs/TODO.md` (전체 요구사항 반영)

---

## 학습 목표

이 가이드를 마친 뒤에는 다음을 직접 설명하고 구현할 수 있어야 합니다.

1. N×N 패턴과 필터의 MAC 점수를 이중 반복문으로 계산한다.
2. CLI와 JSON에서 들어온 데이터를 안전한 정방 Grid로 검증한다.
3. 서로 다른 외부 라벨을 Cross와 X라는 하나의 내부 표현으로 정규화한다.
4. epsilon 정책으로 부동소수점 동점과 판정 불가를 일관되게 처리한다.
5. 모드 1의 재입력 UX와 모드 2의 케이스 단위 FAIL 지속 처리를 분리해 구현한다.
6. 순수 MAC 호출만 측정해 O(N²) 성능을 해석하고, 1차원 평탄화 결과를 과장 없이 비교한다.

> [!NOTE]
> 이 문서는 설명용 예시와 실제 프로젝트의 구현을 함께 다룹니다. 최종 동작의 기준은 항상 [main.py](../../main.py), [README.md](../../README.md), [tests/test_main.py](../../tests/test_main.py)입니다.

## 📚 목차 (Table of Contents)

1. [개요 및 Mini NPU 시뮬레이터 아키텍처](#1-개요-및-mini-npu-시뮬레이터-아키텍처)
2. [Python 3.8 호환성 및 공통 설계 원칙](#2-python-38-호환성-및-공통-설계-원칙)
3. [데이터 구조와 2차원 Grid 검증 계약](#3-데이터-구조와-2차원-grid-검증-계약)
4. [핵심 연산: MAC (Multiply-Accumulate) 및 라벨 정규화](#4-핵심-연산-mac-multiply-accumulate-및-라벨-정규화)
5. [부동소수점 수치 안정성과 Epsilon 동점 판정](#5-부동소수점-수치-안정성과-epsilon-동점-판정)
6. [모드 1: 인터랙티브 사용자 입력 (3×3) 구현 및 예외 은닉](#6-모드-1-인터랙티브-사용자-입력-33-구현-및-예외-은닉)
7. [모드 2: JSON 분석과 견고한 스키마 검증 엔진](#7-모드-2-json-분석과-견고한-스키마-검증-엔진)
8. [성능 프로파일링과 O(N²) 시간복잡도 해석](#8-성능-프로파일링과-on²-시간복잡도-해석)
9. [보너스 과제: 1차원 평탄화(Flat Grid) 메모리 최적화 및 패턴 생성기](#9-보너스-과제-1차원-평탄화flat-grid-메모리-최적화-및-패턴-생성기)
10. [종합 퀴즈 및 수동/자동 테스트 체계](#10-종합-퀴즈-및-수동자동-테스트-체계)
11. [실제 프로젝트와 학습 내용을 연결하기](#11-실제-프로젝트와-학습-내용을-연결하기)

---

## 1. 개요 및 Mini NPU 시뮬레이터 아키텍처

### 1-1. NPU(Neural Processing Unit)와 MAC 연산
현대 NPU 및 AI 가속기(TPU, NPU 등)의 핵심 역할은 행렬 연산, 특히 **MAC(Multiply-Accumulate, 곱셈-누적)** 연산을 대량으로 빠르게 수행하는 것입니다.

$$
Score = \sum_{i=0}^{N-1} \sum_{j=0}^{N-1} (\text{Pattern}[i][j] \times \text{Filter}[i][j])
$$

본 시뮬레이터는 외부 라이브러리(NumPy 등) 없이, 순수 파이썬 반복문만으로 $N \times N$ 크기의 패턴과 필터(십자가 `Cross`, X 모양 `X`) 사이의 유사도를 계산하여 입력 패턴의 종을 판정합니다.

### 1-2. 파이프라인 데이터 흐름
아래 그래프는 입력부터 판정 및 결과 출력까지의 파이프라인 흐름을 나타냅니다.

```mermaid
flowchart TD
    Start([시작: main.py]) --> Menu{메뉴 선택}
    Menu -->|모드 1| Input3x3[사용자 입력 3x3 파싱]
    Menu -->|모드 2| LoadJSON[data.json 파싱 및 검증]
    
    Input3x3 --> GridVal1[Grid 3x3 유효성 검증]
    GridVal1 -->|실패| Err1[원인 안내 후 전체 재입력] --> Input3x3
    GridVal1 -->|성공| Calc1[MAC(Pattern, A) & MAC(Pattern, B)]
    
    LoadJSON --> JSONVal{파일/최상위 스키마 유효?}
    JSONVal -->|불가| Err2[안내 후 메뉴 복귀] --> Menu
    JSONVal -->|성공| CaseLoop[패턴 케이스 순회]
    
    CaseLoop --> CaseCheck{케이스 검증 PASS?}
    CaseCheck -->|FAIL| RecordFail[FAIL 이유 및 식별자 기록]
    CaseCheck -->|PASS| Calc2[MAC(Pattern, Cross) & MAC(Pattern, X)]
    
    Calc1 --> Judge1[Epsilon 동점 판정: A/B/판정불가]
    Calc2 --> Judge2[Epsilon 동점 판정: Cross/X/UNDECIDED]
    
    Judge1 --> Perf1[3x3 MAC 시간 측정 및 출력]
    Judge2 --> Perf2[3x3/5x5/13x13/25x25 MAC 시간 측정]
    
    RecordFail --> Summary[최종 결과 리포트 출력: Total=PASS+FAIL]
    Perf2 --> Summary
```

---

## 2. Python 3.8 호환성 및 공통 설계 원칙

### 2-1. 하위 호환성 제약 (Python 3.8+)
최신 Python 3.10+의 Union 타입(`A | B`)이나 Python 3.9+의 내장 제네릭(`list[int]`)은 Python 3.8에서 지원되지 않는 문법 또는 타입 표기입니다. Python 3.8에서는 프로그램이 실행되기 전에 SyntaxError 또는 호환성 오류가 발생할 수 있으므로, `typing` 모듈을 명시적으로 사용해야 합니다.

```python
# ❌ 잘못된 예 (Python 3.9+ 전용)
def process_grid(matrix: list[list[float]]) -> float | None:
    pass

# ✅ 올바른 예 (Python 3.8 호환)
from typing import List, Optional, Tuple, Dict, Union

Grid = List[List[float]]

def process_grid(matrix: Grid) -> Optional[float]:
    pass
```

### 2-2. 단일 파일 책임 분리 (Separation of Concerns)
단일 파일 `main.py` 제출 환경이더라도 함수 간 책임이 명확히 분리되어야 테스트와 성능 프로파일링이 쉬워집니다.

- **Data Validation**: `validate_grid()`, `normalize_label()`
- **Core Engine**: `mac()`, `judge_scores()`
- **I/O & Handling**: `read_grid_3x3()`, `load_data_json()`
- **Profiling**: `measure_mac_time()`

---

## 3. 데이터 구조와 2차원 Grid 검증 계약

### 3-1. 정방 행렬(Grid) 계약 조건
계산(MAC)에 전달되는 행렬은 엄격한 규칙을 만족해야 합니다:
1. `list` 타입이며 비어있지 않음.
2. 모든 행이 `list` 형태임.
3. 행의 개수와 열의 개수가 동일한 $N \times N$ 형태임.
4. 모든 원소가 `float`로 변환 가능하며 `NaN`, `Infinity`가 아님.

### 3-2. Grid 검증 구현 예시
```python
import math
from typing import List, Tuple, Optional, Any

Grid = List[List[float]]

def validate_grid(matrix: Any, expected_size: Optional[int] = None) -> Tuple[bool, Optional[Grid], int, Optional[str]]:
    """
    행렬 유효성 검증 함수.
    반환: (is_valid, normalized_grid, size, error_message)
    """
    if not isinstance(matrix, list) or len(matrix) == 0:
        return False, None, 0, "행렬이 비어있거나 리스트 형태가 아닙니다."
    
    rows = len(matrix)
    if expected_size is not None and rows != expected_size:
        return False, None, 0, f"기대 크기({expected_size})와 실제 행 수({rows})가 일치하지 않습니다."

    normalized_grid: Grid = []
    for r_idx, row in enumerate(matrix):
        if not isinstance(row, list):
            return False, None, 0, f"{r_idx}번째 행이 리스트 형태가 아닙니다."
        if len(row) != rows:
            return False, None, 0, f"정방 행렬이 아닙니다. (행 수: {rows}, {r_idx}행 열 수: {len(row)})"
        
        norm_row: List[float] = []
        for c_idx, val in enumerate(row):
            if isinstance(val, bool):  # bool은 int의 서브클래스이므로 수동 거부
                return False, None, 0, f"({r_idx}, {c_idx}) 위치에 불리언(bool) 값은 허용되지 않습니다."
            try:
                num = float(val)
                if math.isnan(num) or math.isinf(num):
                    return False, None, 0, f"({r_idx}, {c_idx}) 위치에 유효하지 않은 숫자(NaN/Inf)가 있습니다."
                norm_row.append(num)
            except (ValueError, TypeError):
                return False, None, 0, f"({r_idx}, {c_idx}) 위치의 '{val}'을(를) 숫자로 변환할 수 없습니다."
        normalized_grid.append(norm_row)

    return True, normalized_grid, rows, None
```

---

## 4. 핵심 연산: MAC (Multiply-Accumulate) 및 라벨 정규화

### 4-1. 순수 반복문 MAC 구현
벡터화 라이브러리 없이 2중 `for` 루프를 순회하며 위치별 곱의 누적합을 구합니다.

```python
def mac(pattern: Grid, filter_grid: Grid) -> float:
    """
    패턴과 필터 간의 MAC 연산 수행.
    반환: 누적합 (float)
    """
    size = len(pattern)
    total_score = 0.0
    for r in range(size):
        for c in range(size):
            total_score += pattern[r][c] * filter_grid[r][c]
    return total_score
```

### 4-2. 라벨 정규화 (Label Normalization)
외부 입력의 다양한 라벨 표현(`+`, `cross`, `Cross`, `x`, `X`)을 내부 유일 표준 라벨인 **`Cross`**와 **`X`**로 정규화합니다.

| 원본 입력 문자열 | 정규화 결과 | 비고 |
|:---:|:---:|:---:|
| `+`, `cross`, `CROSS`, `Cross` | **`Cross`** | 십자가 모양 |
| `x`, `X` | **`X`** | X 모양 |
| 기타 (예: `circle`, `?`) | `None` | 유효하지 않은 라벨 (FAIL) |

```python
def normalize_label(raw_label: Any) -> Optional[str]:
    if not isinstance(raw_label, str):
        return None
    cleaned = raw_label.strip().lower()
    if cleaned in ["+", "cross"]:
        return "Cross"
    elif cleaned == "x":
        return "X"
    return None
```

---

## 5. 부동소수점 수치 안정성과 Epsilon 동점 판정

### 5-1. 부동소수점 오차와 == 연산의 위험성
컴퓨터의 이진 부동소수점 표현 한계로 인해 $0.1 + 0.2 \neq 0.3$ 과 같은 미세한 오차가 발생합니다.
따라서 `score_A == score_B` 형태로 동점을 비교해서는 안 됩니다.

### 5-2. Epsilon 판정 규칙
절댓값 차이가 $\epsilon = 10^{-9}$ 미만인 경우 **`UNDECIDED` (판정 불가)**로 처리합니다.

$$
\text{Result} = \begin{cases} 
\text{UNDECIDED} & \text{if } |S_{\text{left}} - S_{\text{right}}| < \epsilon \\
\text{Left\_Label} & \text{if } S_{\text{left}} - S_{\text{right}} \ge \epsilon \\
\text{Right\_Label} & \text{if } S_{\text{right}} - S_{\text{left}} \ge \epsilon 
\end{cases}
$$

```python
EPSILON = 1e-9

def judge_scores(left_score: float, right_score: float, 
                 left_label: str, right_label: str, 
                 epsilon: float = EPSILON) -> str:
    diff = left_score - right_score
    if abs(diff) < epsilon:
        return "UNDECIDED"
    elif diff > 0:
        return left_label
    else:
        return right_label
```

---

## 6. 모드 1: 인터랙티브 사용자 입력 (3×3) 구현 및 예외 은닉

### 6-1. 사용자 경험 및 에러 처리 지침
- 잘못된 메뉴 선택이나 입력 오류 시 **Traceback(예외 스택)을 절대 화면에 노출하지 않습니다.**
- 오류 발생 원인과 기대 형태를 친절히 알린 뒤, 행렬 **전체 재입력** 정책을 일관되게 적용합니다.

### 6-2. 3×3 행렬 입력 가이드 구현
```python
def read_grid_3x3(matrix_name: str) -> Grid:
    while True:
        print(f"\n[{matrix_name} 입력 (3줄, 각 줄에 3개 숫자 공백 구분)]")
        rows = []
        has_error = False
        for i in range(3):
            line = input(f" {i+1}행: ").strip()
            tokens = line.split()
            if len(tokens) != 3:
                print(f"❌ [입력 형식 오류] 각 줄에 3개의 숫자를 공백으로 구분해 입력해야 합니다. (입력받은 개수: {len(tokens)})")
                has_error = True
                break
            
            row_floats = []
            for tok in tokens:
                try:
                    val = float(tok)
                    if math.isnan(val) or math.isinf(val):
                        print(f"❌ [입력 값 오류] NaN이나 Inf는 입력할 수 없습니다.")
                        has_error = True
                        break
                    row_floats.append(val)
                except ValueError:
                    print(f"❌ [숫자 변환 오류] '{tok}'은(는) 올바른 숫자가 아닙니다.")
                    has_error = True
                    break
            if has_error:
                break
            rows.append(row_floats)
        
        if not has_error and len(rows) == 3:
            return rows
        print("⚠️ 행렬 입력을 처음부터 다시 시도합니다.")
```

### 6-3. 기준 벤치마크 테스트 (십자가 A, X B, X 패턴)
- **Filter A (십자가)**: `[[0,1,0], [1,1,1], [0,1,0]]`
- **Filter B (X 모양)**: `[[1,0,1], [0,1,0], [1,0,1]]`
- **Pattern (X 모양)**: `[[1,0,1], [0,1,0], [1,0,1]]`
- **계산 결과**: Score A = $1.0$, Score B = $5.0$ $\rightarrow$ **판정: B**

---

## 7. 모드 2: JSON 분석과 견고한 스키마 검증 엔진

### 7-1. `data.json` 데이터 계약
```json
{
  "filters": {
    "size_5": { "cross": [[...]], "x": [[...]] },
    "size_13": { "cross": [[...]], "x": [[...]] },
    "size_25": { "cross": [[...]], "x": [[...]] }
  },
  "patterns": {
    "size_5_1": {
      "input": [[...]],
      "expected": "+"
    }
  }
}
```

### 7-2. 스키마 검증 및 FAIL 트래킹 정책
1. `patterns` 키는 `size_{N}_{idx}` 형태여야 함.
2. 지정된 $N$ 크기의 필터(`size_N`)가 존재해야 함.
3. 개별 패턴 케이스가 크기 불일치나 라벨 오류 등으로 실패하더라도, **전체 프로그램 실행을 중단하지 않고 해당 케이스만 FAIL 처리** 후 다음 케이스 진행.
4. **리포트 수식 정합성**: $\text{Total Cases} = \text{PASS Cases} + \text{FAIL Cases}$

---

## 8. 성능 프로파일링과 O(N²) 시간복잡도 해석

### 8-1. MAC 연산의 $O(N^2)$ 복잡도 원리
$N \times N$ 행렬의 모든 $N^2$ 개 원소를 2중 반복문으로 한 번씩 접근하여 곱셈과 가산 연산을 수행하므로, 1회 MAC 연산의 시간복잡도는 **$O(N^2)$**입니다.

- $N=3 \rightarrow 3^2 = 9$ 회 연산
- $N=5 \rightarrow 5^2 = 25$ 회 연산
- $N=13 \rightarrow 13^2 = 169$ 회 연산
- $N=25 \rightarrow 25^2 = 625$ 회 연산

> ⚠️ 두 필터(Cross, X)를 모두 채점하는 분류 전체 연산 비용은 $2 \times N^2 = 2N^2$ 입니다.

### 8-2. 정확한 프로파일링 측정 코드
```python
import time

def measure_mac_time(pattern: Grid, filter_grid: Grid, repeat: int = 10) -> float:
    """
    pure MAC 구간만 perf_counter로 repeat 횟수만큼 반복 측정.
    반환: 평균 연산 시간 (ms)
    """
    start_time = time.perf_counter()
    for _ in range(repeat):
        mac(pattern, filter_grid)
    end_time = time.perf_counter()
    
    avg_seconds = (end_time - start_time) / repeat
    return avg_seconds * 1000.0  # 초 -> ms 변환
```

---

## 9. 보너스 과제: 1차원 평탄화(Flat Grid) 메모리 최적화 및 패턴 생성기

### 9-1. 2차원 리스트 vs 1차원 리스트 평탄화 (Flat Grid)
파이썬의 2차원 리스트(`List[List[float]]`)는 포인터 배열의 배열 구조로 메모리 파편화 및 캐시 미스를 유발할 수 있습니다. 
이를 1차원 배열(`List[float]`)로 평탄화하여 `flat[r * N + c]` 방식으로 접근하면 메모리 연속성을 높일 수 있습니다.

```python
def flatten_grid(grid: Grid) -> Tuple[List[float], int]:
    N = len(grid)
    flat = [grid[r][c] for r in range(N) for c in range(N)]
    return flat, N

def mac_flat(flat_pattern: List[float], flat_filter: List[float], N: int) -> float:
    total = 0.0
    total_elements = N * N
    for i in range(total_elements):
        total += flat_pattern[i] * flat_filter[i]
    return total
```

---

## 10. 종합 퀴즈 및 수동/자동 테스트 체계

### Q1. Epsilon 동점 판정
- 점수 A: `0.9000000000000000`, 점수 B: `0.8999999999999999` 이고 `EPSILON = 1e-9` 일 때 판정 결과는?
  - **정답**: 차이가 $10^{-16} < 10^{-9}$ 이므로 **`UNDECIDED` (판정 불가)** 입니다.

### Q2. 수식 정합성
- `data.json`에 10개의 패턴이 있을 때 2개가 스키마 오류라면 Total, PASS, FAIL의 관계는?
  - **정답**: Total: 10, PASS: 8, FAIL: 2 이며 $10 = 8 + 2$ 조건이 충족됩니다.

---
## 11. 실제 프로젝트와 학습 내용을 연결하기

앞선 장의 개념은 추상적인 설계에 그치지 않습니다. 이 프로젝트는 아래와 같이 작은 함수들로 책임을 나누어 실제로 구현되어 있습니다.

| 학습 개념 | 실제 함수 | 확인할 핵심 동작 |
|---|---|---|
| Grid 계약 | validate_grid | 정방 행렬, bool, 숫자, NaN/Inf, 기대 크기를 확인 |
| MAC 엔진 | mac | 반복문으로 위치별 곱과 누적합 수행 |
| 라벨 정책 | normalize_label, validate_filter_set | Cross/X 표준화 및 중복 필터 라벨 거부 |
| 수치 판정 | judge_scores | abs 점수 차이가 epsilon보다 작으면 UNDECIDED |
| 모드 1 | read_grid_3x3, run_mode_1 | 잘못된 행렬 전체 재입력 후 A/B 판정 |
| 모드 2 | load_data_json, analyze_case, run_mode_2 | 케이스별 FAIL 기록 후 다음 케이스 계속 처리 |
| 성능 | measure_mac_time | I/O를 제외한 MAC 호출 평균 ms 측정 |
| 보너스 | flatten, mac_flat | 2차원과 1차원 접근의 동일 점수 비교 |

### 11-1. 실제 Grid 정책: 콘솔과 JSON의 입력 경로를 구분한다

콘솔 모드에서는 입력 토큰을 먼저 float로 변환합니다. 반면 JSON 모드의 Grid는 이미 숫자 배열이라는 계약을 기대하므로 int 또는 float만 허용합니다. 따라서 JSON에 문자열 "1"이 들어오면 데이터 스키마 오류로 처리하는 것이 안전합니다.

~~~text
콘솔 문자열 "1.5" ── float 변환 ──> 1.5 ──> validate_grid
JSON 숫자 1.5    ────────────────────────> validate_grid
JSON 문자열 "1.5" ──────────────────────> PATTERN_GRID_INVALID
~~~

> [!IMPORTANT]
> bool은 Python에서 int의 하위 타입입니다. 따라서 숫자 여부를 검사하기 전에 bool을 먼저 거부해야 JSON의 true/false가 의도치 않게 1/0으로 계산되지 않습니다.

### 11-2. 모드 1: 전체 재입력 정책을 코드로 읽기

사용자가 한 행을 잘못 입력해도 이전에 입력한 일부 행을 저장한 채 이어서 받으면, 어떤 행렬이 실제 계산에 사용됐는지 알기 어려워집니다. 이 프로젝트는 한 줄이라도 실패하면 해당 행렬 3줄 전체를 다시 입력받습니다.

~~~python
def read_grid_3x3(name):
    while True:
        rows = []
        error = None

        for _ in range(3):
            tokens = input().split()
            if len(tokens) != 3:
                error = "각 줄에는 숫자 3개가 필요합니다."
                break

            try:
                rows.append([float(token) for token in tokens])
            except ValueError:
                error = "숫자로 변환할 수 없는 값이 있습니다."
                break

        if error is not None:
            print(error)
            print("다시 입력해주세요.")
            continue

        ok, grid, _size, reason = validate_grid(rows, expected_n=3)
        if ok:
            return grid

        print(reason)
~~~

기준 벤치마크는 다음과 같습니다.

| 입력 | 기대 점수 또는 결과 |
|---|---|
| 필터 A = 십자가, 필터 B = X, 패턴 = X | A 점수 1.0, B 점수 5.0, 판정 B |
| 한 줄의 토큰이 2개 또는 4개 | 형식 오류 안내 후 3줄 전체 재입력 |
| 숫자가 아닌 토큰 | 변환 오류 안내 후 3줄 전체 재입력 |

### 11-3. 모드 2: 케이스 하나의 실패가 전체 분석을 멈추면 안 된다

JSON 분석에서는 정상 케이스뿐 아니라 의도적으로 잘못된 데이터도 결과 리포트의 일부입니다. 따라서 예외를 화면에 던지는 대신, 케이스 식별자와 실패 사유를 결과 객체에 담습니다.

~~~python
CASE_KEY_RE = re.compile(r"^size_(\d+)_(.+)$")


def analyze_case(case_id, entry, filters_by_size):
    matched = CASE_KEY_RE.match(case_id)
    if matched is None:
        return make_case_result(
            case_id,
            "FAIL",
            "INVALID_CASE_KEY",
            "size_{N}_{idx} 형식에서 N을 읽을 수 없습니다.",
        )

    size_from_key = int(matched.group(1))
    expected = normalize_label(entry.get("expected"))
    ok, pattern, actual_size, reason = validate_grid(entry.get("input"))

    if not ok:
        return make_case_result(
            case_id,
            "FAIL",
            "PATTERN_GRID_INVALID",
            reason,
            expected=expected,
            size=size_from_key,
        )

    if actual_size != size_from_key:
        return make_case_result(
            case_id,
            "FAIL",
            "SIZE_MISMATCH",
            "키 크기와 패턴 크기가 다릅니다.",
            expected=expected,
            size=size_from_key,
        )

    # 실제 구현은 필터 존재, expected 유효성, 두 MAC 점수와 PASS/FAIL도 이어서 처리한다.
~~~

| 실패 코드 | 의미 | 프로그램의 다음 동작 |
|---|---|---|
| INVALID_CASE_KEY | size_{N}_{idx} 형식이 아님 | 해당 케이스 FAIL 후 다음 케이스 |
| FILTER_NOT_FOUND | 필요한 size_N 필터가 없음 | 해당 케이스 FAIL 후 다음 케이스 |
| PATTERN_GRID_INVALID | input이 유효한 숫자 n×n Grid가 아님 | 해당 케이스 FAIL 후 다음 케이스 |
| SIZE_MISMATCH | 키, 패턴, 필터의 크기가 다름 | MAC을 호출하지 않고 FAIL |
| EXPECTED_LABEL_INVALID | expected를 Cross/X로 바꿀 수 없음 | 해당 케이스 FAIL |
| UNDECIDED | epsilon 안에서 두 점수가 동점 | 해당 케이스 FAIL |

항상 아래 식이 성립해야 합니다.

$$
\text{Total} = \text{PASS} + \text{FAIL}
$$

### 11-4. 프로파일링: 정확한 측정과 안전한 반복 횟수

성능 측정은 입력, 파일 읽기, print를 포함하지 않습니다. 호출 횟수는 양의 정수인지 먼저 확인하고, 한 패턴과 한 필터의 MAC 호출만 반복합니다.

~~~python
def measure_mac_time(pattern, filter_grid, repeat=10):
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat <= 0:
        raise ValueError("반복 횟수는 1 이상의 정수여야 합니다.")

    start = time.perf_counter()
    for _ in range(repeat):
        mac(pattern, filter_grid)
    elapsed = time.perf_counter() - start

    return elapsed * 1000.0 / repeat
~~~

| 크기 | MAC 1회 위치 수 | Cross/X 둘 다 판정할 때 위치 수 |
|---:|---:|---:|
| 3×3 | 9 | 18 |
| 5×5 | 25 | 50 |
| 13×13 | 169 | 338 |
| 25×25 | 625 | 1,250 |

> [!WARNING]
> 작은 Grid의 시간은 타이머 해상도와 Python 함수 호출 오버헤드의 영향을 크게 받습니다. 시간값이 항상 완벽한 비율이나 단조 증가를 보이지 않아도, N² 위치를 모두 방문한다는 알고리즘 복잡도 자체는 변하지 않습니다.

### 11-5. 1차원 평탄화: 무엇이 최적화되고 무엇이 보장되지 않는가?

2차원 리스트는 먼저 행 리스트를 찾고, 다시 열 원소를 찾습니다. 1차원 리스트는 단일 인덱스 접근으로 이중 인덱싱을 줄일 수 있습니다.

~~~python
def mac_flat(pattern_flat, filter_flat, n):
    if n <= 0:
        raise ValueError("n은 1 이상의 정수여야 합니다.")

    expected_length = n * n
    if len(pattern_flat) != expected_length:
        raise ValueError("pattern 길이가 n²와 다릅니다.")
    if len(filter_flat) != expected_length:
        raise ValueError("filter 길이가 n²와 다릅니다.")

    total = 0.0
    for index in range(expected_length):
        total += pattern_flat[index] * filter_flat[index]
    return total
~~~

> [!NOTE]
> Python의 리스트는 객체 참조를 저장하므로, 평탄화했다고 C 배열처럼 모든 float 값이 원시 연속 메모리에 놓인다고 단정할 수는 없습니다. 1차원 방식의 이점은 구현·버전·입력 크기에 따라 달라지므로, 반드시 같은 입력과 같은 반복 횟수로 측정해 비교해야 합니다.

### 11-6. 자동 테스트와 제출 전 실행 순서

~~~bash
# 모든 회귀 테스트
python3 -m unittest discover -s tests -v

# 실제 메뉴 실행
python3 main.py
~~~

현재 테스트는 다음 항목을 검증합니다.

- Grid의 빈 값, 비정방 구조, bool, NaN/Inf, 기대 크기 불일치
- 십자가/X의 기준 MAC 점수 5.0과 1.0
- 라벨 정규화, 중복 필터 라벨, epsilon 경계값
- 모드 1의 행 전체 재입력과 기준 A/B 판정
- JSON 파일 오류, 스키마 FAIL 지속 처리, 총 7개/통과 5개/실패 2개 리포트
- 2차원 MAC과 1차원 MAC의 동일 점수

### 11-7. 추가 자가 점검 퀴즈

1. <strong>질문:</strong> 차이가 정확히 epsilon인 두 점수는 UNDECIDED인가?  
   <strong>해설:</strong> 아니다. 정책은 차이가 epsilon보다 작을 때만 동점이다.

2. <strong>질문:</strong> JSON에 size_13_3이라는 키와 10×10 input이 있으면 MAC을 실행해야 하는가?  
   <strong>해설:</strong> 아니다. 키에서 읽은 13과 실제 10이 다르므로 SIZE_MISMATCH FAIL을 남기고 MAC을 건너뛴다.

3. <strong>질문:</strong> Cross와 cross가 같은 필터 묶음에 함께 있으면 어떤 문제가 생기는가?  
   <strong>해설:</strong> 둘 다 Cross로 정규화되어 어느 필터를 선택할지 모호하다. 중복 라벨 스키마 오류로 처리한다.

4. <strong>질문:</strong> 성능 표의 25×25, 625는 무엇을 뜻하는가?  
   <strong>해설:</strong> 한 패턴과 한 필터의 MAC 1회에서 방문하는 위치 수다. Cross/X 두 필터를 판정하면 1,250개 위치를 처리한다.

### 11-8. 학습 완료 체크리스트

- [ ] MAC 점수의 계산 과정을 3×3 예시로 손으로 설명할 수 있다.
- [ ] 검증 실패와 판정 실패를 서로 다른 결과 코드로 남길 수 있다.
- [ ] 모드 1에서는 재입력, 모드 2에서는 케이스 단위 FAIL 지속 처리를 선택하는 이유를 설명할 수 있다.
- [ ] Python 3.8 호환 타입 표기와 최신 문법의 차이를 안다.
- [ ] O(N²)와 2N²의 차이를 성능 표 기준으로 설명할 수 있다.
- [ ] 자동 테스트를 실행하고 실패한 테스트에서 원인을 추적할 수 있다.

이 가이드는 요구사항을 학습하고 구현을 검증하는 출발점입니다. 실제 제출 전에는 README의 실행 방법, docs/TODO.md의 완료 기준, 자동 테스트와 수동 입력 테스트를 함께 다시 확인하세요.
