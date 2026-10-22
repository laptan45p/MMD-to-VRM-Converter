import copy
import unittest

from expressions import build_expressions


def mesh(names):
    return {'extras': {'targetNames': names},
            'primitives': [{'targets': [{} for _ in names]}]}


class ExpressionTest(unittest.TestCase):
    def test_emotions_combine_regions_and_weights(self):
        names = ['笑い', 'にこり', 'にこり口', 'キリッ', '怒り', '口角下げ', '困る', '泣き目']
        doc = {'meshes': [mesh(names)]}
        before = copy.deepcopy(doc)
        groups, report = build_expressions(doc)
        presets = {g['presetName']: g for g in groups if g['presetName'] != 'unknown'}
        self.assertEqual([(names[b['index']], b['weight']) for b in presets['joy']['binds']],
                         [('笑い', 70), ('にこり', 60), ('にこり口', 70)])
        for preset in ['joy', 'angry', 'sorrow', 'fun']:
            self.assertEqual(len(presets[preset]['binds']), 3)
        self.assertEqual(report['customCount'], len(names))
        self.assertEqual(doc, before)

    def test_aliases_choose_one_globally_across_split_meshes(self):
        groups, _ = build_expressions({'meshes': [mesh(['にこり口']),
                                      mesh(['にこり口', '口角上げ'])]})
        joy = next(g for g in groups if g['presetName'] == 'joy')
        self.assertEqual([(b['mesh'], b['index']) for b in joy['binds']], [(0, 0), (1, 0)])

    def test_raw_morphs_group_by_name_and_avoid_reserved_name_collisions(self):
        names = ['あ', 'a', 'MMD_a', 'Ａ', 'ハート', 'neutral']
        groups, report = build_expressions({'meshes': [mesh(names), mesh(['ハート'])]})
        custom = [g for g in groups if g['presetName'] == 'unknown']
        self.assertEqual(len(custom), len(names))
        self.assertEqual(len({g['name'].casefold() for g in groups}), len(groups))
        heart = next(g for g in custom if g['name'] == 'ハート')
        self.assertEqual(len(heart['binds']), 2)
        self.assertIn('MMD_a_2', [g['name'] for g in custom])
        self.assertEqual(report['meshMorphCount'], 7)
        self.assertFalse(report['materialMorphsSupported'])

    def test_missing_components_reported_and_fallback_works(self):
        groups, report = build_expressions({'meshes': [mesh(['悲しい', '口角上げ'])]})
        sorrow = next(g for g in groups if g['presetName'] == 'sorrow')
        self.assertEqual(sorrow['binds'], [{'mesh': 0, 'index': 0, 'weight': 70}])
        detail = next(p for p in report['presets'] if p['preset'] == 'sorrow')
        self.assertEqual(detail['status'], 'partial')
        self.assertEqual(detail['missingComponents'], ['eyes', 'mouth'])
        self.assertFalse(any(g['presetName'] == 'blink' for g in groups))

    def test_invalid_target_references_are_not_registered(self):
        m = mesh(['あ', 'い'])
        m['primitives'][0]['targets'].pop()
        groups, report = build_expressions({'meshes': [m]})
        self.assertEqual(report['uniqueMorphCount'], 1)
        self.assertEqual(len(report['warnings']), 1)
        self.assertTrue(all(b['index'] == 0 for g in groups for b in g['binds']))

    def test_empty_document(self):
        groups, report = build_expressions({})
        self.assertEqual(groups, [])
        self.assertEqual(report['presetCount'], 0)
        self.assertTrue(all(p['status'] == 'missing' for p in report['presets']))

    def test_lipsync_blink_and_sides_remain_full_strength(self):
        names = ['まばたき', 'あ', 'い', 'う', 'え', 'お', 'ウインク', 'ウインク右']
        groups, _ = build_expressions({'meshes': [mesh(names)]})
        for preset, index in zip(['blink', 'a', 'i', 'u', 'e', 'o', 'blink_l', 'blink_r'], range(8)):
            g = next(g for g in groups if g['presetName'] == preset)
            self.assertEqual(g['binds'], [{'mesh': 0, 'index': index, 'weight': 100}])



class PairedMouthTest(unittest.TestCase):
    def test_split_corners_combine_both_sides_without_double_applying_full_mouth(self):
        names = ['笑い', 'なごみ', '困る', '怒り', 'キリッ', '目尻＿下げ',
                 '左口角上げ', '右口角上げ', '左口角下げ', '右口角下げ', 'ムッ']
        groups, report = build_expressions({'meshes': [mesh(names)]})
        presets = {g['presetName']: g for g in groups if g['presetName'] != 'unknown'}
        self.assertEqual([names[b['index']] for b in presets['joy']['binds']],
                         ['笑い', '左口角上げ', '右口角上げ'])
        self.assertEqual([names[b['index']] for b in presets['sorrow']['binds']],
                         ['目尻＿下げ', '困る', '左口角下げ', '右口角下げ'])
        self.assertIn('ムッ', [names[b['index']] for b in presets['angry']['binds']])
        self.assertEqual(next(p for p in report['presets'] if p['preset']=='joy')['missingComponents'], ['brows'])
        names.append('口角上げ')
        groups, _ = build_expressions({'meshes': [mesh(names)]})
        joy = next(g for g in groups if g['presetName']=='joy')
        self.assertEqual([names[b['index']] for b in joy['binds']], ['笑い', '口角上げ'])

    def test_one_sided_corner_is_not_used_as_symmetric_expression(self):
        groups, report = build_expressions({'meshes': [mesh(['左口角上げ', '笑い'])]})
        joy = next(g for g in groups if g['presetName']=='joy')
        self.assertEqual(len(joy['binds']), 1)
        self.assertIn('mouth', next(p for p in report['presets'] if p['preset']=='joy')['missingComponents'])
        self.assertEqual(report['customCount'], 2)

    def test_split_parts_can_be_on_different_meshes_and_keep_original_names(self):
        groups, report = build_expressions({'meshes': [mesh(['口角上げ左']), mesh(['口角上げ右'])]})
        joy = next(g for g in groups if g['presetName']=='joy')
        self.assertEqual([(b['mesh'], b['index']) for b in joy['binds']], [(0,0),(1,0)])
        self.assertEqual([c['sourceMorph'] for c in report['customExpressions']], ['口角上げ左','口角上げ右'])

if __name__ == '__main__':
    unittest.main()
