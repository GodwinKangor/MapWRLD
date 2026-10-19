# Figure Modeling Loop

Run the Blender script from the repo root:

```bash
npm run model:figure
```

Outputs:

```text
public/models/figure/figure.blend
public/models/figure/figure.fbx
public/models/figure/figure.glb
public/models/figure/renders/clay.png
public/models/figure/renders/wireframe.png
```

Use `scripts/blender/blender-figure.py` as the editable source of truth. Codex can adjust proportions, add mesh parts, export again, and inspect the render previews after each change.
