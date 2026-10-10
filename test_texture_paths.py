import tempfile
import unittest
from pathlib import Path
from texture_paths import texture_path

class TexturePathTest(unittest.TestCase):
    def test_sibling_folder(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);model=root/'PMX'/'かなた.pmx'
            expected=root/'texture'/'TEX_PPT_Metal.tga'
            self.assertEqual(texture_path(model,r'..\texture\TEX_PPT_Metal.tga',root),expected.resolve())
    def test_package_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);model=root/'PMX'/'m.pmx'
            with self.assertRaises(ValueError):texture_path(model,r'..\..\outside.png',root)
    def test_absolute_paths_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ['C:\\texture.png','/etc/file.png',r'\\server\share\a.png']:
                with self.assertRaises(ValueError):texture_path(Path(d)/'m.pmx',name,d)

if __name__=='__main__':unittest.main()
