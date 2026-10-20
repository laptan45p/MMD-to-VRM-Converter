"""Experimental VRM0 body replacement after source T-pose normalization.

The donor stays external. This is skeletal fitting, not mesh reconstruction or
surface welding. Source head morph accessors and their mesh ordering survive.
"""
import copy
import math
import re
import numpy as np
from normalize import normalize, world_matrices
from vrm_core import read_glb, REQUIRED
from body_appearance import (shape_settings, reshape, normals, skin_plan, image_bytes,
    pillow_decode, pillow_encode, tint_pixels)

BIN = 0x004E4942
DTYPES = {5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}
WIDTHS = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}

class Buffer:
    def __init__(self, doc, chunks):
        self.doc = doc
        self.data = bytearray(next(b for k,b in chunks if k == BIN))
        if len(doc.get('buffers', [])) != 1 or doc['buffers'][0].get('uri'):
            raise ValueError('素体モードは埋め込みバッファ1個のGLBのみ対応します。')
    def view(self, blob):
        self.data.extend(b'\0'*(-len(self.data)%4)); offset = len(self.data); self.data.extend(blob)
        views = self.doc.setdefault('bufferViews', [])
        views.append({'buffer':0,'byteOffset':offset,'byteLength':len(blob)})
        return len(views)-1
    def read(self, index):
        a = self.doc['accessors'][index]; width = WIDTHS[a['type']]; dtype = DTYPES[a['componentType']]
        def values(view, offset, count, width, dtype):
            v = self.doc['bufferViews'][view]
            if v.get('buffer',0) != 0: raise ValueError('External buffer is unsupported')
            stride = v.get('byteStride',width*np.dtype(dtype).itemsize)
            return np.ndarray((count,width),dtype=dtype,buffer=self.data,
                offset=v.get('byteOffset',0)+offset,strides=(stride,np.dtype(dtype).itemsize)).copy()
        result = values(a['bufferView'],a.get('byteOffset',0),a['count'],width,dtype) if 'bufferView' in a else np.zeros((a['count'],width),dtype=dtype)
        if 'sparse' in a:
            s=a['sparse'];i=s['indices'];v=s['values']
            idx=values(i['bufferView'],i.get('byteOffset',0),s['count'],1,DTYPES[i['componentType']]).ravel()
            result[idx]=values(v['bufferView'],v.get('byteOffset',0),s['count'],width,dtype)
        if a.get('normalized') and a['componentType'] != 5126:
            result=np.maximum(result.astype(float)/np.iinfo(dtype).max,-1)
        return result
    def add(self, data, kind, component=5126):
        array = np.ascontiguousarray(data,dtype=DTYPES[component]).reshape(-1,WIDTHS[kind])
        a={'bufferView':self.view(array.tobytes()),'componentType':component,'type':kind,'count':len(array)}
        if kind == 'VEC3' and len(array): a.update(min=array.min(axis=0).tolist(),max=array.max(axis=0).tolist())
        aa=self.doc.setdefault('accessors',[]);aa.append(a);return len(aa)-1
    def finish(self):
        self.doc['buffers'][0]['byteLength']=len(self.data)
        return [(BIN, bytes(self.data))]

def triangles(buf, primitive):
    if primitive.get('mode',4) != 4: raise ValueError('素体モードは三角形メッシュのみ対応します。')
    n=buf.doc['accessors'][primitive['attributes']['POSITION']]['count']
    idx=buf.read(primitive['indices']).ravel().astype(int) if 'indices' in primitive else np.arange(n)
    if len(idx)%3 or np.any(idx<0) or np.any(idx>=n): raise ValueError('Invalid triangle indices')
    return idx.reshape(-1,3)

def descendants(nodes, root):
    result=set();pending=[root]
    while pending:
        i=pending.pop()
        if i in result: continue
        result.add(i);pending.extend(nodes[i].get('children',[]))
    return result

