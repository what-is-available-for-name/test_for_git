#!/usr/bin/env python3
"""Read-only validation and whitelist export for the current RGB episode profile.

Python 3.8+, stdlib only. This is not an evaluator or a general JSON Schema engine.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
FORMAT_ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError('non-standard JSON number: ' + value)

    data = json.loads(Path(path).read_text(encoding='utf-8'),
                      object_pairs_hook=pairs, parse_constant=invalid)
    finite_tree(data)
    return data


def finite_tree(value):
    if isinstance(value, float):
        require(math.isfinite(value), 'non-finite number')
    elif isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)


def _type(value, name):
    return {'object': isinstance(value, dict), 'array': isinstance(value, list),
            'number': type(value) in (int, float), 'integer': type(value) is int,
            'string': isinstance(value, str), 'boolean': type(value) is bool,
            'null': value is None}[name]


def validate(value, schema, at='$'):
    """Only the keywords used by this directory's self-contained schemas.

    Reject unsupported validation keywords rather than silently skipping them.
    Editors may use a full Draft 2020-12 validator independently.
    """
    supported = {'$schema', 'title', 'type', 'enum', 'const', 'anyOf', 'required',
                 'properties', 'additionalProperties', 'items', 'minItems',
                 'maxItems', 'uniqueItems', 'minimum', 'exclusiveMinimum',
                 'minLength', 'pattern'}
    require(not (set(schema) - supported), 'unsupported schema keyword at ' + at)
    finite_tree(value)
    if 'type' in schema:
        types = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        require(any(_type(value, t) for t in types), at + ': wrong type')
    if 'enum' in schema:
        require(value in schema['enum'], at + ': unknown enum value')
    if 'const' in schema:
        require(type(value) is type(schema['const']) and value == schema['const'],
                at + ': wrong constant')
    if 'anyOf' in schema:
        errors = []
        for option in schema['anyOf']:
            try:
                validate(value, option, at)
                break
            except ValueError as exc:
                errors.append(str(exc))
        else:
            raise ValueError(at + ': no anyOf match: ' + '; '.join(errors))
    if isinstance(value, dict):
        require(set(schema.get('required', [])) <= set(value), at + ': missing field')
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            require(not (set(value) - set(props)), at + ': unexpected field')
        for key, child in value.items():
            if key in props:
                validate(child, props[key], at + '.' + key)
    if isinstance(value, list):
        require(len(value) >= schema.get('minItems', 0), at + ': too few items')
        require(len(value) <= schema.get('maxItems', math.inf), at + ': too many items')
        if schema.get('uniqueItems'):
            encoded = [json.dumps(x, sort_keys=True) for x in value]
            require(len(set(encoded)) == len(encoded), at + ': duplicate item')
        for i, item in enumerate(value):
            if 'items' in schema:
                validate(item, schema['items'], at + '[' + str(i) + ']')
    if type(value) in (int, float):
        if 'minimum' in schema:
            require(value >= schema['minimum'], at + ': below minimum')
        if 'exclusiveMinimum' in schema:
            require(value > schema['exclusiveMinimum'], at + ': below exclusive minimum')
    if isinstance(value, str):
        require(len(value) >= schema.get('minLength', 0), at + ': string too short')
        if 'pattern' in schema:
            require(re.search(schema['pattern'], value) is not None, at + ': invalid string')


def check_schema(data, name):
    validate(data, read_json(FORMAT_ROOT / 'schemas' / (name + '.schema.json')))


def safe_file(base, relative):
    require(isinstance(relative, str) and bool(relative), 'empty file path')
    require('\\' not in relative and ':' not in relative, 'non-portable file path')
    rel = Path(relative)
    require(not rel.is_absolute() and '..' not in rel.parts, 'unsafe file path: ' + relative)
    base = Path(base).resolve()
    path = (base / rel).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise ValueError('file/symlink escapes directory: ' + relative)
    require(path.is_file(), 'missing file: ' + relative)
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def point_ids(rows):
    ids = [row['id'] for row in rows]
    require(len(ids) == len(set(ids)), 'duplicate point id')
    return set(ids)


def check_input(data, base, archived=False):
    check_schema(data, 'archive_input' if archived else 'model_input')
    point_ids(data['support']['points'])
    w, h = data['support']['size']
    require(all(0 <= p['u'] < w and 0 <= p['v'] < h
                for p in data['support']['points']), 'support point outside crop')
    paths = [safe_file(base, data[role]['image']) for role in ('support', 'query')]
    require(digest(paths[0]) != digest(paths[1]), 'support/query are the same image bytes')
    if archived:
        crops = data['budget_declaration']['crop']
        for role, crop in [('support', crops), ('query', crops['query_crop'])]:
            l, t, r, b = crop['box_float']
            require(r > l and b > t, 'invalid crop box')
            expected = [r-l, b-t]
            require(all(abs(a-b) < 1e-6 for a, b in zip(crop['size'], expected)),
                    'crop size mismatch')
            require(abs(crop['scale_x'] * expected[0] - data[role]['size'][0]) < 1e-5,
                    'crop x scale mismatch')
            require(abs(crop['scale_y'] * expected[1] - data[role]['size'][1]) < 1e-5,
                    'crop y scale mismatch')
    return paths


def moments(points):
    n = len(points)
    center = [sum(p[j] for p in points)/n for j in range(3)]
    rms = math.sqrt(sum(sum((p[j]-center[j])**2 for j in range(3)) for p in points)/n)
    return center, rms


def check_answer(data, inp, version):
    check_schema(data, 'evaluation')
    require(data['sample_id'] == inp['sample_id'], 'answer sample_id mismatch')
    require(data['coordinate_version'] == version, 'answer coordinate_version mismatch')
    require(point_ids(data['answers']) == point_ids(inp['support']['points']),
            'input/answer point id set mismatch')
    for p in data['answers']:
        valid = p['annotation_valid_2d']
        require((p['query_2d_native'] is not None) == valid, '2D validity/coordinate mismatch')
        require(p['query_2d_origin'] == ('native_annotation' if valid else 'missing'),
                '2D origin mismatch')
    center, rms = moments([p['xyz_camera'] for p in data['answers']])
    meta = data['normalisation']
    require(rms > 0, 'zero GT RMS')
    require(meta['n_valid'] == len(data['answers']), 'n_valid mismatch')
    require(max(abs(a-b) for a, b in zip(center, meta['center'])) < 2e-6,
            'normalisation center mismatch')
    require(abs(rms-meta['rms']) < 2e-6, 'normalisation RMS mismatch')


def package_index(root):
    root = Path(root)
    man = read_json(root/'manifest.json')
    require(isinstance(man, dict), 'manifest must be an object')
    samples = man['samples']
    require(isinstance(samples, list) and samples, 'empty/bad manifest samples')
    ids = [s['sample_id'] for s in samples]
    for sid in ids:
        require(isinstance(sid, str) and re.fullmatch(r'[A-Za-z0-9_-]+', sid), 'unsafe sample_id')
    require(len(set(ids)) == len(ids), 'duplicate manifest sample_id')
    require(man['n_samples'] == len(ids), 'n_samples mismatch')
    versions = man['coordinate_versions']
    allowed = {'pascal_source_pretheta_v1', 'image_camera_cv_candidate_v1'}
    require(isinstance(versions, list) and versions and len(set(versions)) == len(versions),
            'duplicate/empty versions')
    require(set(versions) <= allowed, 'unknown coordinate version')
    require(man['provisional_defaults']['coordinate'] in versions, 'bad default version')
    return man, {s['sample_id']: s for s in samples}


def split_members(root, name, ids):
    require(re.fullmatch(r'[A-Za-z0-9_-]+', name), 'unsafe split name')
    data = read_json(safe_file(root, 'splits/' + name + '.json'))
    check_schema(data, 'split')
    require(data['name'] == name, 'split name mismatch')
    require(set(data['members']) <= set(ids), 'unknown split member')
    return data['members']


def check_package(root):
    root = Path(root)
    man, samples = package_index(root)
    require({p.stem for p in (root/'inputs').glob('*.json')} == set(samples),
            'manifest/input files mismatch')
    expected_answers = {sid+'.'+v+'.json' for sid in samples for v in man['coordinate_versions']}
    require({p.name for p in (root/'evaluation').glob('*.json')} == expected_answers,
            'manifest/evaluation files mismatch')
    points = 0
    for sid, sample in samples.items():
        inp = read_json(safe_file(root, 'inputs/'+sid+'.json'))
        check_input(inp, root/'inputs', archived=True)
        require(inp['sample_id'] == sid, 'input sample_id mismatch')
        k = len(inp['support']['points'])
        require(k >= 5 and sample['k'] == k, 'current profile K>=5 / manifest k mismatch')
        points += k
        for version in man['coordinate_versions']:
            ev = read_json(safe_file(root, 'evaluation/'+sid+'.'+version+'.json'))
            check_answer(ev, inp, version)
        audit = read_json(safe_file(root, 'audit/'+sid+'.json'))
        require(audit['sample_id'] == sid, 'audit sample_id mismatch')
    split_paths = list((root/'splits').glob('*.json'))
    require(split_paths, 'no split files')
    for path in split_paths:
        split_members(root, path.stem, samples)
    return {'n_samples': len(samples), 'n_points': points,
            'n_answers': len(samples)*len(man['coordinate_versions']),
            'result': 'format_and_cross_file_checks_passed',
            'note': 'No image decoding, semantic QA, 3D accuracy or protocol acceptance.'}


def model_record(archive):
    return {'sample_id': archive['sample_id'],
            'support': {'image': archive['support']['image'],
                        'size': archive['support']['size'],
                        'points': [{k: p[k] for k in ('id', 'u', 'v')}
                                   for p in archive['support']['points']]},
            'query': {k: archive['query'][k] for k in ('image', 'size')}}


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                          encoding='utf-8')


def export_inputs(root, destination, split):
    root, out = Path(root), Path(destination)
    require(not out.exists(), 'output already exists; refusing overwrite')
    check_package(root)
    _, samples = package_index(root)
    members = split_members(root, split, samples)
    require(members, 'empty export split')
    prepared = []
    for sid in members:
        inp = read_json(root/'inputs'/(sid+'.json'))
        prepared.append((model_record(inp), check_input(inp, root/'inputs', archived=True)))
    # No writes until source validation and all member lookups pass.
    out.mkdir(parents=True, exist_ok=False)
    (out/'images').mkdir()
    for data, paths in prepared:
        for role, path in zip(('support', 'query'), paths):
            name = data['sample_id']+'_'+role+path.suffix.lower()
            data[role]['image'] = 'images/'+name
            shutil.copyfile(path, out/'images'/name)
        write_json(out/(data['sample_id']+'.json'), data)
    result = check_inputs_only(out)
    return dict(result, split=split, note='Whitelist files only; process isolation is separate.')


def check_inputs_only(root):
    root = Path(root)
    require(all(p.name == 'images' or (p.is_file() and p.suffix == '.json')
                for p in root.iterdir()), 'unexpected entry in model-input directory')
    require((root/'images').is_dir(), 'missing image directory')
    files = sorted(root.glob('*.json'))
    require(files, 'no model input JSON')
    image_paths, ids, count = set(), set(), 0
    for path in files:
        data = read_json(path)
        paths = check_input(data, root)
        sid = data['sample_id']
        require(path.stem == sid and sid not in ids, 'duplicate/mismatched input sample_id')
        ids.add(sid)
        image_paths.update(paths)
        count += len(data['support']['points'])
    actual = {p.resolve() for p in (root/'images').rglob('*') if p.is_file()}
    require(actual == image_paths, 'unreferenced or missing model images')
    return {'n_samples': len(ids), 'n_points': count, 'result': 'model_input_checks_passed'}


def check_prediction(root, path):
    man, samples = package_index(root)
    raw = read_json(path)
    batch = isinstance(raw, dict) and 'predictions' in raw
    check_schema(raw, 'batch_prediction' if batch else 'prediction')
    rows = raw['predictions'] if batch else [raw]
    ids = [r['sample_id'] for r in rows]
    require(len(set(ids)) == len(ids), 'duplicate prediction sample_id')
    require(bool(rows), 'empty predictions')
    for row in rows:
        sid = row['sample_id']
        require(sid in samples, 'unknown prediction sample_id')
        require(row['coordinate_version'] == man['provisional_defaults']['coordinate'],
                'prediction coordinate_version mismatch with package default')
        inp = read_json(safe_file(root, 'inputs/'+sid+'.json'))
        require(point_ids(row['points']) == point_ids(inp['support']['points']),
                'complete prediction point id set mismatch')
    return {'n_predictions': len(rows), 'result': 'complete_prediction_format_passed',
            'note': 'Not a score; missing predictions/points must still count as failures in evaluator.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    for name in ('check', 'check-inputs'):
        sub.add_parser(name).add_argument('package')
    ex = sub.add_parser('export')
    ex.add_argument('package'); ex.add_argument('destination')
    ex.add_argument('--split', required=True)
    pred = sub.add_parser('check-prediction')
    pred.add_argument('package'); pred.add_argument('prediction')
    args = ap.parse_args()
    try:
        if args.command == 'check':
            result = check_package(args.package)
        elif args.command == 'check-inputs':
            result = check_inputs_only(args.package)
        elif args.command == 'export':
            result = export_inputs(args.package, args.destination, args.split)
        else:
            result = check_prediction(args.package, args.prediction)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        print('ERROR: '+str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
