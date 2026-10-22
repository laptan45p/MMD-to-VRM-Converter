"""Attach an MMD head to a normalized donor body without fitting its torso."""
import copy
import math
import numpy as np
from body_template import Buffer, BIN, descendants, influences, triangles, select_body
from body_fit import neutral_body_material
from head_selection import hair_materials,hair_joints,retained_head_nodes,head_faces
from normalize import normalize, world_matrices
from vrm_core import read_glb, REQUIRED


def transplant_head(document,chunks,bones,template_path,options=None,log=print,image_decode=None,image_encode=None):
    options=options or {};multiplier=float(options.get('head_scale',1));offset=float(options.get('neck_offset',0))
    if not math.isfinite(multiplier) or not .5<=multiplier<=1.5:raise ValueError('頭部倍率は0.5〜1.5にしてください。')
    if not math.isfinite(offset) or not -.1<=offset<=.1:raise ValueError('首の境界は-0.1〜0.1mにしてください。')
    if 'neck' not in bones:raise ValueError('頭部移植には元モデルの首ボーンが必要です。')
    donor,dc=read_glb(template_path);vrm=copy.deepcopy(donor.get('extensions',{}).get('VRM'))
    if not vrm:raise ValueError('補完用VRMはVRM 0.xを指定してください。')
    db={b['bone']:b['node'] for b in vrm['humanoid']['humanBones']}
    missing=[r for r in REQUIRED+['neck'] if r not in db]
    if missing:raise ValueError('補完VRMの人型ボーンが不足: '+', '.join(missing))
    selected=select_body(donor,str(options.get('mesh_name') or '').strip())
    instances=[n for n in donor['nodes'] if n.get('mesh')==selected]
    if len(instances)!=1 or 'skin' not in instances[0]:raise ValueError('補完の体メッシュはスキン付き1個にしてください。')
    dc=normalize(donor,dc,db,log);src=Buffer(document,chunks);dst=Buffer(donor,dc)
    sw,sp=world_matrices(document);dw,dp=world_matrices(donor)
    source_neck=sw[bones['neck']][:3,3];target_neck=dw[db['neck']][:3,3]
    def height(world,mapping):
        return float(world[mapping['neck']][1,3]-np.mean([world[mapping[s+'Foot']][1,3] for s in ('left','right')]))
    sh=height(sw,bones);dh=height(dw,db)
    if min(sh,dh)<.05:raise ValueError('首から足首までの高さを取得できませんでした。')
    scale=dh/sh*multiplier;translation=target_neck-scale*source_neck
    cut=float(target_neck[1]+offset);source_cut=float(source_neck[1]+offset/scale)
    # Body accessors, weights and skeleton remain the donor's normalized data.
    body_skin=donor['skins'][instances[0]['skin']];head_nodes=descendants(donor['nodes'],db['head'])
    body_primitives=[]
    for primitive in donor['meshes'][selected]['primitives']:
        tri=triangles(dst,primitive);js,ws=influences(dst,primitive,body_skin)
        joints=np.array(body_skin['joints'])[js];pos=dst.read(primitive['attributes']['POSITION'])
        hw=np.sum(ws*np.isin(joints,list(head_nodes)),axis=1);nw=np.sum(ws*(joints==db['neck']),axis=1)
        keep=(hw<.5)&((hw+nw<.5)|(pos[:,1]<cut));mask=np.all(keep[tri],axis=1)
        if mask.any():
            out=copy.deepcopy(primitive);out['indices']=dst.add(tri[mask].ravel(),'SCALAR',5125)
            out.pop('targets',None);body_primitives.append(out)
    if not body_primitives:raise ValueError('補完素体の体の面を検出できませんでした。')
    for node in donor['nodes']:
        if 'mesh' in node:
            if node is instances[0]:node['mesh']=0;node.pop('weights',None)
            else:
                for key in ('mesh','skin','weights'):node.pop(key,None)
    donor['meshes']=[{'name':'TemplateBody','primitives':body_primitives}]
    # Clear stale donor head expressions; package_vrm regenerates them from MMD.
    donor.setdefault('extensions',{}).pop('VRM',None)
    hair_material_indexes=hair_materials(document)
    source_head=retained_head_nodes(document['nodes'],sp,bones,hair_joints(document,src,hair_material_indexes))
    node_map={bones['head']:db['head'],bones['neck']:db['neck']}
    source_positions={i:scale*m[:3,3]+translation for i,m in enumerate(sw)}
    names={n.get('name') for n in donor['nodes']}
    for old in sorted(source_head-{bones['head']}):
        original=document['nodes'][old]
        if any(k in original for k in ('mesh','camera')):continue
        name='MMDHead_'+original.get('name',str(old))
        while name in names:name+='_' 
        names.add(name);node_map[old]=len(donor['nodes']);node={'name':name}
        hint=original.get('extras',{}).get('mmdPhysics')
        if hint is not None:node['extras']={'mmdPhysics':copy.deepcopy(hint)}
        if original.get('extras',{}).get('mmdRigidBodies'):
            from pmx_colliders import scale_metadata
            node.setdefault('extras',{}).update(scale_metadata({'mmdRigidBodies':original['extras']['mmdRigidBodies']},scale))
        donor['nodes'].append(node)
    for role in ('head','neck'):
        old,new=bones[role],db[role]
        if document['nodes'][old].get('extras',{}).get('mmdRigidBodies'):
            from pmx_colliders import scale_metadata
            donor['nodes'][new].setdefault('extras',{}).update(scale_metadata({'mmdRigidBodies':document['nodes'][old]['extras']['mmdRigidBodies']},scale))
    for old,new in list(node_map.items()):
        if old in (bones['head'],bones['neck']):continue
        parent=sp.get(old);parent_new=node_map.get(parent,db['head'])
        base=(dw[parent_new][:3,3] if parent_new<len(dw) else source_positions[parent])
        donor['nodes'][new]['translation']=(source_positions[old]-base).tolist()
        donor['nodes'][parent_new].setdefault('children',[]).append(new)
    result_bones=db.copy()
    for role,node in bones.items():
        if role in ('leftEye','rightEye','jaw') and node in node_map:result_bones[role]=node_map[node]
    # Copy referenced source textures, preserving the donor body texture bytes.
    image_map={};texture_map={};sampler_map={};material_map={}
    def image(index):
        if index in image_map:return image_map[index]
        value=copy.deepcopy(document['images'][index])
        if 'uri' in value or 'bufferView' not in value:raise ValueError('頭部の画像はGLB内に埋め込んでください。')
        view=document['bufferViews'][value['bufferView']];start=view.get('byteOffset',0)
        value['bufferView']=dst.view(bytes(src.data[start:start+view['byteLength']]))
        out=len(donor.setdefault('images',[]));donor['images'].append(value);image_map[index]=out;return out
    def texture(index):
        if index in texture_map:return texture_map[index]
        value=copy.deepcopy(document['textures'][index])
        if value.get('extensions'):raise ValueError('頭部の特殊テクスチャ拡張は未対応です。')
        value['source']=image(value['source'])
        if 'sampler' in value:
            old=value['sampler']
            if old not in sampler_map:
                sampler_map[old]=len(donor.setdefault('samplers',[]));donor['samplers'].append(copy.deepcopy(document['samplers'][old]))
            value['sampler']=sampler_map[old]
        out=len(donor.setdefault('textures',[]));donor['textures'].append(value);texture_map[index]=out;return out
    def material(index):
        if index in material_map:return material_map[index]
        value=copy.deepcopy(document['materials'][index]);value['name']='MMDHead_'+value.get('name',str(index))
        def remap(item):
            if isinstance(item,dict):
                for key,child in item.items():
                    if key.endswith('Texture') and isinstance(child,dict) and 'index' in child:child['index']=texture(child['index'])
                    else:remap(child)
            elif isinstance(item,list):
                for child in item:remap(child)
        remap(value);out=len(donor.setdefault('materials',[]));donor['materials'].append(value);material_map[index]=out;return out
    kept=removed=0;imported=0;fallback=set();hair_faces_kept=0
    for mi,mesh in enumerate(document['meshes']):
        instances_s=[n for n in document['nodes'] if n.get('mesh')==mi]
        if not instances_s:continue
        if len(instances_s)!=1 or 'skin' not in instances_s[0]:raise ValueError('頭部移植は独立したスキン付きメッシュのみ対応します。')
        skin=document['skins'][instances_s[0]['skin']];primitives=[];new_joints=[]
        def map_joint(old,is_hair=False):
            if is_hair and old not in source_head:return db['head']
            if old in node_map:return node_map[old]
            fallback.add(old);return db['neck']
        def joint_index(old,is_hair=False):
            new=map_joint(old,is_hair)
            if new not in new_joints:new_joints.append(new)
            return new_joints.index(new)
        for primitive in mesh['primitives']:
            tri=triangles(src,primitive);attr=primitive['attributes'];pos=src.read(attr['POSITION'])
            js,ws=influences(src,primitive,skin);joints=np.array(skin['joints'])[js]
            hw=np.sum(ws*np.isin(joints,list(source_head)),axis=1);nw=np.sum(ws*(joints==bones['neck']),axis=1)
            is_hair=primitive.get('material') in hair_material_indexes
            mask=head_faces(tri,pos,hw,nw,source_cut,is_hair)
            if is_hair:hair_faces_kept+=int(mask.sum())
            kept+=int(mask.sum());removed+=int((~mask).sum())
            if not mask.any():continue
            if primitive.get('extensions'):raise ValueError('頭部の圧縮・拡張付きメッシュは未対応です。')
            used,reindexed=np.unique(tri[mask].ravel(),return_inverse=True)
            out={'attributes':{},'indices':dst.add(reindexed,'SCALAR',5125)}
            for semantic,index in attr.items():
                if semantic.startswith(('JOINTS_','WEIGHTS_')):continue
                data=src.read(index)[used]
                if semantic=='POSITION':data=data*scale+translation
                out['attributes'][semantic]=dst.add(data,document['accessors'][index]['type'])
            if 'targets' in primitive:
                out['targets']=[]
                for target in primitive['targets']:
                    out['targets'].append({semantic:dst.add(src.read(index)[used]*(scale if semantic=='POSITION' else 1),document['accessors'][index]['type']) for semantic,index in target.items()})
            mapped=np.zeros_like(js[used]);weights=ws[used].copy()
            for row in range(len(used)):
                for col in range(mapped.shape[1]):
                    if weights[row,col]>1e-6:mapped[row,col]=joint_index(int(joints[used[row],col]),is_hair)
                    else:weights[row,col]=0
            weights/=weights.sum(axis=1)[:,None]
            for suffix,start in (('0',0),('1',4)):
                if start>=mapped.shape[1]:break
                out['attributes']['JOINTS_'+suffix]=dst.add(mapped[:,start:start+4],'VEC4',5123)
                out['attributes']['WEIGHTS_'+suffix]=dst.add(weights[:,start:start+4],'VEC4')
            if 'material' in primitive:out['material']=material(primitive['material'])
            primitives.append(out)
        if not primitives:continue
        world,_=world_matrices(donor);inverse=[]
        for joint in new_joints:
            matrix=np.eye(4);matrix[:3,3]=-world[joint][:3,3];inverse.append(matrix.T.reshape(-1))
        si=len(donor['skins']);donor['skins'].append({'joints':new_joints,'inverseBindMatrices':dst.add(inverse,'MAT4')})
        output=copy.deepcopy(mesh);output['name']='MMDHead_'+mesh.get('name',str(mi));output['primitives']=primitives
        output_index=len(donor['meshes']);donor['meshes'].append(output)
        ni=len(donor['nodes']);node={'name':output['name'],'mesh':output_index,'skin':si,'translation':[0,0,0]}
        if 'weights' in instances_s[0]:node['weights']=copy.deepcopy(instances_s[0]['weights'])
        donor['nodes'].append(node);donor['scenes'][donor.get('scene',0)].setdefault('nodes',[]).append(ni);imported+=1
    if not kept:raise ValueError('元MMDから頭・顔・髪を検出できませんでした。')
    for key in ('extensionsUsed','extensionsRequired'):
        for extension in document.get(key,[]):
            if extension!='VRM' and extension not in donor.setdefault(key,[]):donor[key].append(extension)
    props={i:neutral_body_material(copy.deepcopy(p)) for i,p in enumerate(vrm.get('materialProperties',[])) if i<len(donor['materials'])}
    warnings=['頭部移植は実験機能です。首の接合・肌色・頭の大きさと動作を確認してください。',
        '素体の体型補正と肌色補正は適用しません。首接合が有効な場合は首付近のみ調整します。']
    if fallback:warnings.append('頭の境界に含まれる体側ボーンの少量のウェイトを、素体の首へまとめました。')
    report={'mode':'head_to_template','assemblyBasis':'template','neckCutY':cut,'headScale':scale,'headScaleMultiplier':multiplier,
        'headTranslation':translation.tolist(),'keptHeadTriangles':kept,'removedSourceTriangles':removed,'headMeshes':imported,'retainedHairTriangles':hair_faces_kept,
        'retainedHairMaterials':[document['materials'][i].get('name',str(i)) for i in sorted(hair_material_indexes)],
        'bodyTriangles':sum(len(triangles(dst,p)) for p in body_primitives),'templateMetadata':copy.deepcopy(vrm.get('meta',{})),
        'skinMatching':{'enabled':False,'status':'disabled','warnings':[]},'warnings':warnings}
    document.clear();document.update(donor);bones.clear();bones.update(result_bones)
    log('補完素体の骨格・体型を維持し、MMDの頭部を首の位置へ移植しました。')
    return dst.finish(),report,props

