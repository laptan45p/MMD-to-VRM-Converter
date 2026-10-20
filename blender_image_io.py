"""Use Blender's native image codecs; no Pillow install is needed by users."""
from pathlib import Path
import uuid
import numpy as np

class BlenderImages:
    def __init__(self, work):self.work=Path(work)
    def decode(self,blob,mime):
        import bpy
        path=self.work/('skin-read-'+uuid.uuid4().hex+('.jpg' if mime=='image/jpeg' else '.png'));image=None
        try:
            path.write_bytes(blob);image=bpy.data.images.load(str(path),check_existing=False)
            # Read encoded channel values rather than scene-linear colors.
            image.colorspace_settings.name='Non-Color'
            w,h=image.size;data=np.empty(w*h*4,dtype=np.float32);image.pixels.foreach_get(data)
            return data.reshape(h,w,4)[::-1].copy()
        finally:
            if image is not None:bpy.data.images.remove(image)
            path.unlink(missing_ok=True)
    def encode(self,pixels):
        import bpy
        path=self.work/('skin-write-'+uuid.uuid4().hex+'.png');image=None
        try:
            h,w=pixels.shape[:2];image=bpy.data.images.new('Skin tint temporary',width=w,height=h,alpha=True,float_buffer=False)
            image.colorspace_settings.name='Non-Color'
            image.pixels.foreach_set(np.ascontiguousarray(np.clip(pixels[::-1],0,1),dtype=np.float32).ravel())
            image.filepath_raw=str(path);image.file_format='PNG';image.save()
            return path.read_bytes()
        finally:
            if image is not None:bpy.data.images.remove(image)
            path.unlink(missing_ok=True)
