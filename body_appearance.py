"""Body proportions and texture-aware skin tint; no Blender dependency here."""
import io
import math
import re
import numpy as np

SHAPE_KEYS=('bust','waist','hips','thighs','upper_arms','neck')

def shape_settings(options):
    supplied=options.get('shape',{});result={}
    for key in SHAPE_KEYS:
        value=float(supplied.get(key,1))
        if not math.isfinite(value) or not .5<=value<=1.5:raise ValueError('体型倍率は0.5〜1.5にしてください: '+key)
        result[key]=value
    return result

def reshape(points, positions, settings, regions):
    """Scale soft tissue cross-sections, preserving the skeleton's joint anchors."""
    p=np.asarray(points,dtype=float);result=p.copy()
    hips=positions['hips'];chest=positions.get('chest',positions['spine']);neck=positions['neck']
    height=max(neck[1]-hips[1],.05)
    torso=np.asarray(regions.get('torso',np.zeros(len(p))))
    pelvic=np.asarray(regions.get('pelvis',torso))
    breast=np.asarray(regions.get('breast',np.zeros(len(p))))
    def gaussian(y,sigma):return np.exp(-.5*((p[:,1]-y)/max(sigma,1e-5))**2)
    centers={'waist':hips*.6+chest*.4,'hips':hips,'bust':chest,'neck':neck}
    envelopes={'waist':torso*gaussian(centers['waist'][1],height*.16),
        'hips':pelvic*gaussian(hips[1],height*.18),
        'neck':torso*gaussian(neck[1],height*.13)}
    front=np.clip((chest[2]-p[:,2])/(height*.08),0,1)
    envelopes['bust']=np.maximum(breast,torso*front*gaussian(chest[1]+height*.07,height*.15)*.5)
    delta=np.zeros_like(p)
    for key in ('waist','hips','bust','neck'):
        weight=(settings[key]-1)*envelopes[key]
        radial=p-centers[key];radial[:,1]=0
        delta+=radial*weight[:,None]
    result+=delta
    for key,start,end in [('thighs','UpperLeg','LowerLeg'),('upper_arms','UpperArm','LowerArm')]:
        if settings[key]==1:continue
        for side in ('left','right'):
            a=positions[side+start];b=positions[side+end];axis=b-a;length=np.linalg.norm(axis)
            if length<1e-6:continue
            axis/=length;t=(p-a)@axis/length
            center=a+(t*length)[:,None]*axis;radial=p-center
            envelope=np.sin(np.pi*np.clip(t,0,1))**1.5
            weight=np.asarray(regions.get(side+start,np.zeros(len(p))))
            result+=radial*((settings[key]-1)*envelope*weight)[:,None]
    return result

def normals(points, indices, fallback):
    tri=np.asarray(indices).reshape(-1,3);out=np.zeros_like(points,dtype=float)
    cross=np.cross(points[tri[:,1]]-points[tri[:,0]],points[tri[:,2]]-points[tri[:,0]])
    for column in range(3):np.add.at(out,tri[:,column],cross)
    size=np.linalg.norm(out,axis=1);valid=size>1e-12
    out[valid]/=size[valid,None];out[~valid]=fallback[~valid]
    return out

def srgb_to_linear(value):
    value=np.asarray(value,dtype=float)
    return np.where(value<=.04045,value/12.92,((value+.055)/1.055)**2.4)

def linear_to_srgb(value):
    value=np.clip(value,0,1)
    return np.where(value<=.0031308,value*12.92,1.055*value**(1/2.4)-.055)

def pillow_decode(blob,mime):
    from PIL import Image
    return np.asarray(Image.open(io.BytesIO(blob)).convert('RGBA'),dtype=float)/255

def pillow_encode(pixels):
    from PIL import Image
    f=io.BytesIO();Image.fromarray(np.round(np.clip(pixels,0,1)*255).astype('uint8')).save(f,format='PNG')
    return f.getvalue()

def image_bytes(doc,buf,index):
    value=doc['images'][index]
    if 'bufferView' not in value or 'uri' in value:raise ValueError('肌色補正は埋め込み画像のみ対応します。')
    view=doc['bufferViews'][value['bufferView']];start=view.get('byteOffset',0)
    return bytes(buf.data[start:start+view['byteLength']]),value.get('mimeType','image/png')

def choose_material(doc, supplied='', allowed=None, source=False):
    materials=doc.get('materials',[]);allowed=set(range(len(materials))) if allowed is None else set(allowed)
    if supplied:
        matches=[i for i in allowed if materials[i].get('name')==supplied]
        if len(matches)!=1:raise ValueError('肌材質を特定できません: '+supplied+' / 候補: '+', '.join(materials[i].get('name',str(i)) for i in sorted(allowed)))
        return matches[0]
    scores=[]
    for i in sorted(allowed):
        name=materials[i].get('name','').casefold()
        if re.search(r'hair|eye|lash|brow|mouth|teeth|tongue|faceparts|face_parts|trance|髪|目|眉|口|歯|舌|服|衣装',name):continue
        score=3 if re.search(r'skin|肌|素体',name) else 2 if re.search(r'face|顔',name) else 0
        if score:scores.append((score,i))
    if scores:
        high=max(score for score,_ in scores);matches=[i for score,i in scores if score==high]
        if len(matches)==1:return matches[0]
    if not source and len(allowed)==1:return next(iter(allowed))
    return None

