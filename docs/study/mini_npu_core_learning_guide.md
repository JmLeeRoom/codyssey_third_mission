# Mini NPU 시뮬레이터: 핵심 파이썬 설계와 알고리즘 학습 가이드

> 대상: Mini NPU 시뮬레이터의 공통 설계와 핵심 연산을 구현하려는 학습자
>
> 기반 문서: docs/reference.md의 미션 설명 및 docs/TODO.md의 3~4장
>
> 범위: MAC 연산, 2차원 Grid 검증, 라벨 정규화, epsilon 기반 판정, Python 3.8 호환 설계

---

## 학습 목표

이 문서를 마치면 다음을 설명하고 구현할 수 있습니다.

1. 2차원 패턴과 필터 사이의 MAC(Multiply-Accumulate) 연산을 이중 반복문으로 구현한다.
2. 외부 입력과 JSON 데이터를 안전한 n×n Grid 계약으로 검증한다.
3. 다양한 라벨 표기를 Cross와 X라는 내부 표준으로 정규화한다.
4. 부동소수점 오차를 고려해 epsilon 기반으로 Cross, X, UNDECIDED를 판정한다.
5. Python 3.8에서 동작하는 표준 라이브러리 기반 구조로 입출력, 검증, 계산을 분리한다.

## 먼저 보는 전체 흐름

~~~mermaid
flowchart LR
    A[콘솔 입력 또는 data.json] --> B[Grid / 스키마 검증]
    B -->|유효| C[MAC: Cross 점수]
    B -->|유효| D[MAC: X 점수]
    B -->|오류| E[케이스별 FAIL 사유 기록]
    C --> F[epsilon 기반 판정]
    D --> F
    F --> G[Cross / X / UNDECIDED]
    G --> H[expected와 비교하여 PASS / FAIL]
~~~

이 흐름에서 중요한 원칙은 한 가지입니다. **계산 전에 데이터를 검증하고, 계산 후에는 표준화된 값으로만 판정한다**는 것입니다.

> [!IMPORTANT]
> MAC 함수는 계산에만 집중해야 합니다. 파일 읽기, print, 라벨 변환, 행렬 크기 추론까지 한 함수에 넣으면 테스트와 오류 진단이 어려워집니다.

---

## 1. AI 연산의 시작: MAC(Multiply-Accumulate)

### 1-1. MAC은 무엇인가?

MAC은 같은 위치의 두 값을 곱한 뒤, 모든 곱을 하나의 합계에 누적하는 연산입니다.

수식으로는 다음과 같습니다.

$$
score = \sum_{r=0}^{N-1}\sum_{c=0}^{N-1} pattern[r][c] \times filter[r][c]
$$

여기서 <code>pattern</code>은 입력 이미지 또는 패턴이고, <code>filter</code>는 특정 모양을 찾기 위한 기준입니다. 점수가 클수록 해당 필터와 입력이 더 비슷하다는 뜻입니다.

### 1-2. 3×3 십자가와 X 예제

~~~text
십자가 패턴 P             십자가 필터 C            X 필터 X

0 1 0                    0 1 0                  1 0 1
1 1 1                    1 1 1                  0 1 0
0 1 0                    0 1 0                  1 0 1
~~~

<code>P</code>와 <code>C</code>를 겹치면 1이 겹치는 위치가 5개이므로 점수는 5입니다. 반면 <code>P</code>와 <code>X</code>는 중앙 한 칸만 1이 겹치므로 점수는 1입니다.

| 비교 | 위치별 곱의 합 | 의미 |
|---|---:|---|
| 십자가 패턴 × 십자가 필터 | 5 | 높은 유사도 |
| 십자가 패턴 × X 필터 | 1 | 낮은 유사도 |

~~~text
패턴 P ──×── 십자가 필터 C ──합산──> Cross 점수: 5
패턴 P ──×── X 필터 X      ──합산──> X 점수:     1
                                      │
                                      ▼
                              5 > 1 이므로 Cross
~~~

### 1-3. 왜 NPU와 관련이 있을까?

CPU도 MAC을 계산할 수 있습니다. 다만 일반 CPU는 여러 종류의 명령과 분기 처리를 유연하게 수행하도록 설계되어 있습니다. 반면 NPU나 GPU 같은 병렬 연산 장치는 수많은 곱셈·누적 연산을 동시에 또는 매우 높은 처리량으로 수행하는 데 초점을 둡니다.

