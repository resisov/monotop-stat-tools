# 하드로닉 모노톱 Run 3 통계 워크플로우

이 저장소는 Coffea `.scaled` 히스토그램 누산기에서 다음 결과를 만드는
expected-only 통계 워크플로우입니다.

```text
.scaled 입력
  -> pass/fail 트랜스퍼 팩터와 진단 플롯
  -> ROOT 템플릿과 CMS Combine 데이터카드
  -> blinded expected limit
  -> on-shell/off-shell 질량평면 보간과 limit 플롯
  -> background-only Asimov impact
  -> 산출물 자동 검증
```

처음 사용하는 사람은 아래의 **시간순서별 실행 안내**를 위에서부터 그대로
따르면 됩니다. CMS 사용자에게는 lxplus의 CMSSW 환경을 권장합니다.

## 시간순서별 실행 안내

### 0. 시작 전에 준비할 것

필요한 것은 다음 세 가지입니다.

- lxplus 또는 `/cvmfs/cms.cern.ch`에 접근할 수 있는 EL9 Linux 환경
- 분석할 `.scaled` 파일
- Git과 약 4개 이상의 CPU 코어를 사용할 수 있는 셸

이 문서는 재현성을 위해 **CMSSW_14_1_0_pre4 + Combine v10.6.0**을
사용합니다. 이 조합은 Combine v10.6.0의 공식 CMSSW 설치 조합입니다.
새 Combine 메이저 버전으로 올릴 때는 먼저
[공식 설치 문서](https://cms-analysis.github.io/HiggsAnalysis-CombinedLimit/v10.6.0/)와
이 워크플로우의 테스트를 확인하십시오.

### 1. CMSSW와 CMS Combine 설치: 최초 1회

lxplus에 로그인한 뒤 작업용 디렉터리에서 실행합니다.

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh

cmsrel CMSSW_14_1_0_pre4
cd CMSSW_14_1_0_pre4/src
cmsenv

git -c advice.detachedHead=false clone \
  --depth 1 \
  --branch v10.6.0 \
  https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit.git \
  HiggsAnalysis/CombinedLimit

cd HiggsAnalysis/CombinedLimit
scramv1 b clean
scramv1 b -j 4
```

빌드가 끝나면 다음 명령들이 보여야 합니다.

```bash
command -v combine
command -v text2workspace.py
command -v combineTool.py
command -v plotImpacts.py
combine --version
```

명령 하나라도 나오지 않으면 워크플로우를 실행하지 말고 Combine 빌드와
`cmsenv`부터 확인하십시오.

### 2. 이 저장소와 Python 패키지 준비: 최초 1회

CMSSW의 `src` 아래에 저장소를 복제합니다. 이미 복제했다면 `git clone`은
건너뜁니다.

```bash
cd "$CMSSW_BASE/src"
git clone https://github.com/resisov/monotop-stat-tools.git
cd monotop-stat-tools
```

CMSSW의 ROOT/Python 환경을 유지하면서 분석용 Python 패키지를 격리하기
위해 `--system-site-packages` 가상환경을 만듭니다.

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install \
  cloudpickle coffea hist lz4 numpy pandas matplotlib mplhep scipy uproot
```

설치 확인:

```bash
python3 -c "import coffea, hist, mplhep, scipy, uproot; print('Python packages: OK')"
command -v combine
python3 run_simple.py --help
```

### 3. 새 셸을 열 때마다 환경 활성화

최초 설치는 반복하지 않습니다. 새로 로그인하거나 새 셸을 열 때마다
반드시 **CMSSW를 먼저**, Python 가상환경을 나중에 활성화합니다.

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh
cd /path/to/CMSSW_14_1_0_pre4/src
cmsenv

cd monotop-stat-tools
source .venv/bin/activate
```

아래 네 줄이 모두 경로를 출력하면 실행 환경이 준비된 것입니다.

```bash
command -v python3
command -v combine
command -v text2workspace.py
command -v plotImpacts.py
```

CMSSW 방식에서는 Combine 명령이 이미 `PATH`에 있으므로
`--combine-prefix`를 사용하지 않습니다.

### 4. `.scaled` 입력 파일 배치

저장소 루트에서 입력 디렉터리를 만들고 파일을 복사하거나 심볼릭 링크로
연결합니다. `inputs/`와 `.scaled` 파일은 Git에 올라가지 않습니다.

```bash
cd "$CMSSW_BASE/src/monotop-stat-tools"
mkdir -p inputs

cp /path/to/hadmonotop2022_0802.scaled inputs/
cp /path/to/hadmonotop2022EE_0802.scaled inputs/
cp /path/to/hadmonotop2023_0802.scaled inputs/
cp /path/to/hadmonotop2023BPix_0802.scaled inputs/
```

파일을 복사하지 않으려면 실행 시 절대경로를 `--input`으로 넘겨도 됩니다.
명령행의 `--input`은 JSON 설정의 `input`보다 우선합니다.

```bash
ls -lh inputs/*.scaled
```

### 5. 분석 설정 확인

현재 Run 3 설정은 다음 네 파일에 있습니다.

- `config/analysis_2022preEE.json`: 7.99 fb⁻¹, `inputs/hadmonotop2022_0802.scaled`
- `config/analysis_2022EE.json`: 26.68 fb⁻¹, `inputs/hadmonotop2022EE_0802.scaled`
- `config/analysis_2023.json`: 17.96 fb⁻¹, `inputs/hadmonotop2023_0802.scaled`
- `config/analysis_2023BPix.json`: 9.68 fb⁻¹, `inputs/hadmonotop2023BPix_0802.scaled`

설정 파일의 상대 입력 경로는 **저장소 루트가 아니라 설정 파일이 있는
`config/` 디렉터리 기준**으로 해석됩니다. 예를 들어
`../inputs/file.scaled`는 저장소의 `inputs/file.scaled`를 뜻합니다.

새 era를 추가할 때는 기존 JSON을 복사한 뒤 최소한 다음 값을 확인합니다.

- `era`, `luminosity_fb`, `input`, `histogram`
- `benchmark_signal`: 입력 파일에 실제로 존재하는 시그널 이름
- `nuisances`의 `lumi_<era>` 값
- region별 `data_streams`

명령행의 `--era`, `--lumi`, `--benchmark`, `--lumi-uncertainty`도 JSON 값을
덮어쓸 수 있습니다.

### 6. 쓰기 없는 사전 점검

본 실행 전에 `--dry-run`으로 설정과 실행 명령을 확인합니다. 이 단계는
출력 디렉터리를 만들지 않고 Combine 계산도 수행하지 않습니다.

```bash
python3 run_simple.py \
  --config config/analysis_2022preEE.json \
  --output outputs/2022preEE_0802 \
  --workers 4 \
  --dry-run
```

다음 항목을 확인하십시오.

- 출력된 `input`이 의도한 `.scaled` 파일의 절대경로인지
- `era`와 `luminosity_fb`가 맞는지
- `benchmark_signal`이 맞는지
- 단계 순서가 `build -> plots -> limits -> interpolation -> impacts -> validate`인지

### 7. 전체 워크플로우 실행

각 era는 서로 다른 출력 디렉터리에 순서대로 실행합니다. 아래 네 실행이 모두
끝나야 2022+2023 결합으로 넘어갈 수 있습니다.

```bash
python3 run_simple.py \
  --config config/analysis_2022preEE.json \
  --output outputs/2022preEE_0802 \
  --workers 4

python3 run_simple.py \
  --config config/analysis_2022EE.json \
  --output outputs/2022EE_0802 \
  --workers 4

python3 run_simple.py \
  --config config/analysis_2023.json \
  --output outputs/2023_0802 \
  --workers 4

python3 run_simple.py \
  --config config/analysis_2023BPix.json \
  --output outputs/2023BPix_0802 \
  --workers 4
```

기본 `--shell-mode all`은 on-shell과 off-shell을 signed shell 좌표로 연결한
통합 질량평면을 만듭니다. 분리된 진단 플롯도 필요하면 limit 계산 결과를
재사용해 보간 단계만 추가 실행합니다.

```bash
python3 run_simple.py \
  --config config/analysis_2022EE.json \
  --output outputs/2022EE_0802 \
  --stages interpolation \
  --shell-mode on-shell-only

python3 run_simple.py \
  --config config/analysis_2022EE.json \
  --output outputs/2022EE_0802 \
  --stages interpolation \
  --shell-mode off-shell-only
```

통합·on-shell·off-shell 플롯과 `mX=200 GeV` Brazil 플롯까지 한 번에 만드는
publication bundle이 필요하면 다음 보조 실행기를 사용할 수 있습니다.

```bash
python3 workflow/run_all.py \
  --config config/analysis_2022EE.json \
  --output outputs/2022EE_0802 \
  --workers 4
```

### 8. 2022+2023 데이터카드와 expected limit 결합

네 era에 모두 존재하는 시그널 질량점만 골라 데이터카드를 결합합니다. 현재
설정의 적분휘도 합은 62.31 fb⁻¹입니다. 이 결합 단계는 impact를 실행하지
않습니다.

```bash
python3 workflow/combine_eras.py \
  --input 2022preEE=outputs/2022preEE_0802 \
  --input 2022EE=outputs/2022EE_0802 \
  --input 2023=outputs/2023_0802 \
  --input 2023BPix=outputs/2023BPix_0802 \
  --output outputs/Run3_2022_2023_0802

python3 workflow/run_limits.py \
  --output outputs/Run3_2022_2023_0802 \
  --workers 4
```

통합 및 on-shell 플롯에 CMS Run-2 observed contour를 겹치려면 저장소에
포함된 기준 CSV를 명시합니다.

```bash
python3 workflow/interpolate_limits.py \
  --output outputs/Run3_2022_2023_0802 \
  --subdirectory interpolation_run2_overlay \
  --shell-mode all \
  --run2-observed-contour external/run2/cms_sus_23_004_vector_observed.csv

python3 workflow/interpolate_limits.py \
  --output outputs/Run3_2022_2023_0802 \
  --subdirectory interpolation_on_shell_run2_overlay \
  --shell-mode on-shell-only \
  --run2-observed-contour external/run2/cms_sus_23_004_vector_observed.csv
```

Run-2 결과는 on-shell 해석이므로 `off-shell-only` 플롯에는 중첩하지
않습니다. 옵션을 넘기더라도 코드가 Run-2 선을 의도적으로 그리지 않고 그
이유를 `interpolation_summary.json`에 기록합니다.

### 9. 실행이 끝났는지 확인

`run_simple.py`가 성공하면 마지막에 `workflow_summary.json` 경로를
출력합니다.

```bash
python3 workflow/validate_outputs.py --output outputs/2022EE_0802
```

`Validation status: ok`가 나와야 합니다. 엄격한 검증 스크립트는 통합,
on-shell-only, off-shell-only와 Brazil 플롯을 모두 검사하므로, 파일이
없다는 메시지가 나오면 바로 앞의 `workflow/run_all.py`를 실행하십시오.

## 중단 후 재개와 선택 실행

같은 설정, 입력, 출력으로 명령을 다시 실행하면 완성된 산출물을 재사용합니다.
입력 SHA-256이 바뀌면 build 캐시를 사용하지 않고 이후 Combine 결과도 다시
계산합니다.

```bash
# 기존 결과를 가능한 한 재사용
python3 run_simple.py \
  --config config/analysis_2022EE.json \
  --output outputs/2022EE_0802

# 선택한 단계만 강제로 다시 계산
python3 run_simple.py \
  --config config/analysis_2022EE.json \
  --output outputs/2022EE_0802 \
  --stages limits interpolation impacts validate \
  --force
```

`--stages`로 앞 단계를 생략하려면 해당 출력 디렉터리에 필요한 선행 산출물이
이미 있어야 합니다. 다른 설정이 기록된 출력 디렉터리를 재사용하지 마십시오.

## 생성되는 결과

각 era 출력 디렉터리의 주요 파일은 다음과 같습니다.

```text
analysis_config.json                 실제 실행에 사용한 확정 설정
manifest.json                        입력 SHA-256, 채널, 프로세스, 시그널 목록
transfer_factors.csv/json            pass/fail 트랜스퍼 팩터
plots/transfer_factors/              트랜스퍼 팩터 플롯 8개
plots/regions/                       SR/CR pass/fail yield 플롯 16개
templates/templates.root             Combine ROOT 템플릿
datacards/                           질량점별 데이터카드
workspaces/                          질량점별 Combine workspace
limits/limits.csv/json/root          blinded expected limit 표와 ROOT 결과
interpolation/                       통합 질량평면과 보간 격자
interpolation_on_shell_only/         on-shell 전용 결과
interpolation_off_shell_only/        off-shell 전용 결과
interpolation_run2_overlay/           Run-2 observed를 중첩한 통합 질량평면
interpolation_on_shell_run2_overlay/  Run-2 observed를 중첩한 on-shell 질량평면
impacts/                             공식 impact PDF와 상위 nuisance 요약
workflow_summary.json                단계별 실행 및 검증 상태
```

현재 2D expected-limit 플롯은 다음 표현을 사용합니다.

- 수평축 `mV`: 200–2500 GeV
- 수직축 `mX`: 50–1250 GeV
- 컬러바: `log10(r)`, 범위 -1.5–1.5, 반전된 `viridis_r`
- median expected `r=1`: 원색 빨강 실선
- expected ±1σ: 원색 빨강 점선
- 불확실성 채움 영역 없음
- 모델 표기: Vector mediator, `g_q = 0.25`, `g_DM = 1.0`
- relic-density 표기: `Omega_nbm h^2 = 0.12`
- 선택적 Run-2 observed 중첩: 파랑 실선과 흰색 외곽선
- 입력 질량점의 변환된 convex hull 밖은 외삽하지 않으므로 흰색으로 표시

### Run-2 observed contour의 출처와 해석 범위

기본 참조선은 CMS-SUS-23-004, JHEP 09 (2025) 141의 Figure 7-a에 실린
138 fb⁻¹ Run-2 observed 95% CL exclusion입니다. 현재 분석과 같은 vector
mediator, `g_q=0.25`, `g_DM=1.0` 설정이며 on-shell 영역만 대상으로 합니다.

- 좌표: `external/run2/cms_sus_23_004_vector_observed.csv`
- 출처와 추출 기록: `external/run2/cms_sus_23_004_vector_observed.json`
- CMS 결과 페이지: <https://cms-results.web.cern.ch/cms-results/public-results/publications/SUS-23-004/>
- HEPData: <https://www.hepdata.net/record/ins2904618>

HEPData Table 20은 `g_q=0.5` 대안 시나리오이므로 nominal 중첩에 사용하지
않았습니다. CSV는 공식 Figure 7-a PDF의 solid observed 벡터 경로에서
추출했으며 PDF URL, SHA-256, 축 범위와 추출 방법을 JSON에 함께 기록합니다.
Run-3 빨강 선은 blinded **expected**이고 Run-2 파랑 선은 **observed**이므로
두 선의 차이를 단순한 적분휘도 향상으로만 해석하면 안 됩니다.

## 분석 모델과 보간

워크플로우는 다음 모델을 구성합니다.

1. `TvsQCD`를 top-fail(`0 <= score < 0.33`)과
   top-pass(`0.33 <= score <= 1`)로 나눕니다.
2. 하드로닉 recoil을 `[350, 400, 500, 600, 700, 1000] GeV`로 리비닝하고
   overflow를 마지막 빈에 포함합니다.
3. pass/fail별 SR/CR 트랜스퍼 팩터와 전파된 MC 통계 불확도를 계산합니다.
4. ROOT 템플릿과 각 시그널 질량점의 Combine 데이터카드를 생성합니다.
5. 항상 `--run blind`인 `AsymptoticLimits`로 expected limit을 계산합니다.
6. `log10(r95)`를 질량점의 변환된 convex hull 안에서만 보간합니다.
7. 설정한 벤치마크에서 background-only Asimov impact를 계산합니다.

on-shell은 `(mV, beta_chi)`, off-shell은 `(mV, kappa_chi)` 좌표를 사용합니다.

```text
beta_chi  = sqrt(1 - (2*mX/mV)^2)       for mV > 2*mX
kappa_chi = sqrt((2*mX/mV)^2 - 1)       for mV < 2*mX
```

통합 평면은 on-shell에서 `+beta_chi`, off-shell에서 `-kappa_chi`, 정확한
경계에서 0인 signed shell 좌표를 사용해 `mV = 2*mX`에서 C0 연속으로
연결합니다.

nominal 모델은 80개의 단일 빈 채널로 구성됩니다: 8개 region × 2개 top
category × 5개 recoil 빈. Z, W, top normalization은 각 top category와
recoil 빈에서 독립적으로 float하며, 공통 `rateParam`이 관련 SR과 CR을
연결합니다.

현재 제공된 누산기에는 채워진 shape systematic 템플릿이 없습니다. 따라서
이 저장소는 background automatic MC statistics, normalization nuisance,
지정된 transfer-factor nuisance를 포함한 baseline nominal 모델입니다.
실험 및 이론 shape variation을 추가하기 전에는 논문 제출용 systematic
모델로 사용하면 안 됩니다.

모든 limit은 expected-only입니다. SR 데이터는 플롯에 표시하지 않으며,
impact fit에는 background-only Asimov 데이터셋을 사용합니다. 기록된 CR
데이터는 진단 플롯에 사용할 수 있습니다.

## CMSSW를 사용할 수 없는 경우: conda standalone

macOS나 일반 Linux에서는 저장소의 `environment-combine.yml`로 독립형
Combine 환경을 만들 수 있습니다.

```bash
conda env create -f environment-combine.yml
conda activate combine

git -c advice.detachedHead=false clone \
  --depth 1 \
  --branch v10.6.0 \
  https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit.git

cmake -S HiggsAnalysis-CombinedLimit \
  -B HiggsAnalysis-CombinedLimit/build \
  -DCMAKE_INSTALL_PREFIX="$CONDA_PREFIX" \
  -DCMAKE_INSTALL_PYTHONDIR=lib/python3.12/site-packages \
  -DUSE_VDT=OFF

cmake --build HiggsAnalysis-CombinedLimit/build -j 4
cmake --install HiggsAnalysis-CombinedLimit/build
```

이 방식으로 실행할 때는 다음처럼 prefix를 전달합니다.

```bash
python3 run_simple.py \
  --config config/analysis_2022EE.json \
  --output outputs/2022EE_0802 \
  --combine-prefix "$CONDA_PREFIX" \
  --workers 4
```

## 자주 발생하는 문제

### `CMS Combine was not found`

CMSSW 모드에서는 `cmsenv` 후 가상환경을 활성화했는지 확인합니다.

```bash
cd /path/to/CMSSW_14_1_0_pre4/src
cmsenv
cd monotop-stat-tools
source .venv/bin/activate
command -v combine
```

conda 모드에서는 환경을 활성화하고 `--combine-prefix "$CONDA_PREFIX"`를
전달합니다.

### `Input file does not exist`

JSON의 상대경로는 `config/` 기준입니다. 가장 확실한 진단 방법은
`--input /absolute/path/file.scaled --dry-run`으로 실제 절대경로를 확인하는
것입니다.

### `Output directory belongs to a different configuration`

다른 era 또는 다른 설정에 사용한 출력입니다. 새 `--output`을 지정하십시오.
기존 결과를 의도적으로 다시 만들 때만 `--force`를 사용합니다.

### 플롯에 흰 영역이 보임

오류가 아닐 수 있습니다. 이 워크플로우는 입력 질량점 바깥으로 외삽하지
않습니다. 흰 영역을 채우려면 물리적으로 타당한 새 시뮬레이션 질량점이
필요합니다.

## 개발자 검사

코드를 수정한 뒤 다음 검사를 실행합니다.

```bash
PYTHONPYCACHEPREFIX=/tmp/monotop-pycache \
  python3 -m compileall -q run_simple.py workflow tests
python3 -m unittest discover -s tests -v
git diff --check
```

## 저장소 구조

```text
run_simple.py                         재개 가능한 표준 올인원 CLI
config/                               era별 이식 가능한 분석 설정
workflow/build_model.py               scaled -> TF, 템플릿, 데이터카드
workflow/run_limits.py                병렬 blinded expected limit
workflow/limit_interpolation.py       threshold-aware 보간 공용 함수
workflow/interpolate_limits.py        2D 보간과 질량평면 플롯
workflow/plot_brazil_limit.py         고정 mX의 1D Brazil 플롯
workflow/combine_eras.py              여러 era의 공통 질량점 데이터카드 결합
workflow/run_impacts.py               blinded benchmark impact
workflow/validate_outputs.py          전체 산출물 엄격 검증
external/relic_densities/             relic-density 참조 입력
external/run2/                        CMS Run-2 observed contour와 출처 메타데이터
tests/                                워크플로우 및 보간 회귀 테스트
```

입력 파일, 생성된 출력, 로그, 배포용 아카이브는 Git에서 제외합니다.
저장소에는 워크플로우 코드, 설정, relic-density 참조 자료, 테스트와 문서만
게시합니다.