def sample_color(doc,buf,material,decode):
    mat=doc['materials'][material];pbr=mat.get('pbrMetallicRoughness',{});factor=np.asarray(pbr.get('baseColorFactor',[1,1,1,1]))[:3]
    info=pbr.get('baseColorTexture')
    if info is None:return factor
    coords=[]
    extension=info.get('extensions',{}).get('KHR_texture_transform',{})
    semantic='TEXCOORD_'+str(extension.get('texCoord',info.get('texCoord',0)))
    for mesh in doc['meshes']:
        for p in mesh['primitives']:
            if p.get('material')!=material or semantic not in p['attributes']:continue
            uv=buf.read(p['attributes'][semantic]);n=len(uv)
            index=buf.read(p['indices']).ravel().astype(int) if 'indices' in p else np.arange(n)
            if len(index)%3:continue
            tri=index.reshape(-1,3)
            if len(tri)>4096:tri=tri[np.linspace(0,len(tri)-1,4096).astype(int)]
            coords.extend([uv[tri].mean(axis=1),uv[tri[:,0]],uv[tri[:,1]],uv[tri[:,2]]])
    if not coords:raise ValueError('肌材質のUVを取得できません。')
    uv=np.concatenate(coords);uv*=extension.get('scale',[1,1]);angle=extension.get('rotation',0)
    uv=uv@np.array([[math.cos(angle),math.sin(angle)],[-math.sin(angle),math.cos(angle)]])
    uv+=extension.get('offset',[0,0])
    texture=doc['textures'][info['index']];sampler=doc.get('samplers',[])[texture['sampler']] if 'sampler' in texture else {}
    for column,key in enumerate(('wrapS','wrapT')):
        mode=sampler.get(key,10497)
        if mode==33071:uv[:,column]=np.clip(uv[:,column],0,1)
        elif mode==33648:uv[:,column]=1-np.abs(np.mod(uv[:,column],2)-1)
        else:uv[:,column]=np.mod(uv[:,column],1)
    blob,mime=image_bytes(doc,buf,texture['source']);pixels=decode(blob,mime)
    h,w=pixels.shape[:2];xy=np.floor(uv*np.array([w,h])).astype(int);xy[:,0]=np.clip(xy[:,0],0,w-1);xy[:,1]=np.clip(xy[:,1],0,h-1)
    rgba=pixels[xy[:,1],xy[:,0]];rgb=rgba[:,:3];v=rgb.max(1);s=(v-rgb.min(1))/np.maximum(v,1e-6)
    mask=(rgba[:,3]>.5)&(v>.25)&(s<.65)
    if mask.sum()<3:raise ValueError('肌の代表色を十分に検出できません。')
    rgb=rgb[mask];bins=np.floor(rgb*15).astype(int);keys=bins[:,0]*256+bins[:,1]*16+bins[:,2]
    values,counts=np.unique(keys,return_counts=True);dominant=values[np.argmax(counts)]
    return np.median(srgb_to_linear(rgb[keys==dominant]),axis=0)*factor

def skin_plan(source,src,donor,dst,body_materials,options,decode):
    strength=float(options.get('skin_strength',.8))
    if not math.isfinite(strength) or not 0<=strength<=1:raise ValueError('肌色補正の強さは0〜1にしてください。')
    report={'enabled':bool(options.get('skin_match',True)),'strength':strength,'status':'disabled','warnings':[]};plans={}
    report['sourceCandidates']=[m.get('name',str(i)) for i,m in enumerate(source.get('materials',[]))]
    report['templateCandidates']=[donor['materials'][i].get('name',str(i)) for i in sorted(body_materials)]
    if not report['enabled'] or strength==0:return plans,report
    si=choose_material(source,str(options.get('source_skin_material') or '').strip(),source=True)
    di=choose_material(donor,str(options.get('template_skin_material') or '').strip(),body_materials)
    if si is None or di is None:
        report['status']='not_detected';report['warnings'].append('肌材質を自動判定できませんでした。詳細設定で元MMDと補完素体の肌材質名を指定してください。')
        return plans,report
    report.update(sourceMaterial=source['materials'][si].get('name'),templateMaterial=donor['materials'][di].get('name'))
    try:
        target=sample_color(source,src,si,decode);base=sample_color(donor,dst,di,decode)
        ratio=np.clip(target/np.maximum(base,1e-4),.25,4)**strength
        plans[di]={'ratio':ratio,'factor':np.asarray(donor['materials'][di].get('pbrMetallicRoughness',{}).get('baseColorFactor',[1,1,1,1]))[:3]}
        report.update(status='applied',sourceRGB=np.round(linear_to_srgb(target)*255).astype(int).tolist(),
            templateRGB=np.round(linear_to_srgb(base)*255).astype(int).tolist(),linearGain=ratio.tolist())
        if np.any(np.isclose(ratio,.25**strength)|np.isclose(ratio,4**strength)):
            report['warnings'].append('肌色の差が大きいため補正量を制限しました。肌材質の選択を確認してください。')
    except (ValueError,RuntimeError,OSError) as error:
        report['status']='sample_failed';report['warnings'].append('肌色補正を省略: '+str(error))
    return plans,report

def tint_pixels(pixels,plan):
    out=np.asarray(pixels,dtype=float).copy()
    out[:,:,:3]=linear_to_srgb(srgb_to_linear(out[:,:,:3])*plan['factor']*plan['ratio'])
    return out