이 미션의 파이썬 구현은 실제 NPU를 재현하는 것이 아니라, NPU가 반복적으로 수행하는 핵심 계산 단위를 이해하기 위한 시뮬레이터입니다.

> [!NOTE]
> 한 번의 n×n MAC은 N²개 위치를 방문합니다. 25×25라면 625개 위치를 순회합니다. 이 숫자가 성능 표의 연산 횟수 N²입니다.

### 1-4. 순수 Python 이중 반복문 구현

다음 함수는 **검증이 끝난 동일 크기 Grid**를 받는다고 가정합니다. 계산 함수가 입력·파일·출력을 담당하지 않으므로 단위 테스트와 성능 측정에 재사용하기 좋습니다.

~~~python
from typing import List

Grid = List[List[float]]


def mac(pattern: Grid, filter_grid: Grid) -> float:
    total = 0.0

    for row_index in range(len(pattern)):
        for column_index in range(len(pattern[row_index])):
            total += (
                pattern[row_index][column_index]
                * filter_grid[row_index][column_index]
            )

    return total
~~~

실행 예시는 다음과 같습니다.

~~~python
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

assert mac(cross, cross) == 5.0
assert mac(cross, x_shape) == 1.0
~~~

### 1-5. 시간복잡도와 성능 표

중첩 반복문은 행 N개와 각 행의 열 N개를 모두 방문하므로 시간복잡도는 O(N²)입니다.

| Grid 크기 | 위치 수 | MAC 1회에서 방문하는 위치 |
|---:|---:|---|
| 3×3 | 9 | 9 |
| 5×5 | 25 | 25 |
| 13×13 | 169 | 169 |
| 25×25 | 625 | 625 |

두 필터(Cross와 X) 모두와 비교해 하나의 패턴을 분류한다면 실제 MAC 호출은 2회입니다. 즉, 분류 한 번의 위치별 곱셈 수는 2N²입니다. 그러나 과제의 성능 표에 쓰는 N²는 **MAC 한 번**의 기준임을 구분해야 합니다.

> [!WARNING]
> <code>zip(pattern, filter_grid)</code>만으로 MAC을 구현하면 두 행렬의 길이가 다를 때 짧은 쪽까지만 조용히 계산될 수 있습니다. 크기 검증은 반드시 MAC 이전에 수행해야 합니다.

---

## 2. 안전한 데이터 처리: 2차원 Grid 검증과 계약

### 2-1. Grid 계약이 필요한 이유

모드 1의 콘솔 입력과 모드 2의 JSON 데이터는 모두 외부에서 들어오는 값입니다. 외부 데이터에는 다음과 같은 문제가 있을 수 있습니다.

~~~text
[[1, 0], [0, 1], [1, 0]]       행 수와 열 수가 다른 3×2 행렬
[[1, 0], [0]]                  행마다 길이가 다른 들쭉날쭉한 행렬
[[1, "one"], [0, 1]]           숫자로 해석할 수 없는 값
[[true, false], [false, true]] JSON의 bool 값
[[1, NaN], [0, 1]]             비교를 불안정하게 만드는 NaN
~~~

검증 없이 이 값을 MAC에 전달하면 IndexError, TypeError 또는 조용한 잘못된 결과가 발생합니다. 따라서 Grid를 사용하는 모든 계산 전에 “유효한 숫자 n×n 행렬”이라는 계약을 확인해야 합니다.

### 2-2. 검증 항목

| 순서 | 확인할 계약 | 실패 예시 | 왜 필요한가 |
|---:|---|---|---|
| 1 | 전체 값이 비어 있지 않은 리스트인가? | None, [], 문자열 | 행렬로 순회할 수 있는지 확인 |
| 2 | 모든 행이 리스트인가? | [1, 2, 3] | 2차원 구조인지 확인 |
| 3 | 모든 행 길이가 같은가? | [[1, 0], [1]] | 누락된 열을 방지 |
| 4 | 행 수와 열 수가 같은가? | 3×2 행렬 | n×n 계약 보장 |
| 5 | 기대 크기 N과 일치하는가? | size_5 키에 3×3 데이터 | JSON 키와 실제 데이터의 불일치 방지 |
| 6 | 원소가 숫자로 변환 가능한가? | "abc", None | 곱셈 가능 여부 보장 |
| 7 | bool, NaN, 무한대가 아닌가? | true, NaN, Infinity | 의도하지 않은 값과 불안정한 판정 방지 |

