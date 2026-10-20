import tempfile
import unittest
import zipfile
from pathlib import Path
from template_source import resolve_template
from bone_mapping import map_bones
from vrm_core import MAP

class TemplateSourceTest(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def archive(self,files):
        path=self.root/'template.zip'
        with zipfile.ZipFile(path,'w') as z:
            for name,data in files.items():z.writestr(name,data)
        return path
    def test_base_body_texture_is_preferred(self):
        path=self.archive({'asset/body.fbx':b'fbx','asset/BaseBody/Skin1.png':b'base','asset/Body_Cloth/Skin1.png':b'clothing','asset/BaseBody/Skin2.png':b'other','asset/large.psd':b'not required','asset/project.unitypackage':b'not required'})
        model,texture,r=resolve_template(path,self.root/'work')
        self.assertEqual(model.name,'body.fbx');self.assertEqual(texture.parent.name,'BaseBody');self.assertEqual(texture.read_bytes(),b'base')
        self.assertEqual(r['format'],'fbx');self.assertFalse(list((self.root/'work').rglob('*.psd')));self.assertFalse(list((self.root/'work').rglob('*.unitypackage')))
    def test_explicit_texture_override(self):
        path=self.archive({'body.fbx':b'fbx','BaseBody/Skin1.png':b'base'})
        override=self.root/'custom.png';override.write_bytes(b'custom')
        _,texture,_=resolve_template(path,self.root/'work',{'fbx_texture':str(override)})
        self.assertEqual(texture,override)
    def test_vrm_in_zip_needs_no_texture(self):
        model,texture,r=resolve_template(self.archive({'template.vrm':b'vrm'}),self.root/'work')
        self.assertEqual(model.suffix,'.vrm');self.assertIsNone(texture)
    def test_bad_zip_path_is_rejected(self):
        with self.assertRaises(ValueError):resolve_template(self.archive({'../outside.fbx':b'bad'}),self.root/'work')
        self.assertFalse((self.root/'outside.fbx').exists())
    def test_multiple_models_are_rejected(self):
        with self.assertRaises(ValueError):resolve_template(self.archive({'a.fbx':b'a','b.fbx':b'b'}),self.root/'work')
    def test_clothing_texture_is_not_automatically_selected(self):
        path=self.archive({'body.fbx':b'fbx','Body_Cloth/Skin1.png':b'clothing'})
        with self.assertRaisesRegex(ValueError,'肌テクスチャ'):resolve_template(path,self.root/'work')
    def test_english_prefixed_bones(self):
        aliases={}
        for role in MAP:
            name=role
            for side,prefix in [('left','L_'),('right','R_')]:
                if role.startswith(side):
                    name=prefix+role[len(side):]
                    if name.endswith('Toes'):name=name[:-1]
            aliases[name]=role
        mapping,warnings=map_bones(aliases)
        self.assertEqual(set(mapping),set(MAP));self.assertFalse(warnings)
