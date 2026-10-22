"""Executed by Blender --background --python, never system Python."""
import sys, json, traceback, zipfile, struct, io, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vrm_core import read_glb, write_glb, package_vrm
from bone_mapping import map_bones, validate_fingers
from spring_bones import setup_springs
from body_template import replace_body, active_joints
from head_transplant import transplant_head
from blender_image_io import BlenderImages
from neck_stitch import stitch_neck
from template_source import prepare_template
from normalize import normalize
from pmx_physics import read_physics_hints,annotate_nodes
from texture_paths import texture_path

config = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8-sig'))
log_path = Path(config['log'])
def log(message):
    message = str(message)
    print(message, flush=True)
    with log_path.open('a', encoding='utf-8') as f:f.write(message+'\n')

def material_data(path):
    f=io.BytesIO(path.read_bytes())
    def r(size):
        data=f.read(size)
        if len(data)!=size:raise ValueError('PMXが途中で切れています')
        return data
    def n(fmt):return struct.unpack('<'+fmt,r(struct.calcsize('<'+fmt)))[0]
    if r(4)!=b'PMX ':raise ValueError('PMX形式ではありません')
    version=n('f')
    if not 1.99<version<2.11:raise ValueError('PMX 2.0/2.1のみ対応しています')
    h=r(n('B'))
    if len(h)<8:raise ValueError('PMXヘッダーが不正です')
    def s():
        size=n('i')
        if size<0 or size>10000000:raise ValueError('PMX文字列が不正です')
        return r(size).decode('utf-16-le' if h[0]==0 else 'utf-8')
    def count():
        value=n('i')
        if value<0 or value>10000000:raise ValueError('PMX要素数が不正です')
        return value
    def idx(size):return n({1:'b',2:'h',4:'i'}[size])
    title=s();s();s();s()
    vertices=count()
    for _ in range(vertices):
        r(32+16*h[1]); kind=n('B')
        size={0:h[5],1:2*h[5]+4,2:4*h[5]+16,3:2*h[5]+40,4:4*h[5]+16}.get(kind)
        if size is None:raise ValueError('未知の頂点ウェイト形式')
        r(size+4)
    indices=count();r(indices*h[2]);textures=[s() for _ in range(count())]
    materials=[]
    for _ in range(count()):
        name=s();s();diffuse=struct.unpack('<4f',r(16));r(28);flags=n('B');r(20)
        texture=idx(h[3]);idx(h[3]);r(1);shared=n('B');r(1 if shared else h[3]);s();faces=count()
        materials.append({'name':name,'diffuse':diffuse,'double':bool(flags&1),
                          'texture':textures[texture] if 0<=texture<len(textures) else None})
    return title, textures, materials, vertices, indices//3

def input_model():
    source=Path(config['input'])
    if source.suffix.lower()=='.pmx':
        # Common distributions put PMX and texture in sibling folders.
        folder=source.resolve().parent
        config['texture_root']=str(folder.parent if folder.name.lower() in {'pmx','model','models'} else folder)
        return source
    if source.suffix.lower()!='.zip':raise ValueError('PMXまたはZIPを選んでください')
    destination=Path(config['work'])/'model';destination.mkdir(parents=True,exist_ok=True)
    config['texture_root']=str(destination.resolve())
    with zipfile.ZipFile(source) as archive:
        if sum(i.file_size for i in archive.infolist())>2*1024**3:
            raise ValueError('展開サイズが2GBを超えています')
        for item in archive.infolist():
            name=item.filename
            if not item.flag_bits&0x800:
                try:name=name.encode('cp437').decode('cp932')
                except (UnicodeError,LookupError):pass
            name=name.replace('\\','/')
            target=(destination/name).resolve()
            if not target.is_relative_to(destination.resolve()) or ':' in name:
                raise ValueError('ZIPに不正なパスが含まれています')
            if item.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(item) as src, target.open('wb') as out:
                import shutil
                shutil.copyfileobj(src,out)
    files=list(destination.rglob('*.pmx'))+list(destination.rglob('*.PMX'))
    files=list(dict.fromkeys(files))
    if len(files)!=1:raise ValueError('ZIP内にはPMXを1つだけ入れてください。複数ある場合は展開してPMXを直接選択してください')
    return files[0]