> [!IMPORTANT]
> Python에서 <code>bool</code>은 <code>int</code>의 하위 타입입니다. 따라서 <code>isinstance(True, int)</code>는 True입니다. JSON의 true/false를 숫자 1/0으로 잘못 받아들이지 않으려면 숫자 검사보다 먼저 bool을 거부해야 합니다.

### 2-3. validate_grid 실습 코드

아래 예시는 값이 숫자로 변환 가능한지를 허용하되, bool·NaN·무한대는 거부합니다. 성공하면 정규화한 float Grid, 크기 N, 오류 없음(None)을 반환합니다. 실패하면 오류 메시지를 반환합니다.

~~~python
import math
from typing import Any, List, Optional, Tuple

Grid = List[List[float]]
ValidationResult = Tuple[Optional[Grid], Optional[int], Optional[str]]


def validate_grid(
    raw: Any,
    expected_size: Optional[int] = None,
) -> ValidationResult:
    if not isinstance(raw, list) or not raw:
        return None, None, "행렬은 비어 있지 않은 2차원 리스트여야 합니다."

    size = len(raw)

    if expected_size is not None and size != expected_size:
        return (
            None,
            None,
            "행 수가 기대 크기 {0}과 다릅니다: {1}".format(
                expected_size,
                size,
            ),
        )

    normalized = []

    for row_index, row in enumerate(raw):
        if not isinstance(row, list):
            return None, None, "{0}번째 행이 리스트가 아닙니다.".format(row_index)

        if len(row) != size:
            return (
                None,
                None,
                "{0}번째 행의 열 수가 {1}이 아닙니다.".format(
                    row_index,
                    size,
                ),
            )

        normalized_row = []

        for column_index, value in enumerate(row):
            if isinstance(value, bool):
                return (
                    None,
                    None,
                    "({0}, {1})의 bool 값은 숫자로 허용하지 않습니다.".format(
                        row_index,
                        column_index,
                    ),
                )

            try:
                number = float(value)
            except (TypeError, ValueError):
                return (
                    None,
                    None,
                    "({0}, {1})의 값이 숫자가 아닙니다.".format(
                        row_index,
                        column_index,
                    ),
                )

            if not math.isfinite(number):
                return (
                    None,
                    None,
                    "({0}, {1})의 값은 유한한 실수여야 합니다.".format(
                        row_index,
                        column_index,
                    ),
                )

            normalized_row.append(number)

        normalized.append(normalized_row)

    return normalized, size, None
~~~

사용 방법은 다음과 같습니다.

~~~python
grid, size, error = validate_grid(
    [[0, 1, 0], [1, 1, 1], [0, 1, 0]],
    expected_size=3,
)

if error is not None:
    print("검증 실패:", error)
else:
    print("검증 성공: {0}×{0}".format(size))
~~~

### 2-4. 검증 결과를 어떻게 사용할까?

~~~mermaid
flowchart TD
    A[원본 Grid] --> B{validate_grid 성공?}
    B -->|예| C[정규화된 float Grid]
    C --> D[MAC 호출]
    B -->|아니오| E[사유 기록]
    E --> F[JSON 모드: 해당 케이스 FAIL]
    E --> G[콘솔 모드: 입력 재시도]
~~~

같은 검증 함수라도 호출 위치에 따라 대응이 달라집니다.

| 호출 위치 | 검증 실패 시 처리 |
|---|---|
| 모드 1 콘솔 입력 | 오류 문구를 보여 주고 사용자가 다시 입력하게 한다. |
| 모드 2 JSON 패턴 | 해당 case_id를 FAIL로 남기고 다음 패턴을 계속 분석한다. |
| 모드 2 필터 | 해당 크기의 필터를 쓰는 패턴을 FAIL로 처리하되, 다른 크기 패턴은 계속 분석한다. |

### 2-5. 자주 하는 실수

