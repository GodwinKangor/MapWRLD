# Blender Modeling Modules

These modules are the shared building blocks for code-driven campus detailing.

- `roof_module.py`: flat, gable/prism, and hip/prism roof primitives with reference metadata.
- `reference_module.py`: selects approved/best references and creates scaled elevation boards/JSON for model modules.
- `window_module.py`: window opening plans that become wall faces, not floating panels.
- `door_module.py`: door opening plans that become wall faces, not floating panels.
- `major_wall_detail_module.py`: quad wall grids with integrated window/door cells and wall-reference links.
- `chimney_tower_module.py`: supported chimneys and tiered towers/cupolas.
- `staircase_module.py`: exterior stair blocks tied to references.
- `symmetry_module.py`: mirrored positions and count checks.
- `inspect_module.py`: topology and metadata checks for generated objects.

Every generated detail should carry:

- `mwrld_detail_for`
- `mwrld_module`
- `mwrld_reference`
- `mwrld_wall_id` when the detail belongs to a named exterior wall

Modeling scripts should still run `model:dartmouth:audit-laws` and inspect preview renders before a building is considered ready.
