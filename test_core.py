import copy
import tempfile
import unittest
from pathlib import Path
from vrm_core import REQUIRED, package_vrm, read_glb, write_glb

class CoreTest(unittest.TestCase):
    def fixture(self):
        parents={'spine':'hips','head':'spine',
           'leftLowerArm':'leftUpperArm','leftHand':'leftLowerArm',
           'rightLowerArm':'rightUpperArm','rightHand':'rightLowerArm',
           'leftUpperLeg':'hips','leftLowerLeg':'leftUpperLeg','leftFoot':'leftLowerLeg',
           'rightUpperLeg':'hips','rightLowerLeg':'rightUpperLeg','rightFoot':'rightLowerLeg'}
        nodes=[{'name':r} for r in REQUIRED]
        indexes={r:i for i,r in enumerate(REQUIRED)}
        for child,parent in parents.items():nodes[indexes[parent]].setdefault('children',[]).append(indexes[child])
        return {'asset':{'version':'2.0'},'nodes':nodes,'skins':[{'joints':list(range(len(nodes)))}],
          'meshes':[{'extras':{'targetNames':['まばたき','あ']}}],
          'materials':[{'name':'face','pbrMetallicRoughness':{'baseColorTexture':{'index':0}},'alphaMode':'BLEND'}]}
    def test_package_roundtrip(self):
        doc=self.fixture();report=package_vrm(doc,{r:r for r in REQUIRED},'テスト','作者','https://example.com')
        self.assertEqual(report['expressions'],['blink','a'])
        self.assertEqual(len(doc['extensions']['VRM']['humanoid']['humanBones']),15)
        self.assertEqual(doc['extensions']['VRM']['materialProperties'][0]['textureProperties']['_MainTex'],0)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.vrm';write_glb(p,doc,[(0x004E4942,b'abcd')]);result,chunks=read_glb(p)
            self.assertEqual(result,doc);self.assertEqual(chunks[0][1],b'abcd')
    def test_missing_bones_rejected(self):
        with self.assertRaises(ValueError):package_vrm(self.fixture(),{},'a','b','')
    def test_bad_hierarchy_rejected(self):
        doc=self.fixture()
        for node in doc['nodes']:node.pop('children',None)
        with self.assertRaises(ValueError):package_vrm(doc,{r:r for r in REQUIRED},'a','b','')
    def test_invalid_glb_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.vrm';p.write_bytes(b'bad header!!')
            with self.assertRaises(ValueError):read_glb(p)

if __name__=='__main__':unittest.main()
