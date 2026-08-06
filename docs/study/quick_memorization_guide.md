# Mini NPU 시뮬레이터: 6대 핵심 암기 점검 가이드 (Quick Memorization Guide)

> **목적**: Mini NPU 시뮬레이터 구현 및 검수 시 반드시 1초 만에 떠올려야 하는 6가지 필수 핵심 개념과 공식을 빠르게 암기하고 점검하는 암기 전용 노트입니다.

---

## 📌 30초 전체 지도

```mermaid
mindmap
  root((Mini NPU 6대 핵심))
    MAC 연산 수식
      위치별 곱의 누적합
      Sum Sum Pattern x Filter
    3x3 십자가/X 벤치마크
      A=1.0, B=5.0
      판정 = B
    Epsilon 동점 판정
      abs(A - B) < 1e-9
      UNDECIDED 판정
    라벨 정규화 맵핑
      + / cross -> Cross
      x / X -> X
    성능 표 N²의 의미
      MAC 1회 연산 횟수
      분류 전체 연산 = 2N²
    결과 리포트 수식 정합성
      Total = PASS + FAIL
      중복 카운팅 금지
```

---

> [!IMPORTANT]
> 구현 순서는 항상 입력 검증 → 라벨 정규화 → MAC 점수 계산 → epsilon 판정 → PASS/FAIL 집계입니다. 잘못된 데이터에 MAC을 먼저 실행하지 않습니다.

### 🎴 Card 1. MAC(Multiply-Accumulate) 연산 공식
- **핵심 개념**: 위치별 곱과 누적합 (Multiply-Accumulate)
- **수식 표기**:
  $$Score = \sum_{r=0}^{N-1} \sum_{c=0}^{N-1} (\text{Pattern}[r][c] \times \text{Filter}[r][c])$$
- **암기 문구**: *"같은 위치끼리 곱하고, 모든 곱을 싹 다 더한다!"*

---

### 🎴 Card 2. 3×3 십자가/X 벤치마크 기준 값
- **조건**: 십자가 필터 A, X 필터 B에 **X 패턴**을 입력했을 때
- **결과 수치**:
  - **Filter A 점수**: `1.0`
  - **Filter B 점수**: `5.0`
  - **최종 판정**: **`B`** (Score B > Score A)
- **암기 문구**: *"X 패턴을 대면 A는 1.0, B는 5.0으로 B 판정!"*

---

### 🎴 Card 3. Epsilon 부동소수점 동점 판정 (`UNDECIDED`)
- **조건**: 두 점수의 절댓값 차이가 **$\epsilon = 10^{-9}$ 미만**일 때
- **수식**: `abs(score_a - score_b) < 1e-9`
- **판정 결과**: **`UNDECIDED` (판정 불가)**
- **암기 문구**: *"차이가 1e-9보다 '작을 때'만 판정 불가(UNDECIDED)!"*

---

### 🎴 Card 4. 라벨 정규화 (Normalization) 맵핑 룰
- **입력 문자열 정규화 규칙**:
  - `+`, `cross`, `Cross` $\rightarrow$ **`Cross`** (십자가)
  - `x`, `X` $\rightarrow$ **`X`** (X 모양)
- **원칙**: 내부 판정 및 모든 콘솔/리포트 출력은 정규화된 표준 라벨만 사용.
- **암기 문구**: *"+와 cross는 Cross, x와 X는 X!"*

---

### 🎴 Card 5. 성능 표의 $N^2$ 의미
- **의미**: 한 개의 패턴과 **필터 '하나' 사이의 MAC 1회 기준** 연산 횟수.
- **구분**:
  - MAC 1회 연산 횟수 = **$N^2$** ($3\times3 \rightarrow 9$, $5\times5 \rightarrow 25$, $13\times13 \rightarrow 169$, $25\times25 \rightarrow 625$)
  - 두 필터(Cross, X) 채점 전체 연산 비용 = **$2N^2$**
- **암기 문구**: *"성능 표의 N²는 필터 1개와의 MAC 1회 연산 횟수!"*

---

### 🎴 Card 6. 결과 리포트 수식 정합성
- **공식**:
  $$\text{Total Test Cases} = \text{PASS Cases} + \text{FAIL Cases}$$
- **주의사항**: 스키마 오류/크기 불일치로 실패한 케이스도 반드시 `FAIL` 카운트에 포함되어 위 수식을 100% 만족해야 함.
- **암기 문구**: *"총계는 무조건 PASS + FAIL의 합이다!"*

---

## ⚡ 30초 실전 함정 점검

| 흔한 실수 | 반드시 기억할 정답 |
|---|---|
| 점수 동점을 동등 비교로 판단 | 절댓값 차이가 1e-9보다 작을 때만 UNDECIDED |
| 점수 차이가 정확히 1e-9면 동점 | 아니다. 엄격한 작은-값 비교이므로 더 큰 쪽으로 판정 |
| UNDECIDED와 expected X가 같다고 PASS | 아니다. expected는 Cross/X이므로 UNDECIDED는 FAIL |
| 크기가 다른 Grid도 일단 MAC 실행 | 아니다. 해당 케이스 FAIL 후 다음 케이스 |
| 성능 표의 625는 두 필터 전체 비용 | 아니다. 25×25에서 필터 하나와 MAC 1회의 N² 값 |
| 25×25 분류 전체 비용 | Cross/X 두 필터이므로 2 × 625 = 1,250 |

### 암기용 실행 주문

~~~text
검증한다 → 표준화한다 → MAC 두 번 계산한다 → epsilon으로 판정한다
→ expected와 비교한다 → PASS/FAIL을 하나 기록한다 → Total을 집계한다
~~~

## 📝 1분 셀프 암기 테스트 (Self-Check Quiz)

### 추가 실전 질문

| 질문 | 정답 |
|---|---|
| UNDECIDED이고 expected가 X이면? | FAIL |
| size_13_3 키에 10×10 입력이 오면? | SIZE_MISMATCH FAIL 후 다음 케이스 진행 |

### 다음 자료

- 구현 흐름과 코드의 이유: [종합 실전 학습 가이드](mini_npu_full_learning_guide.md)
- 실제 7대 수동 테스트 절차: [암기·테스트 체크리스트](mini_npu_memory_and_test_checklist.md)

| 번호 | 암기 질문 | 나의 답변 (직접 채워보기) | 정답 확인 |
|:---:|:---|:---:|:---:|
| **1** | MAC 연산의 두 가지 핵심 작업은? | | 위치별 곱 + 누적합 |
| **2** | 3×3 X 패턴 입력 시 필터 A, B 점수와 판정은? | | A=1.0, B=5.0, 판정 B |
| **3** | UNDECIDED 판정이 내려지는 차이 조건은? | | `abs(A - B) < 1e-9` |
| **4** | `+`와 `cross`는 어떤 라벨로 정규화되는가? | | `Cross` |
| **5** | 성능 표의 $N^2$는 필터 몇 개 기준인가? | | 필터 1개와의 MAC 1회 |
| **6** | 총 테스트 수(Total) 계산 수식은? | | `PASS + FAIL` |