| 실수 | 문제 | 개선 |
|---|---|---|
| 외부 입력 검증에 assert 사용 | Python 최적화 모드에서 assert가 비활성화될 수 있음 | 명시적 if와 오류 결과 사용 |
| <code>[[0] * n] * n</code>로 행렬 생성 | 모든 행이 같은 리스트를 참조함 | 반복문 또는 리스트 컴프리헨션으로 행마다 새 리스트 생성 |
| 숫자 검사에서 bool 누락 | true/false가 1/0으로 섞임 | bool을 먼저 검사 |
| NaN을 허용 | 어떤 수와 비교해도 예상과 다른 결과가 날 수 있음 | math.isfinite로 거부 |
| 검증 실패 후에도 MAC 호출 | 원래 오류가 가려지고 예외가 연쇄 발생 | 실패 즉시 재입력 또는 케이스 FAIL |

---

## 3. 데이터 표준화: 라벨 정규화

### 3-1. 라벨 파편화 문제

같은 의미의 모양이 데이터마다 서로 다르게 표기될 수 있습니다.

| 원본 표기 | 사람이 해석한 의미 | 프로그램 내부 표준 |
|---|---|---|
| + | 십자가 | Cross |
| cross | 십자가 | Cross |
| Cross | 십자가 | Cross |
| x | X | X |
| X | X | X |

원본 문자열을 그대로 비교하면 <code>"+"</code>와 <code>"Cross"</code>가 서로 다른 것으로 처리됩니다. 데이터의 표기 차이 때문에 정상 결과가 FAIL이 되는 문제를 막기 위해 정규화가 필요합니다.

### 3-2. 정규화의 순서

~~~text
원본 라벨
   │
   ├─ 문자열인가?
   │      └─ 아니오 → 알 수 없는 라벨
   │
   ├─ 앞뒤 공백 제거
   ├─ 대소문자 구분 제거
   │
   ├─ + 또는 cross → Cross
   ├─ x             → X
   │
   └─ 그 외         → 알 수 없는 라벨
~~~

### 3-3. normalize_label 실습 코드

~~~python
from typing import Any, Optional


