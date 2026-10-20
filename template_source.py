"""Resolve optional VRM/FBX template packages and prepare FBX via Blender.

Only the caller's job directory is modified. Unity packages and PSD sources are
not executed or imported; ZIPs retain their directory structure.
"""
from pathlib import Path
import re
import shutil
import zipfile
from bone_mapping import map_bones, validate_fingers
from vrm_core import REQUIRED, read_glb, write_glb, package_vrm
from normalize import normalize

MODEL_TYPES={'.vrm','.fbx'}
IMAGE_TYPES={'.png','.jpg','.jpeg','.tga','.bmp'}

def choose_texture(root, explicit=''):
    if explicit:
        p=Path(explicit).expanduser().resolve()
        if not p.is_file() or p.suffix.lower() not in IMAGE_TYPES:raise ValueError('FBX用の肌テクスチャを指定してください。')
        return p
    files=[p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_TYPES]
    # Prefer an authored base-body texture over a clothing/face atlas.
    base=[p for p in files if any(part.casefold()=='basebody' for part in p.parts) and re.fullmatch(r'skin\d*',p.stem,re.I)]
    if base:
        preferred=[p for p in base if p.stem.casefold()=='skin1']
        if len(preferred)==1:return preferred[0]
        if len(base)==1:return base[0]
        raise ValueError('BaseBodyの肌テクスチャが複数あります。「FBX設定」で肌テクスチャを選んでください。')
    skin=[p for p in files if re.fullmatch(r'skin|body|肌',p.stem,re.I) and not any(re.search(r'cloth|underwear',part,re.I) for part in p.parts)]
    if len(skin)==1:return skin[0]
    raise ValueError('FBXの肌テクスチャを自動選択できません。「FBX設定」で指定してください。')

def resolve_template(path,work,options=None):
    path=Path(path).resolve();work=Path(work);options=options or {};root=path.parent
    if not path.is_file():raise ValueError('補完素体が見つかりません。')
    original=path
    if path.suffix.lower()=='.zip':
        root=work/'template-input';root.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist())>2*1024**3:raise ValueError('補完素体ZIPの展開サイズが2GBを超えています。')
            seen=set()
            for info in archive.infolist():
                name=info.filename
                if not info.flag_bits&0x800:
                    try:name=name.encode('cp437').decode('cp932')
                    except UnicodeError:pass
                name=name.replace('\\','/');target=(root/name).resolve()
                if not target.is_relative_to(root.resolve()) or ':' in name:raise ValueError('補完素体ZIPに不正なパスがあります。')
                if info.is_dir() or target.suffix.lower() not in MODEL_TYPES|IMAGE_TYPES:continue
                key=str(target).casefold()
                if key in seen:raise ValueError('補完素体ZIPに重複したファイル名があります。')
                seen.add(key);target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(info) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)
        models=[p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in MODEL_TYPES]
        if len(models)!=1:raise ValueError('補完素体ZIPにはVRMまたはFBXを1個だけ入れてください。')
        path=models[0]
    if path.suffix.lower() not in MODEL_TYPES:raise ValueError('補完素体はVRM 0.x、FBX、またはそれらを1個含むZIPを指定してください。')
    texture=choose_texture(root,options.get('fbx_texture') or '') if path.suffix.lower()=='.fbx' else None
    report={'input':str(original),'model':str(path),'format':path.suffix[1:].lower(),'texture':str(texture) if texture else None,'warnings':[]}
    return path,texture,report

def find_body_mesh(meshes,name=''):
    if name:
        matches=[m for m in meshes if m.name==name]
    else:
        matches=meshes if len(meshes)==1 else [m for m in meshes if re.search(r'body|素体',m.name,re.I)]
    if len(matches)!=1:raise ValueError('FBXの体メッシュを特定できません。体メッシュ名を指定してください。候補: '+', '.join(m.name for m in meshes))
    return matches[0]

def fbx_export_options(properties,path):
    settings={'filepath':str(path),'export_format':'GLB','use_selection':True,'export_animations':False,
        'export_morph':False,'export_skins':True,'export_extras':True,'export_yup':True,
        'export_def_bones':False,'export_rest_position_armature':True,'export_materials':'EXPORT'}
    image_property=properties.get('export_image_format')
    if image_property is not None:
        allowed={item.identifier for item in image_property.enum_items}
        selected=next((value for value in ('AUTO','PNG') if value in allowed),None)
        if selected is None:raise RuntimeError('このglTFエクスポーターには対応する画像形式（AUTO / PNG）がありません。')
        settings['export_image_format']=selected
    return {k:v for k,v in settings.items() if k in properties}

