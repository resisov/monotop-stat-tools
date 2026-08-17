# 하드로닉 모노톱 Run 3 통계 워크플로우

한 번의 명령으로 Coffea `.scaled` 히스토그램 누산기(accumulator)에서
트랜스퍼 팩터, pass/fail 컨트롤 플롯, CMS Combine 데이터카드와
워크스페이스, 블라인드된 기대 리미트, nuisance parameter 영향도, 최종
플롯까지 생성합니다.

## 빠른 시작

아래 설명에 따라 분석 환경을 만들고 CMS Combine을 빌드한 다음, 원하는
era 설정으로 워크플로우를 실행합니다.

```bash
conda env create -f environment-combine.yml
conda activate combine

python3 run_simple.py \
  --config config/analysis_2022EE.json \
  --input /path/to/hadmonotop2022EE_0702.scaled \
  --combine-prefix "$CONDA_PREFIX" \
  --output outputs/2022EE \
  --workers 4
```

기본 실행 순서는 다음과 같습니다.

```text
build -> plots -> limits -> interpolation -> impacts -> validate
```

워크플로우는 중단된 지점부터 재개할 수 있습니다. 같은 명령을 다시
실행하면 이미 완성된 산출물을 재사용합니다. 입력 파일의 SHA-256이
일치할 때만 빌드 캐시를 사용하므로, `.scaled` 파일이 바뀌면 이후의
Combine 산출물도 자동으로 무효화됩니다. 모든 결과를 명시적으로 다시
계산하려면 `--force`를 사용합니다.

Combine 설치 여부와 관계없이, 출력 디렉터리를 만들지 않고 실행될
명령을 미리 확인할 수 있습니다.

```bash
python3 run_simple.py \
  --config config/analysis_2023.json \
  --input /path/to/hadmonotop2023_0702.scaled \
  --output outputs/2023 \
  --dry-run
```

선행 산출물이 이미 있다면 필요한 단계만 선택해서 실행할 수도 있습니다.

```bash
python3 run_simple.py \
  --config config/analysis_2023.json \
  --input /path/to/hadmonotop2023_0702.scaled \
  --output outputs/2023 \
  --stages build plots
```

JSON 설정 파일 없이도 표준 모델을 생성할 수 있습니다.

```bash
python3 run_simple.py \
  --input /path/to/hadmonotop2023.scaled \
  --era 2023 \
  --lumi 17.96 \
  --combine-prefix "$CONDA_PREFIX"
```

벤치마크, 보간, 불확도, worker 수, 실행 단계 옵션은
`python3 run_simple.py --help`에서 확인할 수 있습니다.

## 분석 모델

워크플로우는 다음 작업을 수행합니다.

1. `TvsQCD`를 top-fail(`0 <= score < 0.33`)과
   top-pass(`0.33 <= score <= 1`)로 나눕니다.
2. 하드로닉 recoil을 `[350, 400, 500, 600, 700, 1000] GeV`로
   리비닝하고 overflow를 마지막 빈에 포함합니다.
3. pass/fail별로 SR/CR 트랜스퍼 팩터와 전파된 MC 통계 불확도를
   계산합니다.
4. ROOT 템플릿과 각 시그널 질량점에 대한 Combine 데이터카드를
   생성합니다.
5. 블라인드된 기대 `AsymptoticLimits`를 계산하고, 시뮬레이션 질량점의
   볼록 껍질(convex hull) 내부에서만 `log10(r95)`를 보간합니다.
6. 설정된 벤치마크에 대해 background-only Asimov impact를 계산합니다.
7. 트랜스퍼 팩터, SR/CR, 기대 리미트, 영향도 플롯과 기계 판독 가능한
   검증 요약을 생성합니다.

nominal 모델은 80개의 단일 빈 채널로 구성됩니다: 8개 region × 2개 top
category × 5개 recoil 빈. Z, W, top normalization은 각 top category와
recoil 빈에서 독립적으로 float하며, 공통 `rateParam` 값이 관련 SR과
CR을 연결합니다. nominal background group은 `top`, `wjets`, `zjets`,
`zll`, `gjets`, `diboson`, `qcd`입니다.

현재 제공된 누산기에는 채워진 shape systematic 템플릿이 없습니다. 따라서
이 저장소는 background automatic MC statistics, normalization nuisance,
지정된 트랜스퍼 팩터 nuisance를 포함한 baseline nominal 모델을
구현합니다. 실험 및 이론 shape variation이 추가되기 전에는 논문 제출용
systematic 모델로 사용할 수 없습니다.

모든 리미트 산출물은 expected-only입니다. `run_limits.py`는 항상
`--run blind`를 전달하고, SR 데이터는 플롯에 표시하지 않으며, impact
fit에는 background-only Asimov 데이터셋을 사용합니다. 기록된 CR 데이터는
진단 플롯에 계속 사용할 수 있습니다.

## 산출물

각 출력 디렉터리에는 다음 파일이 생성됩니다.

- `analysis_config.json` — 모든 값이 확정된 설정
- `manifest.json` — 입력 해시, 채널, 프로세스, 시그널, 생성 이력
- `transfer_factors.csv/json`과 pass/fail TF 플롯 8개
- `plots/regions/` — SR/CR pass/fail yield 플롯 16개
- `templates/templates.root`와 `datacards/`
- `workspaces/`, `limits/limits.{csv,json,root}`, raw Combine 결과
- `interpolation/limit_interpolation.{png,pdf}`와 격자 파일
- `impacts/` — 공식 Combine impact PDF와 상위 20개 요약
- `workflow_summary.json` — 선택한 단계, 산출물 경로, 입력 SHA-256,
  최종 검증 상태

입력 파일, 생성된 출력, 로그, 배포용 아카이브는 의도적으로 Git에서
제외합니다. 워크플로우 코드, 이식 가능한 설정, relic-density 참조 자료,
테스트, 문서만 저장소에 게시합니다.

## CMS Combine 설치

CMS Combine v10은 conda/CMake를 이용해 독립형으로 빌드할 수 있습니다.

```bash
git clone --depth 1 --branch v10.6.0 \
  https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit.git

cmake -S HiggsAnalysis-CombinedLimit \
  -B HiggsAnalysis-CombinedLimit/build \
  -DCMAKE_INSTALL_PREFIX="$CONDA_PREFIX" \
  -DCMAKE_INSTALL_PYTHONDIR=lib/python3.12/site-packages \
  -DUSE_VDT=OFF

cmake --build HiggsAnalysis-CombinedLimit/build -j4
cmake --install HiggsAnalysis-CombinedLimit/build
```

지정한 prefix에는 `bin/combine`, `bin/combineTool.py`,
`bin/text2workspace.py`, `bin/plotImpacts.py`가 있어야 합니다. 이 명령들이
이미 `PATH`에 있다면 prefix를 생략할 수 있습니다.

## 저장소 구조

```text
run_simple.py                 표준 올인원 CLI
config/                       이식 가능한 era 설정
workflow/build_model.py       scaled 입력 -> TF, 템플릿, 데이터카드
workflow/run_limits.py        병렬 blinded expected limit 계산
workflow/run_impacts.py       blinded 벤치마크 impact 계산
workflow/interpolate_limits.py 및 플로팅 스크립트
external/relic_densities/     참조 등고선 입력
tests/                        부작용 및 생성 이력 테스트
```

다음 명령으로 기본 검사를 실행할 수 있습니다.

```bash
PYTHONPYCACHEPREFIX=/tmp/monotop-pycache \
  python3 -m compileall -q run_simple.py workflow tests
python3 -m unittest discover -s tests -v
```
