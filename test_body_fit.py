import unittest
import numpy as np
from body_fit import torso_landmarks, neutral_body_material


class BodyFitTest(unittest.TestCase):
    def fixture(self):
        bones={role:i for i,role in enumerate(('hips','spine','chest','neck','leftUpperLeg','rightUpperLeg'))}
        positions=np.array([[0,.88,0],[0,.95,0],[0,1.02,0],[0,1.24,0],[-.07,.83,0],[.07,.83,0]])
        return positions,bones

    def test_coincident_waist_controls_do_not_flatten_pelvis(self):
        donor,b=self.fixture();source=donor.copy();source[b['hips']]=[0,.99,0];source[b['spine']]=[0,.99,0]
        before=source.copy();fitted,scale,report=torso_landmarks(source,donor,b,b)
        self.assertTrue(report['adjusted']);self.assertAlmostEqual(scale,1)
        np.testing.assert_allclose(fitted,donor)
        np.testing.assert_array_equal(source,before)
        self.assertGreater(fitted[b['spine'],1]-fitted[b['hips'],1],.06)

    def test_elevated_hips_use_leg_roots_and_neck(self):
        donor,b=self.fixture();source=donor*1.2+[.02,.1,.01]
        source[b['hips'],1]=1.3;source[b['spine'],1]=1.4
        fitted,scale,report=torso_landmarks(source,donor,b,b)
        self.assertTrue(report['adjusted']);self.assertAlmostEqual(scale,1.2)
        np.testing.assert_allclose(fitted,donor*1.2+[.02,.1,.01])

    def test_anatomical_landmarks_are_preserved(self):
        donor,b=self.fixture();source=donor*1.1
        fitted,scale,report=torso_landmarks(source,donor,b,b)
        self.assertFalse(report['adjusted']);self.assertAlmostEqual(scale,1.1)
        np.testing.assert_array_equal(fitted,source)

    def test_invalid_body_height_is_rejected(self):
        donor,b=self.fixture();source=donor.copy();source[b['neck'],1]=.83
        with self.assertRaises(ValueError):torso_landmarks(source,donor,b,b)

    def test_template_rim_outline_and_shade_maps_are_removed(self):
        props={'floatProperties':{'_OutlineWidthMode':2,'_OutlineWidth':.6,'_BlendMode':2},
            'vectorProperties':{'_Color':[1,.8,.6,.5],'_MainTex':[0,0,1,1]},
            'textureProperties':{'_MainTex':3,'_RimTexture':13,'_ShadeTexture':11,'_ShadingGradeTexture':12,'_BumpMap':2}}
        result=neutral_body_material(props)
        self.assertEqual(result['textureProperties'],{'_MainTex':3,'_ShadeTexture':3,'_BumpMap':2})
        self.assertEqual(result['floatProperties']['_OutlineWidthMode'],0)
        self.assertEqual(result['floatProperties']['_BlendMode'],2)
        self.assertEqual(result['vectorProperties']['_Color'],[1,.8,.6,.5])
        self.assertEqual(result['vectorProperties']['_RimColor'],[0,0,0,1])
