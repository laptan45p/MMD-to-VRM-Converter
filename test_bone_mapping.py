import unittest

from bone_mapping import map_bones, validate_required_bones
from normalize import normalize
from vrm_core import REQUIRED


class HandMappingTest(unittest.TestCase):
    def test_short_hand_names(self):
        mapping, warnings = map_bones({'左手': 'hand.L', '右手': 'hand.R'})
        self.assertEqual(mapping, {'leftHand': 'hand.L', 'rightHand': 'hand.R'})
        self.assertEqual(warnings, [])

    def test_existing_names_take_priority_over_fallback(self):
        for name in ('左手首', 'leftHand', 'lHand'):
            with self.subTest(name=name):
                mapping, warnings = map_bones({name: 'wrist', '左手': 'other'})
                self.assertEqual(mapping['leftHand'], 'wrist')
                self.assertEqual(warnings, [])
        mapping, warnings = map_bones({'右手首': 'wrist', '右手': 'other'})
        self.assertEqual(mapping['rightHand'], 'wrist')
        self.assertEqual(warnings, [])

    def test_ambiguous_existing_names_do_not_use_fallback(self):
        mapping, warnings = map_bones({'左手首': 'a', 'leftHand': 'b', '左手': 'c'})
        self.assertNotIn('leftHand', mapping)
        self.assertTrue(any('leftHand' in warning for warning in warnings))

    def test_twist_and_fingers_are_not_hand_candidates(self):
        mapping, _ = map_bones({'左手捩': 'twist', '左人指１': 'finger'})
        self.assertNotIn('leftHand', mapping)

    def test_required_bones_and_zero_node_index(self):
        mapping = dict.fromkeys(REQUIRED, 0)
        validate_required_bones(mapping)
        del mapping['leftHand']
        del mapping['rightHand']
        with self.assertRaisesRegex(ValueError, 'leftHand, rightHand'):
            validate_required_bones(mapping)

    def test_normalization_reports_missing_hands_before_reading_geometry(self):
        mapping = dict.fromkeys(['head', 'leftUpperArm', 'leftLowerArm',
                                 'rightUpperArm', 'rightLowerArm'], 0)
        with self.assertRaisesRegex(ValueError, 'leftHand, rightHand'):
            normalize({}, [], mapping)
