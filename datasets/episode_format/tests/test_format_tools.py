import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('format_tools', ROOT/'tools/format_tools.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)/'fixture'
        shutil.copytree(ROOT/'examples', self.root)
        self.sid = 'example_001'
        self.input_path = self.root/'inputs'/('example_001.json')
        self.cv = 'image_camera_cv_candidate_v1'
        self.answer_path = self.root/'evaluation'/(self.sid+'.'+self.cv+'.json')

    def tearDown(self):
        self.tmp.cleanup()

    def mutate(self, path, callback):
        data = f.read_json(path)
        callback(data)
        f.write_json(path, data)

    def reject_package(self):
        with self.assertRaises(ValueError):
            f.check_package(self.root)

    def test_synthetic_package(self):
        self.assertEqual(f.check_package(self.root)['n_points'], 5)

    def test_export_whitelist_and_refuse_overwrite(self):
        out = Path(self.tmp.name)/'model'
        self.assertEqual(f.export_inputs(self.root, out, 'screened')['n_samples'], 1)
        data = f.read_json(out/(self.sid+'.json'))
        self.assertEqual(set(data), {'sample_id', 'support', 'query'})
        self.assertEqual(set(data['support']['points'][0]), {'id', 'u', 'v'})
        self.assertEqual(sorted(p.name for p in out.iterdir()), [self.sid+'.json', 'images'])
        with self.assertRaises(ValueError):
            f.export_inputs(self.root, out, 'screened')

    def test_prediction_ids_are_order_independent(self):
        path = self.root/'prediction.json'
        self.mutate(path, lambda d: d['points'].reverse())
        self.assertEqual(f.check_prediction(self.root, path)['n_predictions'], 1)

    def test_duplicate_point(self):
        self.mutate(self.input_path, lambda d: d['support']['points'].append(copy.deepcopy(d['support']['points'][0])))
        self.reject_package()

    def test_boolean_id_is_not_integer(self):
        self.mutate(self.input_path, lambda d: d['support']['points'][0].update(id=True))
        self.reject_package()

    def test_wrong_image_dimensions_shape(self):
        self.mutate(self.input_path, lambda d: d['query'].update(size=[256]))
        self.reject_package()

    def test_unsafe_image_path(self):
        for value in ('../secret.png', '/tmp/secret.png', 'https://example.com/image.png'):
            data = f.read_json(self.input_path)
            data['query']['image'] = value
            with self.assertRaises(ValueError):
                f.check_input(data, self.root/'inputs', archived=True)

    def test_symlink_escape(self):
        external = Path(self.tmp.name)/'outside.png'
        external.write_bytes(b'outside')
        image = self.root/'inputs/images/example_001_query.png'
        image.unlink(); image.symlink_to(external)
        self.reject_package()

    def test_duplicate_image_bytes(self):
        shutil.copyfile(self.root/'inputs/images/example_001_support.png',
                        self.root/'inputs/images/example_001_query.png')
        self.reject_package()

    def test_crop_scale_wrong(self):
        self.mutate(self.input_path, lambda d: d['budget_declaration']['crop']['query_crop'].update(scale_x=2))
        self.reject_package()

    def test_current_resample_declaration_is_backward_compatible(self):
        def add_resample(d):
            crop = d['budget_declaration']['crop']
            crop['resample'] = 'PIL BILINEAR (not cv2.warpAffine)'
            crop['query_crop']['resample'] = crop['resample']
        self.mutate(self.input_path, add_resample)
        self.assertEqual(f.check_package(self.root)['n_points'], 5)
        out = Path(self.tmp.name)/'current_model'
        f.export_inputs(self.root, out, 'screened')
        self.assertNotIn('budget_declaration', f.read_json(out/(self.sid+'.json')))

    def test_incompatible_resample_rejected(self):
        self.mutate(self.input_path, lambda d: d['budget_declaration']['crop'].update(resample='nearest'))
        self.reject_package()

    def test_support_outside(self):
        self.mutate(self.input_path, lambda d: d['support']['points'][0].update(u=-1))
        self.reject_package()

    def test_occluded_support_rejected_current_profile(self):
        self.mutate(self.input_path, lambda d: d['support']['points'][0].update(raw_status=2))
        self.reject_package()

    def test_answer_point_set(self):
        self.mutate(self.answer_path, lambda d: d['answers'][0].update(id=6))
        self.reject_package()

    def test_missing_native2d_not_false_zero(self):
        self.mutate(self.answer_path, lambda d: d['answers'][-1].update(query_2d_native=[0, 0]))
        self.reject_package()

    def test_unknown_visibility_is_allowed(self):
        self.assertIsNone(f.read_json(self.answer_path)['answers'][0]['visible_in_rgb'])
        f.check_package(self.root)

    def test_wrong_coordinate_center(self):
        self.mutate(self.answer_path, lambda d: d['normalisation'].update(center=[99, 99, 99]))
        self.reject_package()

    def test_nonstandard_nan_duplicate_keys_overflow(self):
        path = self.root/'bad.json'
        for text in ('{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"x":1,"x":2}'):
            path.write_text(text)
            with self.assertRaises(ValueError):
                f.read_json(path)

    def test_leaking_model_query_field(self):
        data = f.model_record(f.read_json(self.input_path))
        data['query']['xyz_camera'] = [0, 0, 0]
        with self.assertRaises(ValueError):
            f.check_input(data, self.root/'inputs')

    def test_unknown_split_member(self):
        self.mutate(self.root/'splits/screened.json', lambda d: d['members'].append('not_a_sample'))
        self.reject_package()

    def test_duplicate_manifest(self):
        self.mutate(self.root/'manifest.json', lambda d: d['samples'].append(copy.deepcopy(d['samples'][0])))
        self.reject_package()

    def test_wrong_prediction_version_or_incomplete(self):
        data = f.read_json(self.root/'prediction.json')
        for field, value in [('coordinate_version', 'pascal_source_pretheta_v1'), ('points', data['points'][:-1])]:
            wrong = copy.deepcopy(data); wrong[field] = value
            f.write_json(self.root/'bad_prediction.json', wrong)
            with self.assertRaises(ValueError):
                f.check_prediction(self.root, self.root/'bad_prediction.json')

    def test_schema_unknown_keywords_fail_closed(self):
        with self.assertRaises(ValueError):
            f.validate(2, {'type': 'integer', 'multipleOf': 2})


if __name__ == '__main__':
    unittest.main()