def influences(buf, primitive, skin):
    attr=primitive['attributes'];js=[];ws=[]
    for suffix in ('0','1'):
        if 'JOINTS_'+suffix in attr:
            js.append(buf.read(attr['JOINTS_'+suffix]).astype(int));ws.append(buf.read(attr['WEIGHTS_'+suffix]).astype(float))
    if not js: raise ValueError('素体モードにはウェイト付きメッシュが必要です。')
    js=np.concatenate(js,axis=1);ws=np.concatenate(ws,axis=1)
    if np.any(js<0) or np.any(js>=len(skin['joints'])) or np.any(ws<0) or not np.isfinite(ws).all(): raise ValueError('Invalid skin weights')
    totals=ws.sum(axis=1)
    if np.any(totals<1e-8): raise ValueError('Unweighted vertices')
    return js,ws/totals[:,None]

def active_joints(doc, chunks):
    buf=Buffer(doc,chunks);active=set()
    for node in doc['nodes']:
        if 'mesh' not in node or 'skin' not in node: continue
        skin=doc['skins'][node['skin']]
        for p in doc['meshes'][node['mesh']]['primitives']:
            used=np.unique(triangles(buf,p));js,ws=influences(buf,p,skin)
            active.update(np.array(skin['joints'])[js[used][ws[used]>1e-5]].tolist())
    return active

def rotation_between(a,b):
    a=a/np.linalg.norm(a);b=b/np.linalg.norm(b);cos=float(np.dot(a,b))
    if cos < -0.99999:
        axis=np.cross(a,[1.,0,0] if abs(a[0])<.9 else [0.,1,0]);axis/=np.linalg.norm(axis)
        return 2*np.outer(axis,axis)-np.eye(3)
    cross=np.cross(a,b);x,y,z=cross;k=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return np.eye(3)+k+k@k/(1+cos)

def select_body(doc, mesh_name=''):
    meshes=doc['meshes']
    if mesh_name:
        matches=[i for i,m in enumerate(meshes) if m.get('name')==mesh_name]
    else:
        matches=[i for i,m in enumerate(meshes) if re.search(r'bodyskin|nakedbody|body_naked|素体',m.get('name',''),re.I)]
        if not matches:
            matches=[i for i,m in enumerate(meshes) if re.search(r'^body(?:[._ -]|$)',m.get('name',''),re.I)]
    if len(matches)!=1:
        raise ValueError('補完VRMの体メッシュを1個に特定できません。「体メッシュ名」に指定してください。候補: '+', '.join(m.get('name',str(i)) for i,m in enumerate(meshes)))
    return matches[0]

