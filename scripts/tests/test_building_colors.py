import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('style_campus', ROOT/'scripts/blender/style-campus-glb.py')
style = importlib.util.module_from_spec(spec)
spec.loader.exec_module(style)


class BuildingColorTests(unittest.TestCase):
    def test_styling_preserves_geometry_and_existing_vertex_data(self):
        folder = ROOT/'public/models/dartmouth-campus'
        for name in ['dartmouth-campus','dartmouth-evidence']:
            with self.subTest(asset=name):
                source, before = style.read_glb(folder/(name+'.glb'))
                styled, after = style.read_glb(folder/(name+'-styled.glb'))
                self.assertEqual(before,after[:len(before)])
                self.assertEqual(source['nodes'],styled['nodes'])
                self.assertEqual(source['scenes'],styled['scenes'])
                self.assertEqual(source['accessors'],styled['accessors'][:len(source['accessors'])])
                for before_mesh,after_mesh in zip(source['meshes'],styled['meshes']):
                    for a,b in zip(before_mesh['primitives'],after_mesh['primitives']):
                        self.assertEqual(a.get('indices'),b.get('indices'))
                        self.assertEqual(a.get('mode'),b.get('mode'))
                        for key,index in a['attributes'].items():
                            self.assertEqual(index,b['attributes'][key])

    def test_scoped_reference_materials_match_photos_in_both_assets(self):
        folder = ROOT/'public/models/dartmouth-campus'
        records = json.loads((ROOT/'data/building-reference-colors.json').read_text())['buildings']
        for name in ['dartmouth-campus','dartmouth-evidence']:
            gltf,_ = style.read_glb(folder/(name+'-styled.glb'))
            matched = 0
            for material in gltf['materials']:
                if '::reference::' not in material.get('name',''):
                    continue
                base,osm_id = material['name'].split('::reference::')
                colors = records[osm_id]['materialColors']
                suffix = next(k for k in sorted(colors,key=len,reverse=True) if base.endswith(k))
                np.testing.assert_allclose(material['pbrMetallicRoughness']['baseColorFactor'][:3],
                                           style.srgb_to_linear(colors[suffix]),atol=1e-6)
                matched += 1
            self.assertGreater(matched,0)

    def test_unreliable_reference_matches_are_not_applied(self):
        report = json.loads((ROOT/'public/models/dartmouth-campus/building-color-report.json').read_text())
        records = {r['osmId']:r for r in report['buildings']}
        self.assertTrue(records['way/261793901']['applied'])  # McNutt has clear, aligned references.
        self.assertFalse(records['way/785657748']['applied'])  # Main house is obscured.
        self.assertFalse(records['way/48466712']['applied'])  # Identity/geometry mismatch.


if __name__ == '__main__':
    unittest.main()
