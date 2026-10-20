import unittest
import numpy as np
from head_selection import hair_materials,retained_head_nodes,head_faces


class HeadSelectionTest(unittest.TestCase):
    def test_hair_below_neck_with_body_weights_is_preserved(self):
        p=np.array([[0,1.2,0],[.05,.9,0],[-.05,.9,0]]);tri=np.array([[0,1,2]])
        head=np.array([1,0,0]);neck=np.array([0,1,0])
        self.assertFalse(head_faces(tri,p,head,neck,1.1)[0])
        self.assertTrue(head_faces(tri,p,head,neck,1.1,True)[0])
    def test_material_recognition_handles_back_hair_and_japanese(self):
        d={'materials':[{'name':s} for s in ('back_hair','前髪','横髪','cloth','skin','necklace')]}
        self.assertEqual(hair_materials(d),{0,1,2})
    def test_external_hair_branch_imports_endpoints_without_body_controls(self):
        nodes=[{'children':[1,4]},{'children':[2]},{'children':[3]}, {}, {'children':[5]},{}]
        parents={1:0,4:0,2:1,3:2,5:4}
        bones={'hips':0,'spine':1,'head':2}
        kept=retained_head_nodes(nodes,parents,bones,{0,1,4})
        self.assertEqual(kept,{2,3,4,5})
        self.assertNotIn(0,kept);self.assertNotIn(1,kept)