def run():
    import bpy, addon_utils
    log('Blender '+bpy.app.version_string)
    log('1/6 入力ファイルを確認しています')
    mode=config.get('conversion_mode','normal')
    if mode not in ('normal','body_only','head_to_template'):raise ValueError('不明な変換モードです。')
    if mode in ('body_only','head_to_template'):
        template=Path(config.get('body_template',''))
        if not template.is_file() or template.suffix.lower() not in ('.vrm','.fbx','.zip'):raise ValueError('補完素体のVRM / FBX / ZIPを指定してください。')
    model=input_model()
    title,textures,pmx_materials,vertices,triangles=material_data(model)
    log(f'頂点 {vertices:,} / 三角形 {triangles:,} / 材質 {len(pmx_materials)}')
    missing=[]
    for name in textures:
        p=texture_path(model,name,config['texture_root'])
        if not p.exists():missing.append(name)
    if missing:raise ValueError('テクスチャがありません: '+', '.join(missing))
    log('2/6 MMD Toolsを確認しています')
    candidates=[m.__name__ for m in addon_utils.modules() if m.__name__.split('.')[-1]=='mmd_tools']
    if not candidates:
        raise RuntimeError('MMD Toolsが見つかりません。Blenderの 編集 > プリファレンス > エクステンションを入手 から MMD Tools をインストールしてください')
    addon_utils.enable(candidates[0],default_set=False,persistent=False)
    try:
        bpy.ops.mmd_tools.import_model.get_rna_type()
    except Exception as e:
        raise RuntimeError('MMD Toolsを有効にできません。Blenderで有効化してから再実行してください') from e
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    log('3/6 PMXを読み込んでいます')
    result=bpy.ops.mmd_tools.import_model(filepath=str(model),scale=0.08)
    if 'FINISHED' not in result:raise RuntimeError('MMD読み込みが失敗しました')
    arms=[o for o in bpy.context.scene.objects if o.type=='ARMATURE']
    if len(arms)!=1:raise RuntimeError('アーマチュアを1つに特定できません')
    arm=arms[0]
    # Freeze at rest pose; MMD IK/physics are not transferred in this release.
    arm.data.pose_position='REST'
    for pb in arm.pose.bones:
        for constraint in list(pb.constraints):pb.constraints.remove(constraint)
        pb.location=(0,0,0);pb.rotation_euler=(0,0,0);pb.scale=(1,1,1)
    aliases={}
    for bone in arm.data.bones:
        aliases[bone.name]=bone.name
        pb=arm.pose.bones.get(bone.name)
        if pb and hasattr(pb,'mmd_bone') and pb.mmd_bone.name_j:
            aliases[pb.mmd_bone.name_j]=bone.name
    bone_names,mapping_warnings=map_bones(aliases)
    original_names={actual:name for name,actual in aliases.items()}
    log('人型ボーン候補: '+str(len(bone_names)))
    # Some MMD models place upper/lower body as siblings. VRM requires hips->spine.
    if 'hips' in bone_names and 'spine' in bone_names:
        bpy.context.view_layer.objects.active=arm;arm.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        hips=arm.data.edit_bones[bone_names['hips']]
        spine=arm.data.edit_bones[bone_names['spine']]
        ancestor=spine.parent
        while ancestor and ancestor!=hips:ancestor=ancestor.parent
        if ancestor is None:
            check=hips.parent
            while check:
                if check==spine:raise ValueError('腰/背骨の階層が循環するため修正できません')
                check=check.parent
            spine.use_connect=False;spine.parent=hips
            log('VRM用に上半身を下半身の子に設定しました (レスト位置は維持)')
        bpy.ops.object.mode_set(mode='OBJECT')
    log('4/6 基本材質を設定しています')
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==arm for m in o.modifiers)]
    if not meshes:raise RuntimeError('スキン付きメッシュがありません')
    used={slot.material for obj in meshes for slot in obj.material_slots if slot.material}
    material_by_name={m['name']:m for m in pmx_materials}
    exported_materials={}
    warnings=list(mapping_warnings)
    for mat in used:
        japanese=getattr(getattr(mat,'mmd_material',None),'name_j','')
        pm=material_by_name.get(japanese) or material_by_name.get(mat.name)
        if pm is None:
            warnings.append('材質を自動対応できません: '+mat.name);continue
        exported_materials[mat.name]=pm
        pm['alpha_mode']='BLEND' if pm['diffuse'][3]<0.999 else 'OPAQUE'
        mat.use_nodes=True;nodes=mat.node_tree.nodes;nodes.clear()
        output=nodes.new('ShaderNodeOutputMaterial');bsdf=nodes.new('ShaderNodeBsdfPrincipled')
        mat.node_tree.links.new(bsdf.outputs['BSDF'],output.inputs['Surface'])
        bsdf.inputs['Base Color'].default_value=pm['diffuse']
        bsdf.inputs['Alpha'].default_value=pm['diffuse'][3]
        bsdf.inputs['Roughness'].default_value=1
        mat.diffuse_color=pm['diffuse'];mat.use_backface_culling=not pm['double']
        if pm['texture']:
            image=bpy.data.images.load(str(texture_path(model,pm['texture'],config['texture_root'])),check_existing=True)
            if pm['diffuse'][3]>=0.999:
                import numpy as np
                pixels=np.empty(len(image.pixels),dtype=np.float32);image.pixels.foreach_get(pixels)
                alpha_values=pixels[3::4]
                if len(alpha_values) and alpha_values.min()<0.999:
                    fraction=np.mean((alpha_values>0.02)&(alpha_values<0.98))
                    pm['alpha_mode']='MASK' if fraction<0.15 else 'BLEND'
            node=nodes.new('ShaderNodeTexImage');node.image=image
            mat.node_tree.links.new(node.outputs['Color'],bsdf.inputs['Base Color'])
            mat.node_tree.links.new(node.outputs['Alpha'],bsdf.inputs['Alpha'])
    for obj in meshes:
        if obj.data.shape_keys:
            for key in obj.data.shape_keys.key_blocks:key.value=0
        for mod in list(obj.modifiers):
            if mod.type in {'SOLIDIFY','EDGE_SPLIT'}:obj.modifiers.remove(mod)
    log('5/6 スキン・テクスチャ・表情を書き出しています')
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    for obj in meshes:obj.select_set(True)
    bpy.context.view_layer.objects.active=arm
    glb=Path(config['work'])/'intermediate.glb'
    props=bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
    options={'filepath':str(glb),'export_format':'GLB','use_selection':True,
             'export_animations':False,'export_morph':True,'export_skins':True,
             'export_extras':True,'export_yup':True,'export_image_format':'AUTO',
             'export_def_bones':False,'export_rest_position_armature':True,
             'export_materials':'EXPORT'}
    options={k:v for k,v in options.items() if k in props}
    if 'FINISHED' not in bpy.ops.export_scene.gltf(**options):raise RuntimeError('glTF書き出しに失敗しました')
    document,chunks=read_glb(glb)
    # Blender shader evaluation may bake textures. Preserve explicit PMX color and texture binding.
    for gm in document.get('materials',[]):
        pm=exported_materials.get(gm.get('name'))
        if pm:
            gm['doubleSided']=pm['double']
            gm.setdefault('pbrMetallicRoughness',{})['baseColorFactor']=list(pm['diffuse'])
            gm['alphaMode']=pm['alpha_mode']
            if pm['alpha_mode']=='MASK':gm['alphaCutoff']=0.5
    log('6/6 VRM 0.xを作成しています')
    node_names={n.get('name'):i for i,n in enumerate(document['nodes'])}
    mapped={role:node_names[name] for role,name in bone_names.items() if name in node_names}
    physics_hint_counts=annotate_nodes(document,original_names,read_physics_hints(model))
    finger_report=validate_fingers(document,mapped)
    bone_names={role:document['nodes'][node]['name'] for role,node in mapped.items()}
    chunks=normalize(document,chunks,mapped,log)
    body_report=None;body_materials={};weighted_joints=None
    if mode in ('body_only','head_to_template'):
        log('補完VRMの体を組み合わせています')
        images=BlenderImages(config['work'])
        template,template_source_report=prepare_template(template,config['work'],config.get('body_options'),log)
        assemble=transplant_head if mode=='head_to_template' else replace_body
        chunks,body_report,body_materials=assemble(document,chunks,mapped,template,config.get('body_options'),log,images.decode,images.encode)
        body_report['templateSourceReport']=template_source_report
        body_report['warnings'].extend(template_source_report['warnings'])
        body_options=config.get('body_options') or {}
        document,chunks,neck_report=stitch_neck(document,chunks,mapped,body_report['neckCutY'],body_options.get('neck_join',True),images.decode)
        body_report['neckJoin']=neck_report;body_report['warnings'].extend(neck_report['warnings'])
        log('首の自動接合: '+neck_report['status'])
        match=body_report['skinMatching']
        log('肌色補正: '+match['status']+' / 元材質: '+str(match.get('sourceMaterial','未検出'))+' / 補完材質: '+str(match.get('templateMaterial','未検出')))
        if match['status'] in ('not_detected','sample_failed'):
            log('元MMDの材質候補: '+', '.join(match['sourceCandidates']))
            log('補完素体の材質候補: '+', '.join(match['templateCandidates']))
        weighted_joints=active_joints(document,chunks)
        finger_report=validate_fingers(document,mapped)
        bone_names={role:document['nodes'][node]['name'] for role,node in mapped.items()}
    report=package_vrm(document,bone_names,config.get('title') or title,
                       config['author'],config.get('license_url',''))
    warnings.extend(report['expressionReport']['warnings'])
    if body_report:
        for index,properties in body_materials.items():
            document['extensions']['VRM']['materialProperties'][index]=properties
        meta=document['extensions']['VRM']['meta'];donor_meta=body_report['templateMetadata']
        reference='Body template: '+donor_meta.get('title','')+' / Author: '+donor_meta.get('author','')+' / License: '+donor_meta.get('otherLicenseUrl','')
        meta['reference']=reference
        if donor_meta.get('author') and donor_meta['author'] not in (meta['author'],'未指定'):meta['author']+=' / '+donor_meta['author']
        for key in ('allowedUserName','violentUssageName','sexualUssageName','commercialUssageName'):
            value=donor_meta.get(key)
            if key=='allowedUserName' and value in ('OnlyAuthor','ExplicitlyLicensedPerson'):meta[key]='OnlyAuthor'
            elif key!='allowedUserName' and value=='Disallow':meta[key]='Disallow'
        warnings.extend(body_report['warnings'])
    spring_report=setup_springs(document,original_names,config.get('spring_options'),active_joints=weighted_joints)
    report.update({'conversionMode':mode,'bodyTemplateReport':body_report,'fingerReport':finger_report,'springBoneReport':spring_report,
                   'springBones':bool(spring_report['groups']),'blender':bpy.app.version_string,'source':str(model),
                   'normalized':True,'tposeBaked':True,'pmxPhysicsHints':physics_hint_counts,
                   'vertices':vertices,'triangles':triangles,'warnings':warnings+finger_report['warnings']+spring_report['warnings']+[
                     'MMD剛体・ジョイントの完全再現、材質モーフ、ボーンモーフ、MMD特殊シェーダーは未対応です。',
                     '表情はglTFに出力された頂点モーフのみ対応します。',
                     'VRM対応ソフトで見た目・Tポーズ・ボーン・表情を確認してください。',
                     'VRChat用設定・アップロードは別途必要です。']})
    target=Path(config['output']);temporary=target.with_suffix('.vrm.tmp')
    try:
        write_glb(temporary,document,chunks)
        read_glb(temporary)
        os.replace(temporary,target)
    finally:
        if temporary.exists():temporary.unlink()
    target.with_suffix('.conversion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for warning in report['warnings']:log('注意: '+warning)
    log('表情プリセット: '+(', '.join(report['expressions']) or 'なし'))
    er=report['expressionReport']
    log(f"表情モーフ: {er['uniqueMorphCount']}種類 / プリセット {er['presetCount']} / 追加表情 {er['customCount']}")
    for preset in er['presets']:
        if preset['status']=='partial':
            log('表情の一部を自動設定できません: '+preset['preset']+' / '+', '.join(preset['missingComponents']))
    log('完了: '+str(target))
    Path(config['work'],'success.json').write_text(json.dumps({'output':str(target)}),encoding='utf-8')

try:run()
except Exception:
    log(traceback.format_exc())
    sys.exit(1)

