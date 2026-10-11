import unittest
import test_core
from vrm_core import REQUIRED, package_vrm, MAP
from spring_bones import setup_springs, classify
from bone_mapping import map_bones, validate_fingers

class SpringTest(unittest.TestCase):
    def fixture(self):
        d=test_core.CoreTest().fixture();package_vrm(d,{r:r for r in REQUIRED},'test','author','')
        for n in d['nodes']:
            if n['name']=='head':n['translation']=[0,1.3,0]
        for name in ('髪','リボン','袖','スカート','左胸'):
            root=len(d['nodes']);d['nodes'] += [{'name':name,'children':[root+1]}, {'name':name+'先','translation':[0,.1,0]}]
            d['skins'][0]['joints'] += [root,root+1]
        return d
    def test_categories_and_colliders(self):
        d=self.fixture();r=setup_springs(d)
        self.assertEqual(len(r['groups']),5)
        groups=d['extensions']['VRM']['secondaryAnimation']['boneGroups']
        self.assertEqual(groups[-1]['colliderGroups'],[])
        self.assertEqual(groups[-1]['stiffiness'],2.5)
        self.assertEqual(groups[-1]['dragForce'],0.6)
        for g in groups:
            self.assertTrue(all(i<r['colliderCount'] for i in g['colliderGroups']))
            self.assertNotIn(g['bones'][0],range(len(REQUIRED)))
    def test_disabled_and_no_colliders(self):
        d=self.fixture();r=setup_springs(d,options={'chest':{'enabled':False},'colliders':False})
        self.assertEqual(len(r['groups']),4);self.assertEqual(r['colliderCount'],0)
        self.assertFalse(any(g['category']=='chest' for g in r['groups']))
    def test_invalid_settings(self):
        for value in (-1,11,float('nan')):
            with self.assertRaises(ValueError):setup_springs(self.fixture(),options={'hair':{'stiffness':value}})
    def test_humanoid_descendant_rejected(self):
        d=self.fixture();root=len(REQUIRED);d['nodes'][root]['children'].append(0)
        r=setup_springs(d)
        self.assertTrue(any(g['reason']=='contains_humanoid_bone' for g in r['skipped']))
    def test_classification(self):
        self.assertIsNone(classify('髪IK'));self.assertIsNone(classify('胸先'))
        self.assertEqual(classify('胸リボン'),'ribbon')

class FingerTest(unittest.TestCase):
    def test_fullwidth_names(self):
        aliases={names[0].translate(str.maketrans('0123','０１２３')):role for role,names in MAP.items()}
        mapping,warnings=map_bones(aliases)
        self.assertEqual(len([r for r in mapping if any(f in r for f in ('Thumb','Index','Middle','Ring','Little'))]),30)
        self.assertEqual(warnings,[])
    def test_chain_and_invalid_parent(self):
        d={'nodes':[{'children':[1]},{'children':[2]},{'children':[3]},{}]}
        m={'leftHand':0,'leftIndexProximal':1,'leftIndexIntermediate':2,'leftIndexDistal':3}
        r=validate_fingers(d,m);self.assertEqual(len(r['assigned']),3)
        d['nodes'][0]['children']=[1,2];d['nodes'][1]['children']=[]
        r=validate_fingers(d,m);self.assertEqual(r['rejected'],['leftIndexIntermediate','leftIndexDistal'])
    def test_ambiguous_name(self):
        m,w=map_bones({'左親指０':'a','左親指0':'b'})
        self.assertNotIn('leftThumbProximal',m);self.assertTrue(w)
