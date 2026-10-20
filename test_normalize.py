import struct
import unittest
import numpy as np
from normalize import normalize, world_matrices

class NormalizationTest(unittest.TestCase):
    def test_pose_geometry_and_bind_matrices(self):
        nodes=[{'name':'root','children':[1,2,5,8,9]},
          {'name':'head','translation':[0,2,0],'rotation':[0,0.2,0,0.979795897]},
          {'name':'leftUpperArm','translation':[0.2,1.6,0],'children':[3]},
          {'name':'leftLowerArm','translation':[0.3,-0.2,0],'children':[4]},
          {'name':'leftHand','translation':[0.3,-0.2,0]},
          {'name':'rightUpperArm','translation':[-0.2,1.6,0],'children':[6]},
          {'name':'rightLowerArm','translation':[-0.3,-0.2,0],'children':[7]},
          {'name':'rightHand','translation':[-0.3,-0.2,0]},
          {'name':'mesh','mesh':0,'skin':0},
          {'name':'eye','translation':[0,2,0.1]}]
        doc={'nodes':nodes,'buffers':[{'byteLength':0}],'bufferViews':[],'accessors':[],
             'skins':[{'joints':[1,4]}],'meshes':[{'primitives':[{'attributes':{}}]}]}
        data=bytearray()
        def accessor(a,kind,component=5126):
            a=np.asarray(a,dtype='<f4' if component==5126 else '<u2')
            offset=len(data);data.extend(a.tobytes());v=len(doc['bufferViews'])
            doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':a.nbytes})
            index=len(doc['accessors']);doc['accessors'].append({'bufferView':v,'componentType':component,'count':len(a),'type':kind})
            return index
        world,_=world_matrices(doc)
        doc['skins'][0]['inverseBindMatrices']=accessor([np.linalg.inv(world[j]).T.reshape(-1) for j in [1,4]],'MAT4')
        attr=doc['meshes'][0]['primitives'][0]['attributes']
        attr['POSITION']=accessor([[0,2,0],[0.8,1.2,0]],'VEC3')
        attr['JOINTS_0']=accessor([[0,0,0,0],[1,0,0,0]],'VEC4',5123)
        attr['WEIGHTS_0']=accessor([[1,0,0,0],[1,0,0,0]],'VEC4')
        # Sparse morph must remain sparse and rotate with its vertex's skin.
        target=accessor([[0.01,0,0],[0,0.01,0]],'VEC3')
        doc['meshes'][0]['primitives'][0]['targets']=[{'POSITION':target}]
        bones={'head':1,'leftEye':9,'rightEye':9,'leftUpperArm':2,'leftLowerArm':3,'leftHand':4,
               'rightUpperArm':5,'rightLowerArm':6,'rightHand':7}
        chunks=normalize(doc,[(0x004E4942,bytes(data))],bones,lambda _:None)
        self.assertTrue(all('rotation'not in n and 'scale'not in n for n in doc['nodes']))
        new,_=world_matrices(doc)
        self.assertAlmostEqual(new[2][1,3],new[4][1,3])
        self.assertAlmostEqual(new[5][1,3],new[7][1,3])
        self.assertLess(new[9][2,3],0)
        binary=chunks[0][1]
        a=doc['accessors'][attr['POSITION']];v=doc['bufferViews'][a['bufferView']]
        positions=np.frombuffer(binary,dtype='<f4',offset=v['byteOffset'],count=6).reshape(2,3)
        np.testing.assert_allclose(positions[0],[0,2,0],atol=1e-6)
        np.testing.assert_allclose(positions[1],new[4][:3,3],atol=1e-6)
        self.assertIn('sparse',doc['accessors'][target])
        a=doc['accessors'][doc['skins'][0]['inverseBindMatrices']];v=doc['bufferViews'][a['bufferView']]
        ibm=np.frombuffer(binary,dtype='<f4',offset=v['byteOffset'],count=32).reshape(2,4,4).transpose(0,2,1)
        for i,j in enumerate([1,4]):np.testing.assert_allclose(new[j]@ibm[i],np.eye(4),atol=1e-6)

    def test_both_side_conventions_stay_outward_and_idempotent(self):
        import test_body_template
        for reverse in (False,True):
            doc,chunks,bones=test_body_template.fixture()
            if reverse:
                for part in ('UpperArm','LowerArm','Hand'):
                    bones['left'+part],bones['right'+part]=bones['right'+part],bones['left'+part]
            chunks=normalize(doc,chunks,bones,lambda _:None)
            first,_=world_matrices(doc)
            center=first[bones['head']][0,3]
            for side in ('left','right'):
                shoulder=first[bones[side+'UpperArm']][0,3]-center
                hand=first[bones[side+'Hand']][0,3]-center
                self.assertGreater(shoulder*hand,0)
                self.assertGreater(abs(hand),abs(shoulder))
            normalize(doc,chunks,bones,lambda _:None)
            second,_=world_matrices(doc)
            np.testing.assert_allclose(first,second,atol=1e-6)

if __name__=='__main__':unittest.main()
