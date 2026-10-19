import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('combiner', ROOT/'scripts/blender/combine-campus-glbs.py')
combiner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(combiner)


class CampusSubsetTests(unittest.TestCase):
    def test_evidence_asset_preserves_geometry_and_only_includes_evidence_roots(self):
        campus = ROOT/'public/models/dartmouth-campus'
        source, binary = combiner.read_glb(campus/'dartmouth-campus.glb')
        subset, compact = combiner.read_glb(campus/'dartmouth-evidence.glb')
        evidence = json.loads((ROOT/'data/energy-evidence.json').read_text())
        wanted = {'part::'+name for b in evidence['buildings'].values() for name in b['twinObjects']}
        original = {source['nodes'][i]['name']:i for i in source['scenes'][0]['nodes']}
        kept = {subset['nodes'][i]['name']:i for i in subset['scenes'][0]['nodes']}
        self.assertEqual(set(kept),wanted & original.keys())
        self.assertLess(len(subset['nodes']),len(source['nodes']))
        self.assertLess(len(compact),len(binary))
        for name,index in kept.items():
            before = {**source,'scene':0,'scenes':[{'nodes':[original[name]]}]}
            after = {**subset,'scene':0,'scenes':[{'nodes':[index]}]}
            self.assertEqual(combiner.geometry_bounds(before),combiner.geometry_bounds(after),name)
        # Every retained buffer is byte-for-byte identical to a source view;
        # accessor remapping and buffer compaction must not alter mesh data.
        source_views = {binary[v.get('byteOffset',0):v.get('byteOffset',0)+v['byteLength']]
                        for v in source['bufferViews']}
        for view in subset['bufferViews']:
            start = view.get('byteOffset',0)
            self.assertIn(bytes(compact[start:start+view['byteLength']]),source_views)
        for accessor in subset['accessors']:
            self.assertLess(accessor['bufferView'],len(subset['bufferViews']))


if __name__ == '__main__':
    unittest.main()
