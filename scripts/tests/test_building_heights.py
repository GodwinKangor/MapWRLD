import importlib.util
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load('height_collector', 'scripts/reference-tools/collect-building-heights.py')
combiner = load('campus_combiner', 'scripts/blender/combine-campus-glbs.py')


class BuildingHeightTests(unittest.TestCase):
    def test_interior_samples_exclude_holes_and_outside_surface(self):
        extent = {'xmin':-72.29,'ymin':43.70,'xmax':-72.289,'ymax':43.701}
        ring = [[-72.29,43.70],[-72.289,43.70],[-72.289,43.701],[-72.29,43.701],[-72.29,43.70]]
        hole = [[-72.2896,43.7004],[-72.2894,43.7004],[-72.2894,43.7006],[-72.2896,43.7006],[-72.2896,43.7004]]
        surface = np.full((50,50),9.0)
        surface[20:30,20:30] = 50  # A courtyard tree must not become building height.
        stats = collector.sample({'type':'Polygon','coordinates':[ring,hole]},surface,extent)
        self.assertTrue(stats['accepted'])
        self.assertEqual(stats['heightMeters'],9)
        self.assertEqual(stats['p90Meters'],9)

    def test_no_data_and_variable_surface_are_rejected(self):
        geometry = {'type':'Polygon','coordinates':[[[0,0],[.001,0],[.001,.001],[0,.001],[0,0]]]}
        extent = {'xmin':0,'ymin':0,'xmax':.001,'ymax':.001}
        self.assertFalse(collector.sample(geometry,np.full((30,30),np.nan),extent)['accepted'])
        noisy = np.tile(np.linspace(3,30,30),(30,1))
        self.assertEqual(collector.sample(geometry,noisy,extent)['reason'],
                         'variable_surface_possible_trees_or_complex_roof')

    def test_osm_height_units_and_invalid_input(self):
        self.assertEqual(collector.parse_height('30 ft'),9.14)
        self.assertEqual(collector.parse_height('21.64 m'),21.64)
        self.assertIsNone(collector.parse_height('unknown'))
        self.assertIsNone(collector.parse_height('-20'))

    def test_vertical_transform_keeps_base_and_footprint_fixed(self):
        source = {'scene':0,'scenes':[{'nodes':[0]}],
                  'nodes':[{'mesh':0,'translation':[0,5,0]}],
                  'meshes':[{'primitives':[{'attributes':{'POSITION':0}}]}],
                  'accessors':[{'min':[-10,0,-15],'max':[10,20,15]}]}
        meta = {'dimensions':{'z':20},'generatedDetails':0}
        record = {'heightMeters':12,'modelFootprintAligned':True,'method':'lidar_estimate','sourceUrl':'test'}
        adjustment, status = combiner.height_adjustment(meta,source,record)
        self.assertEqual(status,'applied')
        bottom = combiner.transform_point(adjustment,[-10,5,-15])
        top = combiner.transform_point(adjustment,[10,25,15])
        self.assertEqual(bottom,[-10,5,-15])
        self.assertAlmostEqual(top[1]-bottom[1],12)
        self.assertEqual((top[0],top[2]),(10,15))
        self.assertEqual(combiner.height_adjustment({**meta,'generatedDetails':1},source,record)[1],
                         'preserved_detailed_geometry')
        self.assertEqual(combiner.height_adjustment(meta,source,{**record,'modelFootprintAligned':False})[1],
                         'model_footprint_identity_mismatch')


if __name__ == '__main__':
    unittest.main()
