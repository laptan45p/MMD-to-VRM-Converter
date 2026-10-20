import copy
import tempfile
import unittest
from pathlib import Path
import numpy as np
from test_body_template import fixture
from body_template import Buffer
from head_transplant import transplant_head
from normalize import normalize,world_matrices
from vrm_core import write_glb,package_vrm,read_glb


class HeadTransplantTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'template.vrm'
        self.donor,self.dc,self.db=fixture();write_glb(self.path,self.donor,self.dc)
    def tearDown(self):self.temp.cleanup()
    def source(self):
        d,c,b=fixture(1.25);return d,normalize(d,c,b,lambda _:None),b
    def test_donor_body_vertices_weights_and_skeleton_are_preserved(self):
        expected=copy.deepcopy(self.donor);ec=normalize(expected,self.dc,self.db,lambda _:None)
        world,_=world_matrices(expected);e=Buffer(expected,ec)
        d,c,b=self.source();c,report,props=transplant_head(d,c,b,self.path,log=lambda _:None)
        actual,_=world_matrices(d);np.testing.assert_allclose(actual[:len(world)],world)
        buf=Buffer(d,c);primitive=d['meshes'][0]['primitives'][0]
        for key,index in expected['meshes'][1]['primitives'][0]['attributes'].items():
            np.testing.assert_array_equal(buf.read(primitive['attributes'][key]),e.read(index))
        self.assertEqual(b,self.db);self.assertEqual(report['assemblyBasis'],'template')
    def test_head_and_expression_are_uniformly_scaled(self):
        d,c,b=self.source();buf=Buffer(d,c);p=d['meshes'][0]['primitives'][0]
        positions=buf.read(p['attributes']['POSITION']);delta=buf.read(p['targets'][0]['POSITION'])
        c,report,_=transplant_head(d,c,b,self.path,log=lambda _:None);out=Buffer(d,c)
        p=d['meshes'][1]['primitives'][0]
        np.testing.assert_allclose(out.read(p['attributes']['POSITION']),positions*report['headScale']+report['headTranslation'],atol=1e-6)
        np.testing.assert_allclose(out.read(p['targets'][0]['POSITION']),delta*report['headScale'],atol=1e-6)
        report=package_vrm(d,{r:d['nodes'][i]['name'] for r,i in b.items()},'output','author','')
        self.assertIn('blink',report['expressions'])
        self.assertEqual(d['extensions']['VRM']['blendShapeMaster']['blendShapeGroups'][0]['binds'][0]['mesh'],1)
    def test_rest_inverse_binds_are_identity(self):
        d,c,b=self.source();c,r,_=transplant_head(d,c,b,self.path,log=lambda _:None)
        world,_=world_matrices(d);buf=Buffer(d,c)
        for skin in d['skins']:
            inverse=buf.read(skin['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
            for joint,matrix in zip(skin['joints'],inverse):np.testing.assert_allclose(world[joint]@matrix,np.eye(4),atol=1e-6)
    def test_head_hair_hierarchy_is_attached_to_template_head(self):
        d,c,b=self.source();hair=len(d['nodes'])
        d['nodes'].extend([{'name':'Hair','translation':[0,.05,0],'children':[hair+1]},{'name':'HairEnd','translation':[0,-.1,0]}]);d['nodes'][b['head']].setdefault('children',[]).append(hair)
        before,_=world_matrices(d)
        c,r,_=transplant_head(d,c,b,self.path,log=lambda _:None);after,parents=world_matrices(d)
        root=next(i for i,n in enumerate(d['nodes']) if n.get('name')=='MMDHead_Hair')
        self.assertEqual(parents[root],b['head']);self.assertTrue(d['nodes'][root]['children'])
        np.testing.assert_allclose(after[root][:3,3],before[hair][:3,3]*r['headScale']+r['headTranslation'],atol=1e-6)
    def test_original_body_fitting_settings_have_no_effect(self):
        a,c,b=self.source();c,r,_=transplant_head(a,c,b,self.path,{'width':.5,'shape':{'bust':1.5},'match_source_proportions':True},log=lambda _:None)
        d,dc,db=self.source();dc,rr,_=transplant_head(d,dc,db,self.path,log=lambda _:None)
        for pa,pb in zip(a['meshes'][0]['primitives'],d['meshes'][0]['primitives']):
            np.testing.assert_array_equal(Buffer(a,c).read(pa['attributes']['POSITION']),Buffer(d,dc).read(pb['attributes']['POSITION']))
    def test_invalid_head_scale_is_rejected(self):
        for scale in (0,2,float('nan')):
            d,c,b=self.source()
            with self.assertRaises(ValueError):transplant_head(d,c,b,self.path,{'head_scale':scale})
    def test_roundtrip(self):
        d,c,b=self.source();c,r,_=transplant_head(d,c,b,self.path,log=lambda _:None)
        path=Path(self.temp.name)/'output.vrm';write_glb(path,d,c);out,chunks=read_glb(path)
        self.assertEqual(out,d)
    def test_head_textures_remap_without_changing_body_texture(self):
        donor=copy.deepcopy(self.donor);buf=Buffer(donor,self.dc)
        donor['images']=[{'bufferView':buf.view(b'donor pixels'),'mimeType':'image/png'}]
        donor['textures']=[{'source':0}];donor['materials'][1]['pbrMetallicRoughness']={'baseColorTexture':{'index':0}}
        donor['extensions']['VRM']['materialProperties'][1]['textureProperties']={'_MainTex':0}
        write_glb(self.path,donor,buf.finish())
        d,c,b=self.source();buf=Buffer(d,c)
        d['images']=[{'bufferView':buf.view(b'head pixels'),'mimeType':'image/png'}]
        d['textures']=[{'source':0}];d['materials'][0]['pbrMetallicRoughness']={'baseColorTexture':{'index':0}}
        c,r,props=transplant_head(d,buf.finish(),b,self.path,log=lambda _:None)
        body=d['meshes'][0]['primitives'][0];head=d['meshes'][1]['primitives'][0]
        bt=d['materials'][body['material']]['pbrMetallicRoughness']['baseColorTexture']['index']
        ht=d['materials'][head['material']]['pbrMetallicRoughness']['baseColorTexture']['index']
        self.assertEqual(bt,0);self.assertEqual(ht,1);self.assertEqual(props[1]['textureProperties']['_MainTex'],0)
        out=Buffer(d,c)
        for index,expected in ((bt,b'donor pixels'),(ht,b'head pixels')):
            image=d['images'][d['textures'][index]['source']];view=d['bufferViews'][image['bufferView']];start=view['byteOffset']
            self.assertEqual(bytes(out.data[start:start+view['byteLength']]),expected)
    def test_long_hair_with_body_control_weights_remains_and_follows_head(self):
        d,c,b=self.source();buf=Buffer(d,c)
        d['materials'].append({'name':'back_hair'})
        primitive={'attributes':{'POSITION':buf.add([[0,1.9,0],[.05,1.1,0],[-.05,1.1,0]],'VEC3'),
            'NORMAL':buf.add([[0,0,-1]]*3,'VEC3'),
            'JOINTS_0':buf.add([[b['chest'],0,0,0]]*3,'VEC4',5123),
            'WEIGHTS_0':buf.add([[1,0,0,0]]*3,'VEC4')},'indices':buf.add([0,1,2],'SCALAR',5123),'material':2}
        d['meshes'][0]['primitives'].append(primitive)
        c,r,_=transplant_head(d,buf.finish(),b,self.path,log=lambda _:None)
        self.assertEqual(r['retainedHairTriangles'],1)
        mesh=d['meshes'][1];hair=next(p for p in mesh['primitives'] if d['materials'][p['material']]['name']=='MMDHead_back_hair')
        node=next(n for n in d['nodes'] if n.get('mesh')==1);skin=d['skins'][node['skin']];out=Buffer(d,c)
        js=out.read(hair['attributes']['JOINTS_0']).astype(int);ws=out.read(hair['attributes']['WEIGHTS_0'])
        self.assertEqual(set(np.array(skin['joints'])[js[ws>0]]),{b['head']})
        np.testing.assert_allclose(out.read(hair['attributes']['POSITION'])[:,1],np.array([1.9,1.1,1.1])*r['headScale']+r['headTranslation'][1],atol=1e-6)
