"""Single-file STAC collections and optional source outages must not stop road streaming."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import blockworker
import mapcells
import mapdata
import netfetch
import overture
import roads
from test_roads import FRAME, LAT, LON, features
from test_blockworker import FakeDem


class StacLoadingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.url = f'{overture.STAC_ROOT}/test/buildings/building_part/collection.json'
        self.bbox = [-85, 41, -84, 42]
        self.item_url = self.url.replace('collection.json', '00000/00000.json')
        self.item = {'bbox': self.bbox, 'assets': {
            'aws': {'href': 'https://example.org/part.parquet', 'file:size': 123}}}
        self.collection = {'links': [{'rel': 'item', 'href': './00000/00000.json'}],
                           'extent': {'spatial': {'bbox': [self.bbox]}}}
        self.docs = {self.url: self.collection, self.item_url: self.item}
        self.fetcher = Mock()
        self.fetcher.get.side_effect = lambda url, **kw: SimpleNamespace(body=json.dumps(self.docs[url]).encode())
        self.idx = overture.StacIndex('test', self.root, self.fetcher)

    def files(self, bounds=None):
        return self.idx.files('buildings', 'building_part', bounds or self.bbox)

    def test_single_file_aggregate_is_valid_and_disk_cache_needs_no_clear(self):
        # Exactly the screenshot's format; populate the same old raw cache first.
        path = Path(self.idx._dir('buildings', 'building_part'), 'collection.json')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(self.collection))
        self.assertEqual(self.files(), [('part.parquet', ['https://example.org/part.parquet'], 123)])
        self.assertEqual(self.fetcher.get.call_count, 1)  # item only, collection reused
        self.idx = overture.StacIndex('test', self.root, self.fetcher)
        self.files()
        self.assertEqual(self.fetcher.get.call_count, 1)  # both now cached

    def test_aggregate_outside_query_does_not_fetch_items(self):
        self.assertEqual(self.files([0, 0, 1, 1]), [])
        self.assertEqual(self.fetcher.get.call_count, 1)

    def test_multi_item_aggregate_filters_by_each_item_box(self):
        far_url = self.item_url.replace('00000', '00001')
        self.docs[far_url] = {'bbox': [0, 0, 1, 1], 'assets': self.item['assets']}
        self.collection['links'].append({'rel': 'item', 'href': far_url})
        self.collection['extent']['spatial']['bbox'] = [[-85, 0, 1, 42]]
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.fetcher.get.call_count, 3)
        self.files()
        self.assertEqual(self.fetcher.get.call_count, 3)

    def test_existing_per_file_index_keeps_fast_filter(self):
        self.collection['links'].append({'rel': 'item', 'href': './00001/00001.json'})
        self.collection['extent']['spatial']['bbox'] = [[-85, 0, 1, 42], self.bbox, [0, 0, 1, 1]]
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.fetcher.get.call_count, 2)

    def test_three_dimensional_bbox_uses_lon_lat_axes(self):
        self.collection['extent']['spatial']['bbox'] = [[-85, 41, -20, -84, 42, 800]]
        self.item['bbox'] = [-85, 41, -20, -84, 42, 800]
        self.assertEqual(len(self.files()), 1)

    def test_empty_collection_is_empty_but_broken_item_is_an_error(self):
        self.collection['links'] = []
        self.assertEqual(self.files(), [])
        self.idx._coll.clear()
        self.collection['links'] = [{'rel': 'item', 'href': self.item_url}]
        path = Path(self.idx._dir('buildings', 'building_part'), 'collection.json')
        path.write_text(json.dumps(self.collection))
        del self.item['bbox']
        with self.assertRaisesRegex(overture.OvertureError, 'invalid bounding box'):
            self.files()


class OptionalLayerLoadingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.md = mapdata.MapData(self.root, netfetch.Fetcher(offline=True))
        self.addCleanup(self.md.close)
        self.key = mapcells.cell_of(LAT, LON)
        self.calls = []
        self.source_fails = True
        self.road = features([[(-300, 100), (300, 100)], [(120, -100), (120, 300)]],
                             ['secondary', 'residential'])
        self.first = roads.cells_of_tile(FRAME, 0, 0)[0]

        def build(key, layer, kind):
            self.calls.append((key, layer))
            if layer == 'building_parts' and self.source_fails:
                raise overture.OvertureError('STAC buildings/building_part unavailable')
            f = self.road if layer == 'roads' and key == self.first else overture.empty(layer)
            arrays = f.to_arrays('')
            arrays['provenance'] = np.asarray('{}')
            return arrays
        self.md._build = build

    def test_optional_failure_retains_roads_cools_retries_and_never_caches_empty_parts(self):
        for _ in range(3):
            with self.md.capture_complete() as capture:
                cell = self.md.cell(self.key, ('roads', 'building_parts'), optional=('building_parts',))
            self.assertIsNotNone(cell.layers['roads'])
            self.assertIsNone(cell.layers['building_parts'])
            self.assertFalse(capture[0])
            self.assertTrue(capture.failed)
        self.assertEqual(sum(layer == 'building_parts' for _, layer in self.calls), 1)
        self.assertFalse(Path(self.md.path(self.key, 'building_parts')).exists())
        self.source_fails = False
        self.md._optional_retry['building_parts'] = 0  # cooldown elapsed
        with self.md.capture_complete() as capture:
            cell = self.md.cell(self.key, ('roads', 'building_parts'), optional=('building_parts',))
        self.assertIsNotNone(cell.layers['building_parts'])
        self.assertTrue(capture[0])
        self.assertFalse(capture.failed)

    def test_required_sources_still_raise_and_do_not_use_optional_cooldown(self):
        self.md.cell(self.key, ('building_parts',), optional=('building_parts',))
        with self.assertRaises(overture.OvertureError):
            self.md.cell(self.key, ('building_parts',))

    def test_programming_errors_are_not_hidden(self):
        self.md._build = Mock(side_effect=ValueError('bad geometry code'))
        with self.assertRaisesRegex(ValueError, 'bad geometry code'):
            self.md.cell(self.key, ('building_parts',), optional=('building_parts',))

    def test_real_road_worker_finishes_with_buildings_on_and_parts_unavailable(self):
        state = SimpleNamespace(md=self.md, dem=FakeDem(), widths=None, surface=None, airports=None,
                                sea=None, lock=threading.Lock(), bridges={},
                                anchor=lambda aid, lat, lon: (None, None))
        with patch.object(blockworker, '_s', state):
            path, count, status = blockworker.roads_tile(
                1, LAT, LON, 15, 0, 0, self.root, '/temp/x', True, 0.05,
                buildings=True, with_complete=True)
        self.assertGreater(count, 0)
        self.assertTrue(Path(self.root, Path(path).name).exists())
        self.assertTrue(status['sourcesFailed'])  # usable this session, not a permanent incomplete bundle


if __name__ == '__main__':
    unittest.main()
