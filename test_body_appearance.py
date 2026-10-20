import tempfile
import unittest
from pathlib import Path
import numpy as np
from body_appearance import (reshape, shape_settings, normals, srgb_to_linear, linear_to_srgb,
    tint_pixels, choose_material, pillow_encode, pillow_decode, skin_plan)
from body_template import Buffer, replace_body, BIN
from test_body_template import fixture
from normalize import normalize, world_matrices
from vrm_core import write_glb

class ShapeTest(unittest.TestCase):
    def setUp(self):
        d,c,b=fixture();w,_=world_matrices(d);self.positions={r:w[i][:3,3] for r,i in b.items()}
    def test_neutral_is_identity(self):
        p=np.array([[.1,.9,.2],[.05,1.2,-.1]])
        np.testing.assert_array_equal(reshape(p,self.positions,shape_settings({}),{'torso':np.ones(2)}),p)
    def test_waist_local_and_arm_envelope(self):
        p=np.array([[.1,.96,.1],[.3,1.35,.1],[.6,1.3,.1]])
        region={'torso':np.array([1,0,0]),'leftUpperArm':np.array([0,1,1])}
        settings=shape_settings({'shape':{'waist':.7,'upper_arms':1.3}})
        out=reshape(p,self.positions,settings,region)
        self.assertLess(out[0,0],p[0,0]);self.assertGreater(out[1,2],p[1,2])
        np.testing.assert_allclose(out[2],p[2]);np.testing.assert_allclose(out[:,1],p[:,1],atol=.02)
    def test_shape_range(self):
        for value in (0,2,float('nan')):
            with self.assertRaises(ValueError):shape_settings({'shape':{'bust':value}})
    def test_normals(self):
        p=np.array([[0.,0,0],[1,0,0],[0,1,0]]);out=normals(p,[0,1,2],np.zeros((3,3)))
        np.testing.assert_allclose(out,[[0,0,1]]*3)

class SkinTest(unittest.TestCase):
    def test_srgb_roundtrip(self):
        p=np.linspace(0,1,256);np.testing.assert_allclose(linear_to_srgb(srgb_to_linear(p)),p,atol=1e-12)
    def test_tint_preserves_alpha_and_detail(self):
        p=np.array([[[.4,.3,.2,.4],[.6,.5,.4,.8]]]);out=tint_pixels(p,{'factor':np.ones(3),'ratio':np.array([1.2,1.1,1.05])})
        np.testing.assert_array_equal(out[:,:,3],p[:,:,3]);self.assertTrue(np.all(out[0,1,:3]>out[0,0,:3]));self.assertTrue(np.all(out[:,:,:3]>p[:,:,:3]))
    def test_material_selection_and_ambiguity(self):
        d={'materials':[{'name':'Faceparts_Front'},{'name':'Hair'},{'name':'Face'},{'name':'BodySkin'}]}
        self.assertEqual(choose_material(d,source=True),3)
        self.assertEqual(choose_material(d,'Face',source=True),2)
        with self.assertRaises(ValueError):choose_material(d,'missing')
        self.assertIsNone(choose_material({'materials':[{'name':'cloth'},{'name':'eye'}]},source=True))
    def test_integrated_texture_match_and_shape(self):
        with tempfile.TemporaryDirectory() as work:
            donor,dc,db=fixture();source,sc,sb=fixture()
            def texture(d,c,color,material,mesh):
                buf=Buffer(d,c);pixels=np.broadcast_to(np.array(color)/255,(4,4,4)).copy();blob=pillow_encode(pixels)
                image=len(d.setdefault('images',[]));d['images'].append({'bufferView':buf.view(blob),'mimeType':'image/png'})
                index=len(d.setdefault('textures',[]));d['textures'].append({'source':image})
                d['materials'][material]['pbrMetallicRoughness']={'baseColorTexture':{'index':index}}
                d['meshes'][mesh]['primitives'][0]['attributes']['TEXCOORD_0']=buf.add([[.25,.25],[.75,.25],[.5,.75]],'VEC2')
                d['extensions']['VRM']['materialProperties'][material]['textureProperties']={'_MainTex':index,'_ShadeTexture':index}
                return buf.finish()
            dc=texture(donor,dc,[180,140,120,255],1,1);sc=texture(source,sc,[235,205,185,255],0,0)
            donor['materials'][1]['normalTexture']={'index':0}
            donor['extensions']['VRM']['materialProperties'][1]['textureProperties']['_BumpMap']=0
            path=Path(work)/'body.vrm';write_glb(path,donor,dc)
            sc=normalize(source,sc,sb,lambda _:None)
            original_positions=Buffer(source,sc).read(source['meshes'][0]['primitives'][0]['attributes']['POSITION']).copy()
            sc,report,properties=replace_body(source,sc,sb,path,{'skin_strength':1,'shape':{'bust':1.2}},lambda _:None)
            self.assertEqual(report['skinMatching']['status'],'applied');self.assertEqual(report['shape']['bust'],1.2)
            buf=Buffer(source,sc);mat=source['materials'][-1];tex=source['textures'][mat['pbrMetallicRoughness']['baseColorTexture']['index']];im=source['images'][tex['source']];view=source['bufferViews'][im['bufferView']]
            corrected=pillow_decode(bytes(buf.data[view['byteOffset']:view['byteOffset']+view['byteLength']]),'image/png')
            np.testing.assert_allclose(corrected[0,0],np.array([235,205,185,255])/255,atol=1/255)
            np.testing.assert_array_equal(buf.read(source['meshes'][0]['primitives'][0]['attributes']['POSITION']),original_positions)
            self.assertEqual(properties[len(source['materials'])-1]['vectorProperties']['_Color'][:3],[1,1,1])
            self.assertNotEqual(mat['normalTexture']['index'],mat['pbrMetallicRoughness']['baseColorTexture']['index'])
            normal_image=source['images'][source['textures'][mat['normalTexture']['index']]['source']];nv=source['bufferViews'][normal_image['bufferView']]
            normal_pixels=pillow_decode(bytes(buf.data[nv['byteOffset']:nv['byteOffset']+nv['byteLength']]),'image/png')
            np.testing.assert_allclose(normal_pixels[0,0],np.array([180,140,120,255])/255,atol=1/255)
            np.testing.assert_allclose(properties[len(source['materials'])-1]['vectorProperties']['_ShadeColor'][:3],[.8,.8,.8])
            self.assertTrue(np.isfinite(buf.read(source['meshes'][-1]['primitives'][0]['attributes']['NORMAL'])).all())
    def test_disabled_skin_and_invalid_strength(self):
        donor,dc,db=fixture();source,sc,sb=fixture()
        p,r=skin_plan(source,Buffer(source,sc),donor,Buffer(donor,dc),{1},{'skin_match':False},pillow_decode)
        self.assertEqual(p,{});self.assertEqual(r['status'],'disabled')
        with self.assertRaises(ValueError):skin_plan(source,Buffer(source,sc),donor,Buffer(donor,dc),{1},{'skin_strength':2},pillow_decode)