def prepare_template(path,work,options=None,log=print):
    """Called only after source geometry has been exported and loaded into memory."""
    options=options or {};path,texture,report=resolve_template(path,work,options)
    if path.suffix.lower()=='.vrm':return path,report
    import bpy
    log('補完FBXを読み込んでいます')
    # Source MMD data is already in the GLB document, so this isolated worker can
    # release its scene objects before importing the external body.
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    importer=None;properties=None
    for candidate in (bpy.ops.wm.fbx_import,bpy.ops.import_scene.fbx):
        try:properties=candidate.get_rna_type().properties.keys();importer=candidate;break
        except (AttributeError,RuntimeError):continue
    if importer is None:raise RuntimeError('BlenderのFBXインポーターを利用できません。')
    settings={'filepath':str(path),'use_anim':False,'use_image_search':False,'automatic_bone_orientation':False,'ignore_leaf_bones':False}
    if 'FINISHED' not in importer(**{k:v for k,v in settings.items() if k in properties}):raise RuntimeError('FBXの読み込みに失敗しました。')
    arms=[o for o in bpy.context.scene.objects if o.type=='ARMATURE']
    if len(arms)!=1:raise ValueError('補完FBXのアーマチュアを1個に特定できません。')
    arm=arms[0];arm.data.pose_position='REST';arm.animation_data_clear()
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==arm for m in o.modifiers)]
    mesh=find_body_mesh(meshes,(options.get('mesh_name') or '').strip())
    if not mesh.data.uv_layers:raise ValueError('補完FBXの体メッシュにUVがありません。')
    materials={slot.material for slot in mesh.material_slots if slot.material}
    if len(materials)>1:raise ValueError('補完FBXは体メッシュの肌材質が1個の構成に対応します。複数材質のFBXはVRMへ変換して指定してください。')
    for bone in arm.pose.bones:
        for constraint in list(bone.constraints):bone.constraints.remove(constraint)
        bone.location=(0,0,0);bone.rotation_euler=(0,0,0);bone.rotation_quaternion=(1,0,0,0);bone.scale=(1,1,1)
    mesh.animation_data_clear()
    if mesh.data.shape_keys:
        for key in mesh.data.shape_keys.key_blocks:key.value=0
    # Switch to the supplied base-body texture. No new texture details are drawn.
    mat=bpy.data.materials.new('FBXTemplateSkin');mat.use_nodes=True
    nodes=mat.node_tree.nodes;nodes.clear();output=nodes.new('ShaderNodeOutputMaterial');bsdf=nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Roughness'].default_value=1;mat.node_tree.links.new(bsdf.outputs['BSDF'],output.inputs['Surface'])
    image=bpy.data.images.load(str(texture),check_existing=True);image.colorspace_settings.name='sRGB'
    tex=nodes.new('ShaderNodeTexImage');tex.image=image;mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
    mesh.data.materials.clear();mesh.data.materials.append(mat)
    for polygon in mesh.data.polygons:polygon.material_index=0
    names,mapping_warnings=map_bones({bone.name:bone.name for bone in arm.data.bones})
    missing=[role for role in REQUIRED+['neck'] if role not in names]
    if missing:raise ValueError('補完FBXのボーン名を対応付けできません: '+', '.join(missing))
    bpy.ops.object.select_all(action='DESELECT');arm.select_set(True);mesh.select_set(True);bpy.context.view_layer.objects.active=arm
    intermediate=Path(work)/'template-fbx.glb'
    props=bpy.ops.export_scene.gltf.get_rna_type().properties
    if 'FINISHED' not in bpy.ops.export_scene.gltf(**fbx_export_options(props,intermediate)):raise RuntimeError('補完FBXの中間出力に失敗しました。')
    doc,chunks=read_glb(intermediate);nodes={n.get('name'):i for i,n in enumerate(doc['nodes'])};mapping={role:nodes[name] for role,name in names.items() if name in nodes}
    for node in doc['nodes']:
        if 'mesh' in node:doc['meshes'][node['mesh']]['name']=mesh.name
    fingers=validate_fingers(doc,mapping);chunks=normalize(doc,chunks,mapping,log)
    author=(options.get('fbx_author') or '').strip();license_url=(options.get('fbx_license_url') or '').strip()
    package_vrm(doc,{role:doc['nodes'][i]['name'] for role,i in mapping.items()},path.stem,author or '未指定',license_url)
    out=Path(work)/'template-prepared.vrm';write_glb(out,doc,chunks)
    report.update(bodyMesh=mesh.name,skinMaterial=mat.name,humanoidCount=len(mapping),fingerReport=fingers,metadataProvided=bool(author))
    report['warnings'].extend(mapping_warnings)
    if not author:report['warnings'].append('補完FBXにはVRMの作者情報がありません。「FBX設定」で補完素材の作者名・利用条件URLを入力してください。')
    log('補完FBXの肌テクスチャ: '+str(texture))
    return out,report
