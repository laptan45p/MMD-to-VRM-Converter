import copy
import json
import unittest
import numpy as np
from body_template import Buffer, triangles, active_joints
from neck_stitch import stitch_neck, topology, simple_projection
from normalize import world_matrices
from test_body_template import fixture


def tube_fixture(top_count=16,body_count=24,body_radius=.05):
    doc,chunks,bones=fixture();buf=Buffer(doc,chunks)
    for mi,(count,low,high,radius,joint) in enumerate([(top_count,1.4,1.6,.055,bones['neck']),(body_count,1.15,1.4,body_radius,bones['chest'])]):
        angle=np.arange(count)*2*np.pi/count
        positions=np.array([[radius*np.cos(a),y,radius*np.sin(a)] for y in (low,high) for a in angle])
        normal=np.array([[np.cos(a),0,np.sin(a)] for y in (low,high) for a in angle])
        idx=[]
        for i in range(count):
            j=(i+1)%count;idx.extend([i,count+i,count+j,i,count+j,j])
        doc['meshes'][mi]={'name':'Head' if mi==0 else 'TemplateBody','primitives':[{'attributes':{
            'POSITION':buf.add(positions,'VEC3'),'NORMAL':buf.add(normal,'VEC3'),
            'JOINTS_0':buf.add([[joint,0,0,0]]*len(positions),'VEC4',5123),
            'WEIGHTS_0':buf.add([[1,0,0,0]]*len(positions),'VEC4')},'indices':buf.add(idx,'SCALAR',5125),'material':mi}]}
    doc['materials'][1]={'name':'Template_BodySkin','pbrMetallicRoughness':{'baseColorFactor':[.8,.6,.5,1]}}
    return doc,buf.finish(),bones

class NeckJoinTest(unittest.TestCase):
    def test_unequal_rings_are_closed(self):
        d,c,b=tube_fixture();out,chunks,r=stitch_neck(d,c,b,1.4)
        self.assertEqual(r['status'],'joined');self.assertEqual(r['bridgeTriangles'],40)
        data=topology(out,Buffer(out,chunks),set(range(len(out['meshes']))),1e-6)
        # Only the remote top and bottom tube openings remain.
        centers=[data['positions'][loop].mean(0)[1] for loop in data['loops']]
        self.assertEqual(len(centers),2);np.testing.assert_allclose(sorted(centers),[1.15,1.6],atol=1e-5)
        self.assertEqual(len(d['meshes']),2);json.dumps(r,allow_nan=False)
    def test_skin_rest_and_normal_alignment(self):
        d,c,b=tube_fixture();out,chunks,r=stitch_neck(d,c,b,1.4);buf=Buffer(out,chunks)
        skin=out['skins'][-1];w,_=world_matrices(out);inverse=buf.read(skin['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
        for joint,m in zip(skin['joints'],inverse):np.testing.assert_allclose(w[joint]@m,np.eye(4),atol=1e-6)
        p=out['meshes'][-1]['primitives'][0];normals=buf.read(p['attributes']['NORMAL']);np.testing.assert_allclose(np.linalg.norm(normals,axis=1),1,atol=1e-6)
        weights=buf.read(p['attributes']['WEIGHTS_0'])+buf.read(p['attributes']['WEIGHTS_1']);np.testing.assert_allclose(weights.sum(1),1)
        self.assertTrue(active_joints(out,chunks))
    def test_crossed_projection_is_rejected(self):
        self.assertFalse(simple_projection(np.array([[0,0,0],[1,0,1],[0,0,1],[1,0,0]],dtype=float)))
        self.assertTrue(simple_projection(np.array([[0,0,0],[1,0,0],[1,0,1],[0,0,1]],dtype=float)))
    def test_disabled_is_unchanged(self):
        d,c,b=tube_fixture();out,chunks,r=stitch_neck(d,c,b,1.4,False)
        self.assertIs(out,d);self.assertIs(chunks,c);self.assertEqual(r['status'],'disabled')
    def test_no_boundary_falls_back(self):
        d,c,b=fixture();before=copy.deepcopy(d);out,chunks,r=stitch_neck(d,c,b,1.4)
        self.assertEqual(r['status'],'skipped');self.assertEqual(out,before);self.assertIs(chunks,c)
    def test_extreme_radius_falls_back(self):
        d,c,b=tube_fixture(body_radius=.2);before=copy.deepcopy(d);out,chunks,r=stitch_neck(d,c,b,1.4)
        self.assertEqual(r['status'],'skipped');self.assertEqual(out,before);self.assertIs(chunks,c)
    def test_neck_expression_is_rejected(self):
        d,c,b=tube_fixture();buf=Buffer(d,c);p=d['meshes'][0]['primitives'][0];n=d['accessors'][p['attributes']['POSITION']]['count']
        delta=np.zeros((n,3));delta[0,0]=.01;p['targets']=[{'POSITION':buf.add(delta,'VEC3')}];c=buf.finish()
        out,chunks,r=stitch_neck(d,c,b,1.4)
        self.assertEqual(r['status'],'skipped');self.assertIn('モーフ',r['reason']);self.assertIs(out,d)
    def test_inconsistent_winding_is_rejected(self):
        d,c,b=tube_fixture();buf=Buffer(d,c);p=d['meshes'][1]['primitives'][0];tri=triangles(buf,p)[:,::-1];p['indices']=buf.add(tri.ravel(),'SCALAR',5125);c=buf.finish()
        out,chunks,r=stitch_neck(d,c,b,1.4)
        self.assertEqual(r['status'],'skipped');self.assertIn('向き',r['reason'])
