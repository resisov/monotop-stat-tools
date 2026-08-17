# Hadronic monotop Run 3 statistical workflow

One command turns a Coffea `.scaled` histogram accumulator into transfer
factors, pass/fail control plots, CMS Combine datacards and workspaces, blinded
expected limits, nuisance-parameter impacts, and final plots.

## Quick start

Create the analysis environment and build CMS Combine as described below, then
run an era configuration:

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

The default stage order is:

```text
build -> plots -> limits -> interpolation -> impacts -> validate
```

The run is resumable. Repeating the same command reuses complete products. The
build cache is accepted only when the input SHA-256 matches, so changing a
`.scaled` file automatically invalidates downstream Combine products. Use
`--force` to recalculate everything explicitly.

Preview every command without requiring Combine or creating an output
directory:

```bash
python3 run_simple.py \
  --config config/analysis_2023.json \
  --input /path/to/hadmonotop2023_0702.scaled \
  --output outputs/2023 \
  --dry-run
```

Run only selected stages when their prerequisites already exist:

```bash
python3 run_simple.py \
  --config config/analysis_2023.json \
  --input /path/to/hadmonotop2023_0702.scaled \
  --output outputs/2023 \
  --stages build plots
```

The CLI can also generate the standard model without a JSON file:

```bash
python3 run_simple.py \
  --input /path/to/hadmonotop2023.scaled \
  --era 2023 \
  --lumi 17.96 \
  --combine-prefix "$CONDA_PREFIX"
```

Use `python3 run_simple.py --help` for benchmark, interpolation, uncertainty,
worker, and stage options.

## Analysis model

The workflow:

1. splits `TvsQCD` into top-fail (`0 <= score < 0.33`) and top-pass
   (`0.33 <= score <= 1`);
2. rebins hadronic recoil to `[350, 400, 500, 600, 700, 1000] GeV`, folding
   overflow into the last bin;
3. calculates SR/CR transfer factors and propagated MC statistical
   uncertainties separately in pass/fail;
4. writes ROOT templates and one Combine datacard per signal mass point;
5. evaluates blinded expected `AsymptoticLimits` and interpolates
   `log10(r95)` only inside the simulated mass-point convex hull;
6. evaluates background-only Asimov impacts for the configured benchmark;
7. renders transfer-factor, SR/CR, expected-limit, and impact plots and writes a
   machine-readable validation summary.

The nominal model has 80 one-bin channels: 8 regions × 2 top categories × 5
recoil bins. Z, W, and top normalizations float independently in each top
category and recoil bin, while shared `rateParam` values connect the relevant
signal and control regions. Nominal background groups are `top`, `wjets`,
`zjets`, `zll`, `gjets`, `diboson`, and `qcd`.

The supplied accumulators do not contain populated shape-systematic templates.
This repository therefore implements a baseline nominal model with background
automatic MC statistics, normalization nuisances, and assigned transfer-factor
nuisances. It is not a publication-ready systematic model until experimental
and theory shape variations are supplied.

All limit products are expected-only. `run_limits.py` always passes
`--run blind`; SR data are not drawn; and impact fits use a background-only
Asimov data set. Recorded CR data remain available for diagnostic plots.

## Products

Each output directory contains:

- `analysis_config.json` — fully resolved configuration;
- `manifest.json` — input hash, channels, processes, signals, and provenance;
- `transfer_factors.csv/json` and 8 pass/fail TF plots;
- `plots/regions/` — 16 SR/CR pass/fail yield plots;
- `templates/templates.root` and `datacards/`;
- `workspaces/`, `limits/limits.{csv,json,root}`, and raw Combine results;
- `interpolation/limit_interpolation.{png,pdf}` and grid files;
- `impacts/` — official Combine impact PDFs plus a top-20 summary;
- `workflow_summary.json` — selected stages, product paths, input SHA-256, and
  final validation status.

Inputs, generated outputs, logs, and deliverable archives are intentionally
ignored by Git. Only workflow code, portable configurations, the relic-density
reference, tests, and documentation are published.

## CMS Combine installation

CMS Combine v10 supports a standalone conda/CMake build:

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

The prefix must contain `bin/combine`, `bin/combineTool.py`,
`bin/text2workspace.py`, and `bin/plotImpacts.py`. It may be omitted when these
commands are already on `PATH`.

## Repository layout

```text
run_simple.py                 canonical all-in-one CLI
config/                       portable era configurations
workflow/build_model.py       scaled input -> TFs, templates, datacards
workflow/run_limits.py        parallel blinded expected limits
workflow/run_impacts.py       blinded benchmark impacts
workflow/interpolate_limits.py and plotting scripts
external/relic_densities/     reference contour input
tests/                        side-effect and provenance tests
```

Run the lightweight checks with:

```bash
PYTHONPYCACHEPREFIX=/tmp/monotop-pycache \
  python3 -m compileall -q run_simple.py workflow tests
python3 -m unittest discover -s tests -v
```
