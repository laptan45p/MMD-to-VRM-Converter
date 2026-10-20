import copy
import tempfile
import unittest
from pathlib import Path
import numpy as np
from body_template import Buffer, replace_body, active_joints, select_body, BIN
from normalize import normalize, world_matrices
from vrm_core import package_vrm, write_glb, read_glb
from spring_bones import setup_springs


def fixture(scale=1):
    roles=['hips','spine','chest','neck','head']
    roles += [side+part for side in ('left','right') for part in ('UpperArm','LowerArm','Hand','UpperLeg','LowerLeg','Foot')]
    coords={'hips':[0,.8,0],'spine':[0,1,0],'chest':[0,1.2,0],'neck':[0,1.4,0],'head':[0,1.6,0]}
    parents={'spine':'hips','chest':'spine','neck':'chest','head':'neck'}
    for side,sign in [('left',1),('right',-1)]:
        for part,x in [('UpperArm',.2),('LowerArm',.4),('Hand',.6)]:coords[side+part]=[sign*x,1.3,0]
        for part,y in [('UpperLeg',.75),('LowerLeg',.4),('Foot',.05)]:coords[side+part]=[sign*.1,y,0]
        for chain in [('chest',side+'UpperArm',side+'LowerArm',side+'Hand'),('hips',side+'UpperLeg',side+'LowerLeg',side+'Foot')]:
            for a,b in zip(chain,chain[1:]):parents[b]=a
    bones={r:i for i,r in enumerate(roles)};nodes=[]
    for role in roles:
        parent=parents.get(role);pos=np.array(coords[role],dtype=float)*scale
        if parent:pos-=np.array(coords[parent])*scale
        nodes.append({'name':role,'translation':pos.tolist()})
    for role,parent in parents.items():nodes[bones[parent]].setdefault('children',[]).append(bones[role])
    breast=len(nodes);nodes.append({'name':'Breast_L','translation':[.05*scale,0,-.05*scale],'children':[breast+1]})
    nodes.append({'name':'BreastEnd_L','translation':[0,0,-.05*scale]});nodes[bones['chest']].setdefault('children',[]).append(breast)
    d={'asset':{'version':'2.0'},'nodes':nodes,'scenes':[{'nodes':[0]}],'scene':0,
       'buffers':[{'byteLength':0}],'bufferViews':[],'accessors':[],'skins':[],
       'materials':[{'name':'face'},{'name':'body'}],'meshes':[]}
    buf=Buffer(d,[(BIN,b'')]);world,_=world_matrices(d);joints=list(range(len(nodes)))
    inverse=np.array([np.linalg.inv(m).T.reshape(-1) for m in world]);d['skins']=[{'joints':joints,'inverseBindMatrices':buf.add(inverse,'MAT4')}]
    for name,positions,joint,mat in [('Head',[[0,1.5,0],[.1,1.7,0],[-.1,1.7,0]],bones['head'],0),
                                    ('BodySkin',[[0,1.15,-.1],[.1,1.15,-.1],[.05,1.3,-.1]],breast,1)]:
        p={'attributes':{'POSITION':buf.add(np.array(positions)*scale,'VEC3'),
            'NORMAL':buf.add([[0,0,-1]]*3,'VEC3'),
            'JOINTS_0':buf.add([[joint,0,0,0]]*3,'VEC4',5123),
            'WEIGHTS_0':buf.add([[1,0,0,0]]*3,'VEC4')},'indices':buf.add([0,1,2],'SCALAR',5123),'material':mat}
        m={'name':name,'primitives':[p]}
        if name=='Head':
            m['extras']={'targetNames':['まばたき']};p['targets']=[{'POSITION':buf.add([[0,.02,0]]*3,'VEC3')}]
        mi=len(d['meshes']);d['meshes'].append(m);ni=len(nodes);nodes.append({'name':name+'Object','mesh':mi,'skin':0});d['scenes'][0]['nodes'].append(ni)
    c=buf.finish();package_vrm(d,{r:r for r in roles},'fixture','template author','https://example.com/terms')
    return d,c,bones

class BodyTemplateTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'template.vrm'
        self.donor,self.dc,self.db=fixture();write_glb(self.path,self.donor,self.dc)
    def tearDown(self):self.temp.cleanup()
    def source(self,scale=1):
        d,c,b=fixture(scale);c=normalize(d,c,b,lambda _:None);return d,c,b
    def test_head_morph_and_donor_body(self):
        d,c,b=self.source();before=self.path.read_bytes();morph=d['meshes'][0]['primitives'][0]['targets'][0]['POSITION']
        expected=Buffer(d,c).read(morph)
        c,r,mats=replace_body(d,c,b,self.path,log=lambda _:None)
        self.assertEqual(r['keptHeadTriangles'],1);self.assertEqual(r['removedSourceTriangles'],1)
        self.assertEqual([m['name'] for m in d['meshes']],['Head','TemplateBody'])
        np.testing.assert_allclose(Buffer(d,c).read(morph),expected)
        report=package_vrm(d,{r:d['nodes'][i]['name'] for r,i in b.items()},'output','author','')
        self.assertEqual(report['expressions'],['blink']);self.assertEqual(d['extensions']['VRM']['blendShapeMaster']['blendShapeGroups'][0]['binds'][0]['mesh'],0)
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(r['templateMetadata']['author'],'template author')
    def test_rest_bind_and_chest_end(self):
        d,c,b=self.source(1.25);c,r,_=replace_body(d,c,b,self.path,log=lambda _:None)
        buf=Buffer(d,c);skin=d['skins'][-1];world,_=world_matrices(d)
        inv=buf.read(skin['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
        for j,m in zip(skin['joints'],inv):np.testing.assert_allclose(world[j]@m,np.eye(4),atol=1e-6)
        self.assertAlmostEqual(r['scale'],1.25)
        package_vrm(d,{r:d['nodes'][i]['name'] for r,i in b.items()},'output','author','')
        r=setup_springs(d,active_joints=active_joints(d,c))
        roots=[x for x in r['groups'] if x['category']=='chest']
        self.assertEqual(len(roots),1);self.assertTrue(d['nodes'][roots[0]['node']].get('children'))
    def test_coincident_controls_keep_source_skeleton_and_valid_bind(self):
        d,c,b=fixture()
        world,_=world_matrices(d)
        positions=np.array([m[:3,3] for m in world])
        positions[b['hips']]=[0,1,0];positions[b['spine']]=[0,1,0]
        _,parents=world_matrices(d)
        for i,node in enumerate(d['nodes']):
            node['translation']=(positions[i]-(positions[parents[i]] if i in parents else 0)).tolist()
        c=normalize(d,c,b,lambda _:None)
        before,_=world_matrices(d);count=len(d['nodes'])
        c,report,_=replace_body(d,c,b,self.path,log=lambda _:None)
        after,_=world_matrices(d)
        self.assertTrue(report['torsoFit']['adjusted'])
        np.testing.assert_allclose(after[:count],before)
        buf=Buffer(d,c);skin=d['skins'][-1]
        inverse=buf.read(skin['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
        for joint,bind in zip(skin['joints'],inverse):
            np.testing.assert_allclose(after[joint]@bind,np.eye(4),atol=1e-6)

    def test_material_texture_remapping(self):
        d=self.donor;buf=Buffer(d,self.dc)
        d['images']=[{'bufferView':buf.view(b'image bytes'),'mimeType':'image/png'}];d['textures']=[{'source':0}]
        d['materials'][1]['pbrMetallicRoughness']={'baseColorTexture':{'index':0}}
        d['extensions']['VRM']['materialProperties'][1]['textureProperties']={'_MainTex':0}
        write_glb(self.path,d,buf.finish())
        source,c,b=self.source();source['images']=[{'bufferView':0,'mimeType':'image/png'}];source['textures']=[{'source':0}]
        c,r,mats=replace_body(source,c,b,self.path,log=lambda _:None)
        self.assertEqual(source['materials'][-1]['pbrMetallicRoughness']['baseColorTexture']['index'],1)
        self.assertEqual(mats[len(source['materials'])-1]['textureProperties']['_MainTex'],1)
        image=source['images'][1];view=source['bufferViews'][image['bufferView']];data=Buffer(source,c).data
        self.assertEqual(bytes(data[view['byteOffset']:view['byteOffset']+view['byteLength']]),b'image bytes')
    def test_proportion_matching_can_be_disabled_and_keeps_head(self):
        d,c,b=self.source();head=d['meshes'][0]['primitives'][0]['attributes']['POSITION']
        before=Buffer(d,c).read(head)
        c,report,_=replace_body(d,c,b,self.path,{'match_source_proportions':False},log=lambda _:None)
        self.assertEqual(report['proportionMatching']['status'],'disabled')
        np.testing.assert_array_equal(Buffer(d,c).read(head),before)

    def test_missing_neck_rejected(self):
        d,c,b=self.source();b.pop('neck')
        with self.assertRaisesRegex(ValueError,'首'):replace_body(d,c,b,self.path)
    def test_vrm1_rejected(self):
        d=copy.deepcopy(self.donor);d['extensions']={'VRMC_vrm':{}};write_glb(self.path,d,self.dc)
        source,c,b=self.source()
        with self.assertRaisesRegex(ValueError,'VRM 0.x'):replace_body(source,c,b,self.path)
    def test_ambiguous_mesh_requires_name(self):
        d=copy.deepcopy(self.donor);d['meshes'].append(copy.deepcopy(d['meshes'][1]))
        with self.assertRaises(ValueError):select_body(d)
        self.assertEqual(select_body(self.donor,'BodySkin'),1)
    def test_invalid_width_rejected(self):
        for width in (0,float('nan'),2):
            d,c,b=self.source()
            with self.assertRaises(ValueError):replace_body(d,c,b,self.path,{'width':width})
    def test_roundtrip(self):
        d,c,b=self.source();c,r,_=replace_body(d,c,b,self.path,log=lambda _:None)
        p=Path(self.temp.name)/'output.vrm';write_glb(p,d,c);out,chunks=read_glb(p)
        self.assertEqual(out,d);self.assertTrue(active_joints(out,chunks))
