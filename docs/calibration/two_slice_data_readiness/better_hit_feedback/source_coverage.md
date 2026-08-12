authority: non_authoritative_derived_presentation

# BetterHitFeedback reference-assisted positive calibration material

## Request

Read the exact UTF-8 request in `request.txt`. Its SHA256 is `975612665FF3779774E09D189D1C7877E31E34B5E924C07D0E1CD2050E005187`.

The operator-confirmed requirement boundary is: one independent stagger event displays one yellow X and plays one prompt sound; a later independent stagger event may produce feedback again.

## Allowed corpus

- Canonical corpus owner: `src/mod_agent/evaluation/arm_a.py::RunManifestCollector.canonical_corpus_snapshot`.
- Runtime locator: operator-supplied `--r8-root`.
- Search-root allowlist: `Assets/Scripts/Modules-ASM`, `Datablocks`.
- Expected snapshot: 3,196 files, `sha256:40ed82c420c7192f64c539cc983c40aae7e1a8fe221e0c2cd0e31964ace26ba2`.
- Historical implementations, Golden annotation, project/queue documents, tests with fixed answers, prior Agent/RAG output, and answer-explaining reports are outside the allowlist.

## Current physical facts

The included R8 files declare `ES_Hitreact.ActivateState`, `ES_Hitreact.DoHitReact`, `Dam_EnemyDamageBase.BulletDamage`, and distinct `Light`, `Heavy`, `ToDeath`, and `InstantRagdollDeath` reaction values.

Current interop assembly:

- SHA256: `B0127EB1E9228A61B7ED04EA0152348E24DA693636711D03A248049618BB74BB`
- MVID: `85155e68-33a5-4fa5-a419-c563e7ea5e60`

| Method | Token | Signature | Body |
| --- | --- | --- | --- |
| `ES_Hitreact.ActivateState` | `0x06001387` | `2006011184301184340212B9DC11511186F8` | present |
| `ES_Hitreact.DoHitReact` | `0x0600138A` | `200701081184301184340C0211511151` | present |
| `Dam_EnemyDamageBase.BulletDamage` | `0x060023B4` | `200A010C12B9DC11511151115102080C0C09` | present |
| `Enemies.EnemyAgent.OnTakeDamage` | `0x0600F223` | `2005010C12B9DC11511151118430` | present |

The hash-bound historical implementation uses `ES_Hitreact.ActivateState` with the exact six-parameter Hook signature and limits its selected reactions to Micro, Light, and Heavy with a locally owned player source check. It is reference support and remains excluded from actual retrieval.

The hash-bound instrumented Runtime logs recompute to 4/18 `ActivateState` result markers and 2/14 `BulletDamage` input markers in the bounded/full logs. The result markers include Light and Heavy plus successful visual/audio marker predicates.

## Sufficiency scope and Runtime limitations

The combined current API/IL, historical implementation, and bounded Runtime facts support selecting `ES_Hitreact.ActivateState` as the observation direction and entering implementation planning. They do not complete Runtime acceptance.

Planning and Runtime verification must still resolve:

1. whether one independent reaction produces multiple qualifying calls;
2. the required event boundary or deduplication mechanism;
3. whether later independent reactions still produce feedback;
4. complete death-path and other boundary regression;
5. final player-visible and audible Runtime correctness.

No individual method-existence, method-body, implementation, or Runtime-marker fact mechanically determines the technical annotation.
