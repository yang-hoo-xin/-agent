authority: non_authoritative_derived_presentation

# WallCrawler bounded-search evidence material

## Request boundary

Read the exact UTF-8 request in `request.txt`. Its SHA256 is `B60BF872F06F8772B5D558629A1179A5D3E7C5E8CC463CEA33514596088B6F0A`.

The request requires selected enemies to crawl on walls and ceilings only in configured areas while retaining normal AI movement, turning, actions, and attacks. Ceiling traversal uses a prone pose and is limited to enemies already supporting prone locomotion.

The user-provided reference clue is preserved exactly as `bep/plugins/xxxrundowns/.json`. It is an investigation lead only. Its real path, filename pattern, JSON format, and field structure have not been verified and are not inferred here. Ladder logic is also an implementation hint, not a required mechanism.

## Current physical facts

- Search-root allowlist: `Assets/Scripts/Modules-ASM`, `Datablocks`.
- Expected canonical snapshot: 3,196 files, `sha256:40ed82c420c7192f64c539cc983c40aae7e1a8fe221e0c2cd0e31964ace26ba2`.
- R8 `Modules-ASM.dll` SHA256: `DD0C57D5C527E78B40FAB798456EDD73413DA0F140995A63FCA3619C36C32698`.
- MVID: `28e7d845-eb8b-48af-a5b2-9b1addb278ae`.
- The 11 fixed files are verified directly against `R8_EXPECTED_SHA256`.

| Method | Token | Signature | Body fact |
| --- | --- | --- | --- |
| `ES_PathMove.CommonFixedUpdate` | `0x06000B8C` | `200001` | `IL 002A` (`nop; ret`) |
| `ES_PathMove.UpdateRotation` | `0x06000B8E` | `200001` | `IL 002A` (`nop; ret`) |
| `ES_PathMoveBase.UpdateRotation` | `0x06000B93` | `200001` | abstract, RVA `0`, no body |

All three exact symbols were found, but their bodies establish `searched_and_absent_behavioral_semantics`, not `not_found`. Product readiness, `can_generate_patch`, blocker codes, and prior Agent/RAG output remain non-authoritative.

The bound R8 sources also expose `ES_ClimbLadder` start position, end position, normal, move target, and `OffMeshLink` fields; `EnemyLocomotion` exposes `PathMove`, `ClimbLadder`, `EnemyCrawlFlip`, and `EnemyCrawl`; course-node, zone, area, and layout declarations expose structural identities. These are bounded investigation leads only. They do not prove that the requested movement, AI, animation, attack, and configuration capabilities compose.

## Evidence gaps for independent technical review

1. arbitrary-surface movement rather than only a fixed ladder route;
2. wall/ceiling acquisition and usable surface normals;
3. movement and turning in a surface-relative coordinate frame;
4. integration with the existing AI rather than complete takeover or pause;
5. a JSON area-configuration entry point and runtime area binding;
6. default prohibition for unconfigured, unknown, or parse-failed areas;
7. reliable identification of enemies supporting a prone locomotion pose;
8. positive integration evidence that the mechanism does not inherently replace or disable normal attack state transitions.

This material does not disclose or decide the provisional annotation, its hash, or a continue/block outcome.

## Later planning-stage details

Planning or implementation may separately validate the exact wall/floor/ceiling transition algorithm, animation transition timing, attack-pose and hitbox tuning, collision parameters, concrete JSON field structure, per-enemy compatibility, and final Runtime behavior and visuals. These details are non-authoritative here and do not expand the judgment schema.