def replace_body(doc, chunks, bones, template_path, options=None, log=print, image_decode=None, image_encode=None):
    """Mutates normalized source; returns chunks, report and donor metadata."""
    options=options or {}; offset=float(options.get('neck_offset',0)); width=float(options.get('width',1))
    if not math.isfinite(offset) or not -.1<=offset<=.1 or not math.isfinite(width) or not .5<=width<=1.5:
        raise ValueError('首の境界は-0.1〜0.1m、体の幅は0.5〜1.5にしてください。')
    shapes=shape_settings(options);shaped=any(v!=1 for v in shapes.values())
    image_decode=image_decode or pillow_decode;image_encode=image_encode or pillow_encode
    if 'neck' not in bones: raise ValueError('素体モードには元モデルの首ボーンが必要です。')
    donor,dc=read_glb(template_path)
    vrm=donor.get('extensions',{}).get('VRM')
    if not vrm: raise ValueError('補完用VRMはVRM 0.xを指定してください。VRM 1.0は未対応です。')
    db={b['bone']:b['node'] for b in vrm['humanoid']['humanBones']}
    missing=[r for r in REQUIRED+['neck'] if r not in db]
    if missing: raise ValueError('補完VRMの人型ボーンが不足: '+', '.join(missing))
    selected=select_body(donor,options.get('mesh_name','').strip())
    instances=[n for n in donor['nodes'] if n.get('mesh')==selected]
    if len(instances)!=1 or 'skin' not in instances[0]: raise ValueError('補完の体メッシュはスキン付き1個にしてください。')
    dc=normalize(donor,dc,db,log)
    src=Buffer(doc,chunks);dst=Buffer(donor,dc)
    sw,sp=world_matrices(doc);dw,dp=world_matrices(donor)
    spos=np.array([m[:3,3] for m in sw]);dpos=np.array([m[:3,3] for m in dw])
    height=float(spos[bones['neck'],1]-spos[bones['hips'],1]);dh=float(dpos[db['neck'],1]-dpos[db['hips'],1])
    if height<.03 or dh<.03: raise ValueError('腰から首の高さが不正です。')
    scale=height/dh
    if not .1<scale<10: raise ValueError('元モデルと補完素体の大きさが大幅に異なります。')
    # Segment transforms match named joints; transverse scale preserves donor shape.
    targets={j:bones[r] for r,j in db.items() if r in bones}
    matrices={}
    for j,target in targets.items():
        ends=[k for k in targets if dp.get(k)==j]
        # Prefer the torso chain over shoulders/legs when fitting hips and chest.
        role=next(r for r,n in db.items() if n==j)
        preferred={'hips':'spine','spine':'chest','chest':'neck','neck':'head'}
        if role in preferred and db.get(preferred[role]) in ends: ends=[db[preferred[role]]]
        elif len(ends)!=1: ends=[]
        linear=np.eye(3)*scale;axis=np.array([0.,1,0])
        if ends:
            end=ends[0];a=dpos[end]-dpos[j];b=spos[targets[end]]-spos[target]
            if min(np.linalg.norm(a),np.linalg.norm(b))>1e-6:
                unit=a/np.linalg.norm(a);axis=unit;ratio=np.linalg.norm(b)/np.linalg.norm(a)
                linear=rotation_between(a,b)@(np.eye(3)*scale+(ratio-scale)*np.outer(unit,unit))
        # Width/depth adjustment keeps target bone anchors fixed.
        linear=linear@(np.eye(3)*width+(1-width)*np.outer(axis,axis))
        m=np.eye(4);m[:3,:3]=linear;m[:3,3]=spos[target]-linear@dpos[j];matrices[j]=m
    def anchor(j):
        seen=set()
        while j not in matrices:
            if j not in dp or j in seen: raise ValueError('補完ボーンを人型骨格に対応付けできません。')
            seen.add(j);j=dp[j]
        return j
    dskin=donor['skins'][instances[0]['skin']];joint_map={};new_positions={}
    existing_names={n.get('name') for n in doc['nodes']}
    def map_joint(j):
        if j in joint_map:return joint_map[j]
        if j in targets:joint_map[j]=targets[j];return targets[j]
        a=anchor(j);m=matrices[a];pos=m[:3,:3]@dpos[j]+m[:3,3]
        parent=map_joint(dp[j]);parent_pos=new_positions.get(parent,spos[parent] if parent<len(spos) else None)
        name='Template_'+donor['nodes'][j].get('name',str(j))
        while name in existing_names:name+='_'
        existing_names.add(name);idx=len(doc['nodes'])
        doc['nodes'].append({'name':name,'translation':(pos-parent_pos).tolist()})
        doc['nodes'][parent].setdefault('children',[]).append(idx);joint_map[j]=idx;new_positions[idx]=pos
        return idx
    used_primitives=[]
    donor_head=descendants(donor['nodes'],db['head'])
    donor_cut=dpos[db['neck'],1]+offset/scale
    for primitive in donor['meshes'][selected]['primitives']:
        tri=triangles(dst,primitive);js,ws=influences(dst,primitive,dskin)
        nodes=np.array(dskin['joints'])[js];pos=dst.read(primitive['attributes']['POSITION'])
        hw=np.sum(ws*np.isin(nodes,list(donor_head)),axis=1)
        nw=np.sum(ws*(nodes==db['neck']),axis=1)
        body=(hw<.5)&((hw+nw<.5)|(pos[:,1]<donor_cut))
        mask=np.all(body[tri],axis=1)
        if mask.any():
            primitive=copy.deepcopy(primitive)
            primitive['indices']=dst.add(tri[mask].ravel(),'SCALAR',5125)
            used_primitives.append(primitive)
    if not used_primitives: raise ValueError('補完VRMの体に使える面がありません。体メッシュ名を確認してください。')
    used_donor_joints=set()
    for p in used_primitives:
        used=np.unique(triangles(dst,p));js,ws=influences(dst,p,dskin)
        used_donor_joints.update(np.array(dskin['joints'])[js[used][ws[used]>1e-5]].tolist())
    for j in sorted(used_donor_joints):map_joint(j)
    # Import unweighted endpoints too: Spring Bone needs a child to define length.
    for j in sorted(used_donor_joints):
        if j in targets: continue
        for child in donor['nodes'][j].get('children',[]):
            if child not in db.values(): map_joint(child)
    for role,j in db.items():
        if role not in bones and j in joint_map and (role.endswith(('Proximal','Intermediate','Distal','Toes'))): bones[role]=joint_map[j]
    plans,skin_report=skin_plan(doc,src,donor,dst,{p.get('material') for p in used_primitives if 'material' in p},options,image_decode)
    role_lookup={node:role for role,node in db.items()}
    body_positions={role:spos[node] for role,node in bones.items() if node<len(spos)}
    def node_regions(j):
        current=j;breast=False
        while current not in role_lookup:
            breast=breast or bool(re.search(r'breast|bust|胸',donor['nodes'][current].get('name',''),re.I))
            if current not in dp:break
            current=dp[current]
        role=role_lookup.get(current,'')
        torso=role in ('hips','spine','chest','upperChest','neck')
        region={'torso':float(torso),'pelvis':float(torso or role in ('leftUpperLeg','rightUpperLeg')),'breast':float(breast)}
        for side in ('left','right'):
            for part in ('UpperArm','UpperLeg'):region[side+part]=float(role==side+part)
        return region
    joint_regions=[node_regions(j) for j in dskin['joints']]
    if shaped:
        updated={}
        for donor_node,new_node in joint_map.items():
            if new_node not in new_positions:continue
            region={key:np.array([value]) for key,value in node_regions(donor_node).items()}
            updated[new_node]=reshape(np.array([new_positions[new_node]]),body_positions,shapes,region)[0]
        new_positions.update(updated)
        new_parents={child:i for i,n in enumerate(doc['nodes']) for child in n.get('children',[])}
        for node,position in new_positions.items():
            parent=new_parents[node];base=new_positions[parent] if parent in new_positions else spos[parent]
            doc['nodes'][node]['translation']=(position-base).tolist()
    # Remove the source body and clothes by head ancestry; preserve long hair below neck.
    head=descendants(doc['nodes'],bones['head']);neck=bones['neck'];cut=float(spos[neck,1]+offset)
    kept=removed=0;mesh_remap={};new_meshes=[]
    for mi,mesh in enumerate(doc['meshes']):
        instances_s=[n for n in doc['nodes'] if n.get('mesh')==mi]
        if not instances_s: continue
        if len(instances_s)!=1 or 'skin' not in instances_s[0]:raise ValueError('素体モードは独立したスキン付きメッシュのみ対応します。')
        skin=doc['skins'][instances_s[0]['skin']];primitives=[]
        for p in mesh['primitives']:
            tri=triangles(src,p);attr=p['attributes'];pos=src.read(attr['POSITION']);js,ws=influences(src,p,skin)
            nodes=np.array(skin['joints'])[js]
            head_weights=np.sum(ws*np.isin(nodes,list(head)),axis=1)
            neck_weights=np.sum(ws*(nodes==neck),axis=1)
            keep=(head_weights>=.5)|((head_weights+neck_weights>=.5)&(pos[:,1]>=cut))
            mask=np.all(keep[tri],axis=1);kept+=int(mask.sum());removed+=int((~mask).sum())
            if mask.any():
                out=copy.deepcopy(p);out['indices']=src.add(tri[mask].ravel(),'SCALAR',5125);primitives.append(out)
        if primitives:
            out=copy.deepcopy(mesh);out['primitives']=primitives;mesh_remap[mi]=len(new_meshes);new_meshes.append(out)
    if not kept:raise ValueError('頭・顔・髪の面を検出できませんでした。元モデルのウェイトを確認してください。')
    for n in doc['nodes']:
        if 'mesh' in n:
            if n['mesh'] in mesh_remap:n['mesh']=mesh_remap[n['mesh']]
            else:n.pop('mesh');n.pop('skin',None);n.pop('weights',None)
    doc['meshes']=new_meshes
    # Copy only donor textures actually used by the selected body material.
    material_map={};texture_map={};image_map={};sampler_map={}
    def image(index, skin=None):
        key=(index,skin)
        if key in image_map:return image_map[key]
        value=copy.deepcopy(donor['images'][index])
        if 'uri' in value or 'bufferView' not in value:raise ValueError('補完素体の画像はVRM内に埋め込んでください。')
        v=donor['bufferViews'][value['bufferView']];start=v.get('byteOffset',0)
        blob=bytes(dst.data[start:start+v['byteLength']])
        if skin is not None:
            blob=image_encode(tint_pixels(image_decode(blob,value.get('mimeType','image/png')),plans[skin]));value['mimeType']='image/png'
        value['bufferView']=src.view(blob)
        image_map[key]=len(doc.setdefault('images',[]));doc['images'].append(value);return image_map[key]
    def texture(index, skin=None):
        key=(index,skin)
        if key in texture_map:return texture_map[key]
        t=copy.deepcopy(donor['textures'][index])
        if t.get('extensions'):raise ValueError('補完素体の特殊テクスチャ拡張は未対応です。')
        t['source']=image(t['source'],skin)
        if 'sampler' in t:
            old=t['sampler']
            if old not in sampler_map:
                sampler_map[old]=len(doc.setdefault('samplers',[]));doc['samplers'].append(copy.deepcopy(donor['samplers'][old]))
            t['sampler']=sampler_map[old]
        texture_map[key]=len(doc.setdefault('textures',[]));doc['textures'].append(t);return texture_map[key]
    material_properties={}
    def material(index):
        if index in material_map:return material_map[index]
        mat=copy.deepcopy(donor['materials'][index]);mat['name']='Template_'+mat.get('name',str(index))
        def remap(value):
            if isinstance(value,dict):
                for key,child in value.items():
                    if key.endswith('Texture') and isinstance(child,dict) and 'index'in child:child['index']=texture(child['index'],index if index in plans and key=='baseColorTexture' else None)
                    else:remap(child)
            elif isinstance(value,list):
                for child in value:remap(child)
        remap(mat)
        if index in plans:
            pbr=mat.setdefault('pbrMetallicRoughness',{});factor=list(pbr.get('baseColorFactor',[1,1,1,1]))
            factor[:3]=[1,1,1] if 'baseColorTexture' in pbr else np.clip(plans[index]['factor']*plans[index]['ratio'],0,1).tolist()
            pbr['baseColorFactor']=factor
        out=len(doc.setdefault('materials',[]));doc['materials'].append(mat);material_map[index]=out
        properties=vrm.get('materialProperties',[])
        if index<len(properties):
            prop=copy.deepcopy(properties[index]);prop['name']=mat['name']
            prop['textureProperties']={k:texture(v,index if index in plans and k in ('_MainTex','_ShadeTexture') else None) if v>=0 else v for k,v in prop.get('textureProperties',{}).items()}
            if index in plans:
                vectors=prop.setdefault('vectorProperties',{});vectors['_Color']=mat['pbrMetallicRoughness']['baseColorFactor']
                if '_ShadeColor' in vectors:
                    shade=list(vectors['_ShadeColor'])
                    gain=1/np.maximum(plans[index]['factor'],1e-6) if prop.get('textureProperties',{}).get('_ShadeTexture',-1)>=0 else plans[index]['ratio']
                    shade[:3]=np.clip(np.array(shade[:3])*gain,0,1).tolist();vectors['_ShadeColor']=shade
            material_properties[out]=prop
        return out
    ordered=sorted(used_donor_joints);unique=[]
    for j in ordered:
        n=joint_map[j]
        if n not in unique:unique.append(n)
    inverse=[]
    for n in unique:
        pos=new_positions.get(n,spos[n] if n<len(spos) else None);m=np.eye(4);m[:3,3]=-pos;inverse.append(m.T.reshape(-1))
    skin_index=len(doc['skins']);doc['skins'].append({'joints':unique,'inverseBindMatrices':src.add(inverse,'MAT4')})
    body_primitives=[]
    for p in used_primitives:
        if p.get('extensions'):raise ValueError('圧縮・拡張付きの体メッシュは未対応です。')
        tri=triangles(dst,p);used,reindexed=np.unique(tri.ravel(),return_inverse=True)
        js,ws=influences(dst,p,dskin);js=js[used];ws=ws[used];dnodes=np.array(dskin['joints'])[js]
        transforms=np.array([matrices[anchor(j)] if j in used_donor_joints else np.eye(4) for j in dskin['joints']])
        blend=np.einsum('vjab,vj->vab',transforms[js],ws)
        attr=p['attributes']
        fitted=np.einsum('vab,vb->va',blend[:,:3,:3],dst.read(attr['POSITION'])[used])+blend[:,:3,3]
        if shaped:
            regions={key:np.sum(ws*np.array([r[key] for r in joint_regions])[js],axis=1) for key in joint_regions[0]}
            fitted=reshape(fitted,body_positions,shapes,regions)
        out={'attributes':{},'indices':src.add(reindexed,'SCALAR',5125)}
        for semantic,index in attr.items():
            if semantic.startswith(('JOINTS_','WEIGHTS_')) or (shaped and semantic=='TANGENT'):continue
            data=dst.read(index)[used]
            if semantic=='POSITION':data=fitted
            elif semantic in ('NORMAL','TANGENT'):
                transform=np.linalg.inv(blend[:,:3,:3]).transpose(0,2,1) if semantic=='NORMAL' else blend[:,:3,:3]
                xyz=np.einsum('vab,vb->va',transform,data[:,:3]);xyz/=np.maximum(np.linalg.norm(xyz,axis=1)[:,None],1e-12)
                data[:,:3]=normals(fitted,reindexed,xyz) if shaped and semantic=='NORMAL' else xyz
            # Expand normalized integer UV/color attributes to floating point.
            a=donor['accessors'][index];out['attributes'][semantic]=src.add(data,a['type'])
        ws=np.where(ws>1e-5,ws,0);ws/=ws.sum(axis=1)[:,None]
        mapped=np.zeros_like(js)
        for row in range(js.shape[1]):
            mapped[:,row]=[unique.index(joint_map[int(j)]) if w>1e-5 else 0 for j,w in zip(dnodes[:,row],ws[:,row])]
        for suffix,start in [('0',0),('1',4)]:
            if start>=js.shape[1]:break
            out['attributes']['JOINTS_'+suffix]=src.add(mapped[:,start:start+4],'VEC4',5123)
            out['attributes']['WEIGHTS_'+suffix]=src.add(ws[:,start:start+4],'VEC4')
        if 'material' in p:out['material']=material(p['material'])
        body_primitives.append(out)
    body_mesh=len(doc['meshes']);doc['meshes'].append({'name':'TemplateBody','primitives':body_primitives})
    ni=len(doc['nodes']);doc['nodes'].append({'name':'TemplateBody','mesh':body_mesh,'skin':skin_index,'translation':[0,0,0]})
    scene=doc.setdefault('scene',0);doc.setdefault('scenes',[{'nodes':[]}])[scene].setdefault('nodes',[]).append(ni)
    # Used material extensions must be declared; the VRM extension itself is generated later.
    for key in ('extensionsUsed','extensionsRequired'):
        for extension in donor.get(key,[]):
            if extension != 'VRM' and extension not in doc.setdefault(key,[]):doc[key].append(extension)
    metadata=copy.deepcopy(vrm.get('meta',{}))
    report={'mode':'body_only','bodyMesh':donor['meshes'][selected].get('name'),'neckCutY':cut,
        'width':width,'scale':scale,'shape':shapes,'skinMatching':skin_report,'keptHeadTriangles':kept,'removedSourceTriangles':removed,
        'bodyTriangles':sum(len(triangles(dst,p)) for p in used_primitives),
        'mappedJoints':len(unique),'addedJoints':len(new_positions),'templateMetadata':metadata,
        'warnings':skin_report['warnings']+['素体合成は実験機能です。首の接合状態と、肌色・つなぎ目・体形を確認してください。',
                    '頭の保持はウェイトから推定します。頭に追従する衣装が残る場合があります。',
                    '補完素体の表情・体形モーフは移植しません。胸は元のウェイトとボーンを利用して揺れを再設定します。']}
    log('素体合成: 頭の面 '+str(kept)+' / 体の面 '+str(report['bodyTriangles']))
    return src.finish(),report,material_properties
