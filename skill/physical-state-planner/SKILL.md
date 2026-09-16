---
name: physical-state-planner
description: Create concise, dataset-agnostic physical state plans from video prompts. Use when Codex needs to decompose a prompt, optional physical hints, or optional evaluation questions into scene objects, semantic keyframes, transitions, causal constraints, must-show requirements, and must-avoid failures before any video, Blender, simulation, or animation implementation.
---

# Physical State Planner

## Purpose

Use this skill to turn a video prompt into a lightweight physical process plan.
The output is an implementation-neutral sequence of semantic keyframes and
transitions for later Coder, Blender, simulation, or audit agents.

Keep the physical plan free of Blender code, implementation primitives, solver
settings, render commands, and exact frame numbers. Those belong to the later
implementation stage.

## Inputs

Accept these fields when available:

- `prompt` required: the video description.
- `physics_hints` optional: physical laws, category labels, domain notes.
- `eval_hints` optional: questions, middle-frame requirements, final-frame checks.
- `dataset_metadata` optional: dataset name, category, subcategory, index.

If a field is missing, continue from the prompt and record needed assumptions.

## Workflow

1. Extract the core physical event from the prompt:
   - transfer, heating, cooling, melting, boiling, freezing, mixing, dissolving,
     reacting, burning, breaking, colliding, deforming, falling, floating,
     spreading, separating, or settling.

2. Identify scene objects:
   - `initial_objects`: visible before the event begins.
   - `process_objects`: visible only after the trigger or during evolution.
   - `final_objects_or_states`: final products, layers, colors, damage,
     deformation, phase state, or arrangement.

3. Create semantic keyframes:
   - Use 4-5 keyframes by default: `K0` initial, `K1` onset, `K2` middle
     process, optional `K3` late process, `K4` final.
   - Use 4 keyframes for simple events and 5 keyframes for most material or
     physical transformations. Use 6 only when a distinct intermediate state is
     physically necessary. Do not exceed 6 keyframes.
   - Use `time_hint` as a rough percentage such as `0%`, `20%`, `50%`, `75%`,
     and `100%`; do not choose exact implementation frames.
   - For each keyframe, describe the visible state, the physical state, and
     what must not be visible yet.
   - Make neighboring keyframes visibly distinct. Do not put the same change
     in both onset and middle keyframes.

4. Create transitions between keyframes:
   - For every adjacent pair, state the cause and the continuous change.
   - Include `should_not_jump` items that would make the transition look
     discontinuous or physically uncaused.
   - Describe where the effect originates when relevant, such as heat source,
     contact boundary, impact point, liquid source, reaction interface, or
     applied force.
   - Make each transition answer these questions when applicable:
     `origin`: where does the visible change start?
     `direction`: where does it move, spread, shrink, rise, fall, or propagate?
     `material_source`: where does the new visible material, color, phase, or
     damage come from?
     `continuity`: what visible quantity should change smoothly instead of
     jumping?
   - Avoid generic transition text such as "the object gradually changes" unless
     it names the origin, direction, and visible continuous change.

5. Write lightweight causal constraints:
   - Use simple before/after constraints.
   - Focus on preventing result states from appearing before their causes.
   - Include contact-before-reaction, heat-before-phase-change,
     accumulation-before-final-layer, force-before-deformation, or
     trigger-before-damage when relevant.

6. Extract visual requirements:
   - `must_show`: prompt-critical objects, intermediate states from eval hints,
     and final outcomes.
   - `must_avoid`: likely failure modes such as premature result appearance,
     missing contact, sudden geometric products, homogeneous mixing when
     separation is required, or wrong final arrangement.

7. Record uncertain assumptions:
   - Mark assumptions that are needed to plan the physics but are not explicit
     in the input.
   - Do not present assumptions as confirmed facts.

## Output Schema

Write the physical plan as JSON with this shape:

```json
{
  "physical_intent": "",
  "scene": {
    "environment": "",
    "initial_objects": [],
    "process_objects": [],
    "final_objects_or_states": []
  },
  "semantic_keyframes": [
    {
      "id": "K0",
      "time_hint": "0%",
      "visible_state": "",
      "physical_state": "",
      "must_not_show": []
    },
    {
      "id": "K1",
      "time_hint": "20%",
      "visible_state": "",
      "physical_state": "",
      "must_not_show": []
    },
    {
      "id": "K2",
      "time_hint": "50%",
      "visible_state": "",
      "physical_state": "",
      "must_not_show": []
    },
    {
      "id": "K3",
      "time_hint": "75%",
      "visible_state": "",
      "physical_state": "",
      "must_not_show": []
    },
    {
      "id": "K4",
      "time_hint": "100%",
      "visible_state": "",
      "physical_state": "",
      "must_not_show": []
    }
  ],
  "transitions": [
    {
      "from": "K0",
      "to": "K1",
      "cause": "",
      "continuous_change": "",
      "should_not_jump": []
    }
  ],
  "causal_constraints": [
    {
      "before": "",
      "after": "",
      "reason": ""
    }
  ],
  "must_show": [],
  "must_avoid": [],
  "uncertain_assumptions": []
}
```

## Planning Rules

- Keep the plan short enough for downstream agents to follow.
- Prefer 4-5 semantic keyframes; use 6 only for genuinely complex physical
  processes.
- Prefer physical states over visual tricks.
- Do not decide implementation primitives such as sphere, cylinder, mesh,
  shader, particle system, or keyframe timing.
- Do not overfit to one dataset's field names.
- Treat evaluation hints as ordering or visibility hints when present, but keep
  the schema dataset-agnostic.
- A final state may be visually simple, but its prerequisites must appear in
  either `transitions` or `causal_constraints`.
- The transition text should be directly usable by a Coder agent and directly
  auditable from extracted preview frames.
- A transition is incomplete if it does not say where the effect starts or how
  it remains visually connected to the previous keyframe.

## Anti-Patterns To Catch

Include likely anti-patterns in `must_avoid` or transition `should_not_jump`:

- Result appears before trigger.
- Contact/reaction/color change happens before contact.
- Phase change appears before heating or cooling.
- Final layer, pool, crack, flame, bubble, stain, or product appears suddenly.
- Motion reads as a rigid geometric symbol when the prompt implies a material
  process.
- The final frame is correct but the middle process is physically missing.
- An effect appears far from its physical origin without a connecting path.

## Examples

Read `references/oil-water-layering.json` for a compact example.