def normalize_label(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None

    key = raw.strip().casefold()

    if key == "+" or key == "cross":
        return "Cross"

    if key == "x":
        return "X"

    return None
~~~

<code>casefold()</code>는 소문자 변환보다 넓은 범위의 대소문자 정규화를 지원합니다. 이 과제에서는 <code>lower()</code>도 충분하지만, 의도를 드러내기 위해 <code>casefold()</code>를 사용할 수 있습니다.

~~~python
assert normalize_label("+") == "Cross"
assert normalize_label(" cross ") == "Cross"
assert normalize_label("Cross") == "Cross"
assert normalize_label("X") == "X"
assert normalize_label("triangle") is None
assert normalize_label(None) is None
~~~

### 3-4. 필터 키 중복은 왜 오류일까?

다음처럼 하나의 필터 묶음에 <code>cross</code>와 <code>Cross</code>가 동시에 있으면 둘 다 Cross로 정규화됩니다.

~~~json
{
  "cross": [[0, 1], [1, 1]],
  "Cross": [[1, 0], [0, 1]],
  "x": [[1, 0], [0, 1]]
}
~~~

어느 것을 Cross 필터로 선택해야 하는지 알 수 없으므로 모호한 스키마입니다. 이 경우 임의로 마지막 값을 덮어쓰지 말고 오류로 처리해야 합니다.

~~~python
from typing import Any, Dict, Optional, Tuple


def normalize_filter_mapping(
    raw_filters: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    normalized = {}

    for raw_label, filter_grid in raw_filters.items():
        label = normalize_label(raw_label)

        if label is None:
            return None, "알 수 없는 필터 라벨: {0}".format(raw_label)

        if label in normalized:
            return None, "중복된 표준 필터 라벨: {0}".format(label)

        normalized[label] = filter_grid

    if "Cross" not in normalized or "X" not in normalized:
        return None, "Cross와 X 필터가 모두 필요합니다."

    return normalized, None
~~~

> [!WARNING]
> 알 수 없는 라벨을 그대로 반환하거나 기본값으로 Cross에 연결하면 데이터 오류가 조용히 정답처럼 보일 수 있습니다. 알 수 없는 라벨은 반드시 제어된 FAIL 사유로 바꿔야 합니다.

### 3-5. 정규화가 적용되는 지점

| 데이터 | 정규화 시점 | 이후 사용할 값 |
|---|---|---|
| filters.size_N의 키 | 필터 묶음을 로드할 때 | Cross, X |
| patterns.*.expected | 케이스를 분석하기 전 | Cross, X |
| 콘솔 출력 | 점수 판정 후 | Cross, X 또는 UNDECIDED |
| PASS/FAIL 비교 | prediction과 expected 비교 직전 | Cross, X |

정규화는 한 번만 하고, 이후에는 표준 라벨을 결과 객체에 저장하는 방식이 가장 안전합니다.

---

## 4. 컴퓨팅 수치 해석: 부동소수점 오차와 epsilon 판정

### 4-1. 왜 실수를 ==로 비교하면 안 될까?

컴퓨터는 대부분의 실수를 2진 부동소수점 형식으로 저장합니다. 10진수 0.1은 2진수로 유한하게 끝나지 않으므로 근삿값으로 저장됩니다.

~~~python
print(0.1 + 0.2)
print((0.1 + 0.2) == 0.3)
~~~

실행 환경에 따라 첫 줄은 보통 0.30000000000000004처럼 보이고, 두 번째 줄은 False가 됩니다. 수학적으로는 같아도 메모리에 저장된 비트 패턴이 아주 조금 다를 수 있기 때문입니다.

### 4-2. epsilon 정책

이 과제에서는 두 점수의 절댓값 차이가 epsilon보다 **작으면** 동점으로 봅니다.

$$
|score_{left} - score_{right}| < \epsilon
$$

기본 epsilon은 1e-9입니다.

| 점수 차이 | 판정 |
|---|---|
| 차이 < 1e-9 | UNDECIDED |
| 차이 = 1e-9 | 동점 아님 |
| 차이 > 1e-9 | 더 큰 점수의 라벨 |

<code><=</code>가 아니라 <code><</code>를 쓴다는 점이 중요합니다. 기준 문서의 정책이 차이가 epsilon과 정확히 같은 경우를 동점으로 보지 않기 때문입니다.

### 4-3. judge_scores 실습 코드

~~~python
EPSILON = 1e-9


def judge_scores(
    left_score: float,
    right_score: float,
    left_label: str,
    right_label: str,
    epsilon: float = EPSILON,
) -> str:
    if abs(left_score - right_score) < epsilon:
        return "UNDECIDED"

    if left_score > right_score:
        return left_label

    return right_label
~~~

모드에 따라 같은 함수를 다른 라벨과 함께 쓸 수 있습니다.

~~~python
# 모드 1: 사용자 입력 필터 A/B
mode_1_result = judge_scores(1.0, 5.0, "A", "B")
# 결과: B

# 모드 2: JSON의 Cross/X 필터
mode_2_result = judge_scores(5.0, 1.0, "Cross", "X")
# 결과: Cross
~~~

### 4-4. UNDECIDED는 PASS인가?

아닙니다. JSON의 expected는 정규화 후 Cross 또는 X입니다. 따라서 판정이 UNDECIDED라면 어느 한쪽 라벨과 일치할 수 없으므로 FAIL입니다.

~~~python
from typing import Optional, Tuple


def compare_with_expected(
    prediction: str,
    expected: Optional[str],
) -> Tuple[str, Optional[str]]:
    if expected is None:
        return "FAIL", "expected 라벨을 정규화할 수 없습니다."

    if prediction == "UNDECIDED":
        return "FAIL", "epsilon 동점 규칙에 따라 판정할 수 없습니다."

    if prediction == expected:
        return "PASS", None

    return "FAIL", "예측값과 expected가 다릅니다."
~~~

다음은 기준 문서의 부동소수점 예시와 같은 상황입니다.

~~~python
result = judge_scores(
    0.9000000000000000,
    0.8999999999999999,
    "Cross",
    "X",
)

assert result == "UNDECIDED"
~~~

> [!WARNING]
> <code>math.isclose()</code>는 편리하지만 기본 상대 허용오차와 절대 허용오차 정책이 과제의 명시적 규칙과 다를 수 있습니다. 이 과제에서는 abs 차이와 EPSILON을 직접 사용해 정책을 분명하게 표현합니다.

### 4-5. 점수, 판정, 결과의 관계

~~~text
Cross 점수 ─┐
            ├─ judge_scores ──> Cross / X / UNDECIDED
X 점수     ─┘                           │
                                        ▼
expected(Cross 또는 X) ─ compare ─> PASS / FAIL
~~~

이 구조에서 점수 비교와 정답 비교를 분리하면 “동점이라 판정 불가”와 “판정은 했지만 expected와 다름”을 서로 다른 실패 사유로 기록할 수 있습니다.

---

## 5. Python 3.8 호환성과 책임 분리

### 5-1. 왜 Python 3.8을 기준으로 설계할까?

실행 환경이 Python 3.8 이상이므로 더 최신 Python에서만 지원하는 문법을 필수 코드에 쓰면 일부 환경에서 프로그램이 시작조차 하지 못할 수 있습니다.

| 용도 | Python 3.8 호환 표기 | 피해야 할 최신 문법 |
|---|---|---|
| 2차원 리스트 | <code>List[List[float]]</code> | <code>list[list[float]]</code> |
| 딕셔너리 | <code>Dict[str, Any]</code> | <code>dict[str, Any]</code> |
| 선택적 문자열 | <code>Optional[str]</code> | <code>str | None</code> |

~~~python
from typing import Any, Dict, List, Optional, Tuple

Grid = List[List[float]]
CaseResult = Dict[str, Any]
EPSILON = 1e-9
~~~

외부 라이브러리 없이도 이 과제에 필요한 기능은 표준 라이브러리로 충분합니다.

| 목적 | 표준 라이브러리 |
|---|---|
| JSON 읽기 | json |
| 성능 시간 측정 | time |
| 케이스 키 형식 검사 | re |
| 유한한 실수 검사 | math |
| Python 3.8 타입 힌트 | typing |

### 5-2. 함수별 책임 분리

~~~mermaid
flowchart TD
    A[main] --> B[모드 선택]
    B --> C[read_grid_3x3 또는 load_data_json]
    C --> D[validate_grid]
    D --> E[normalize_label]
    E --> F[mac]
    F --> G[judge_scores]
    G --> H[analyze_case / CaseResult]
    H --> I[print_case / print_summary]
    F --> J[measure_mac_time]
~~~

| 함수 또는 구성 요소 | 한 가지 책임 | 테스트 방법 |
|---|---|---|
| validate_grid | Grid 계약 검증·float 정규화 | 잘못된 행렬 입력으로 오류 문구 확인 |
| mac | 위치별 곱과 누적합 | 3×3 예시가 5.0과 1.0인지 확인 |
| normalize_label | 외부 라벨을 Cross/X로 변환 | +, cross, X, 알 수 없는 값 테스트 |
| judge_scores | epsilon 정책에 따른 라벨 선택 | 동점, 좌측 우세, 우측 우세 테스트 |
| analyze_case | 케이스 처리와 PASS/FAIL 생성 | 정상·스키마 오류 JSON 케이스 테스트 |
| measure_mac_time | 순수 MAC 호출 시간 측정 | print·파일 읽기가 측정 구간 밖인지 확인 |
| print_case / print_summary | 화면 출력 | 결과 객체로 출력 형식 확인 |

### 5-3. CaseResult를 남기는 이유

JSON 모드에서는 한 케이스가 실패해도 나머지 케이스를 계속 처리해야 합니다. 그러려면 예외만 출력하고 끝내는 대신, 각 케이스의 결과를 하나의 구조에 담아야 합니다.

~~~python
result = {
    "case_id": "size_5_1",
    "status": "PASS",
    "reason_code": None,
    "reason_message": None,
    "expected": "Cross",
    "prediction": "Cross",
    "score_cross": 5.0,
    "score_x": 1.0,
    "size": 5,
}
~~~

실패 예시는 다음과 같이 남길 수 있습니다.

~~~python
failed_result = {
    "case_id": "size_13_1",
    "status": "FAIL",
    "reason_code": "UNDECIDED",
    "reason_message": "epsilon 동점 규칙에 따라 판정할 수 없습니다.",
    "expected": "X",
    "prediction": "UNDECIDED",
    "score_cross": 0.9,
    "score_x": 0.8999999999999999,
    "size": 13,
}
~~~

이 구조를 하나의 리스트에 모은 뒤 status가 PASS인 개수와 FAIL인 개수를 세면 총계가 일관됩니다.

> [!NOTE]
> 성능 측정 함수에는 print, input, JSON 파일 읽기를 넣지 마세요. 오직 mac 호출만 시간 범위에 포함해야 크기별 비교가 의미 있습니다.

---

## 6. 구현 순서: 작은 단위부터 연결하기

다음 순서로 구현하면 오류 원인을 좁히기 쉽습니다.

1. <code>Grid</code>, <code>EPSILON</code>, Python 3.8 타입 힌트를 정의합니다.
2. <code>validate_grid()</code>을 구현하고 정상·비정상 Grid를 테스트합니다.
3. <code>mac()</code>을 구현하고 십자가/X 예제로 점수 5.0과 1.0을 확인합니다.
4. <code>normalize_label()</code>을 구현하고 +, cross, X, 알 수 없는 값을 테스트합니다.
5. <code>judge_scores()</code>와 <code>compare_with_expected()</code>를 구현합니다.
6. 모드 1에서 입력 → 검증 → MAC → 판정을 연결합니다.
7. 모드 2에서 JSON 로드 → 스키마 확인 → 케이스별 결과 객체 생성을 연결합니다.
8. 마지막에 성능 측정과 콘솔 요약을 연결합니다.

### 미니 점검 시나리오

~~~text
입력 패턴:      0 1 0
                1 1 1
                0 1 0

Cross 필터:     0 1 0      Cross 점수 = 5.0
                1 1 1
                0 1 0

X 필터:         1 0 1      X 점수 = 1.0
                0 1 0
                1 0 1

판정: Cross
expected: +
정규화 expected: Cross
최종 결과: PASS
~~~

이 한 시나리오가 통과하면 Grid 검증, MAC, 라벨 정규화, 판정, PASS 비교의 기본 연결을 확인할 수 있습니다.

---

## 7. Self-Check Quiz

### 문제 1

행 길이가 서로 다른 Grid를 MAC 함수에 바로 전달하면 왜 위험한가?

<details>
<summary>해설 보기</summary>

행렬의 같은 위치끼리 곱한다는 전제가 깨집니다. IndexError가 발생할 수 있고, zip을 쓴 구현이라면 짧은 행까지만 계산되어 잘못된 점수가 조용히 나올 수 있습니다. 따라서 n×n 검증을 먼저 해야 합니다.

</details>

### 문제 2

JSON의 true와 false를 숫자로 허용하면 어떤 문제가 생길 수 있으며, Python에서 이를 어떻게 막는가?

<details>
<summary>해설 보기</summary>

Python에서 bool은 int의 하위 타입이므로 True가 1, False가 0처럼 처리될 수 있습니다. 입력 데이터의 의미가 바뀌므로 값 검사 전에 isinstance(value, bool)로 bool을 명시적으로 거부합니다.

</details>

### 문제 3

두 점수의 차이가 정확히 1e-9라면 이 과제의 기본 정책에서 UNDECIDED인가?

<details>
<summary>해설 보기</summary>

아닙니다. 정책은 abs(score_a - score_b) < 1e-9입니다. 등호가 없으므로 차이가 정확히 epsilon이면 더 큰 점수 쪽으로 판정합니다.

</details>

### 문제 4

모드 2에서 한 패턴의 expected 라벨이 triangle이라면 프로그램 전체를 멈추지 않고 어떻게 처리해야 하는가?

<details>
<summary>해설 보기</summary>

normalize_label이 None 또는 제어된 오류를 반환하게 하고, 해당 case_id를 EXPECTED_LABEL_INVALID 같은 사유로 FAIL 결과 객체에 기록합니다. 다음 패턴은 계속 분석합니다.

</details>

---

## 마무리 체크리스트

- [ ] MAC이 위치별 곱과 누적합이라는 것을 3×3 예제로 설명할 수 있다.
- [ ] Grid 검증을 MAC보다 먼저 수행해야 하는 이유를 설명할 수 있다.
- [ ] bool, NaN, 무한대를 숫자 데이터에서 거부하는 이유를 설명할 수 있다.
- [ ] +, cross, Cross, x, X를 표준 라벨로 변환할 수 있다.
- [ ] abs 점수 차이와 epsilon으로 UNDECIDED를 판정할 수 있다.
- [ ] Python 3.8 호환 타입 표기와 최신 타입 표기의 차이를 안다.
- [ ] 한 케이스 실패가 전체 JSON 분석을 멈추지 않도록 결과 객체를 설계할 수 있다.

다음 단계는 이 문서의 함수들을 <code>main.py</code>에 연결하고, docs/TODO.md의 모드 1·모드 2·성능 분석·README 항목을 순서대로 완료하는 것입니다.

