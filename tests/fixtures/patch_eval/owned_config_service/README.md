# OwnedConfigService single-task comparison input

This is newly authored MIT C# fixture code, independent of other Mod tasks. It
contains three source files, a JSON file store and a process CLI. No corrected
implementation or reference patch is included.

The baseline deliberately accepts every JSON value for `maxRetries`. The new
requirement is to accept only JSON integer tokens 0 through 5, reject seven
invalid input classes with exit code 2 and JSON `status=rejected`, and preserve
the existing configuration file byte-for-byte on rejection. Valid settings,
unknown keys/values, `serviceName`, independent process restart and malformed
JSON rejection must retain their behavior.

The fixed oracle has 15 checks: seven requested-change failures plus eight
preservation checks. It invokes the compiled application 23 times, always in a
fresh process, and inspects actual disk files and JSON stdout. It builds all
three BCL-only source files with the already established fixed .NET 7
`csc.dll`/reference-assembly approach; no NuGet restore or user NuGet config is
used. The fixed toolchain is SDK 7.0.401 / runtime and refs 7.0.11. This records
the available test environment, not a supported-production-runtime recommendation.

`prepare_owned_config_task(output_root=...)` in `behavior_evaluator.py` only
prepares inputs and verifies the baseline. It calls the existing FeatureSpec,
RgLive, formal Coverage, ImplementationPlanner, ArtifactStore and continuation
preflight owners. Findings and target selection are explicitly operator-authored
fixture inputs, with zero Fresh/model execution claims.

The output is a standard `continuation-input.json`, standard `worker.json`, a
task record, the baseline compile/process/matrix evidence, and an unapproved
source-disclosure preview. Use the existing `continue-fresh-patch` for a selected
local profile, or `run_external_patch_continuation` for an explicitly approved
external profile. No second model runner or Eval framework is provided.

Only the application `source` directory is model-readable. The oracle, compiler,
API keys and unrelated workspaces are excluded. The source manifest and MIT
license establish selected fixture data; they do not authorize uploading it.
The same Feature/Evidence/Plan and check set can be used for both interfaces;
each real attempt needs its own explicit profile, attempt ID and output location.
The same worker configuration may be reused for local and external comparisons:
oracle output is isolated by the existing model-response path identity, so new
attempts do not overwrite another run's matrix.

The expected baseline result is seven failing change checks and all eight
preservation checks passing. A failing compile/environment does not count as
passing preservation. A model's compiler error is reported separately from an
unavailable toolchain, and no behavior-matrix success is inferred from compilation.
This is one task for an initial comparison, not three-task qualification, hosted
CI, deployment, Apply or game Runtime evidence.
