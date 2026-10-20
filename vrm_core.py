"""Small VRM 0.x packager. Blender performs geometry/skinning export."""
import json
import struct

MAP = {'hips':['下半身'], 'spine':['上半身'], 'chest':['上半身2'],
       'neck':['首'], 'head':['頭'], 'leftEye':['左目'], 'rightEye':['右目']}
for side, jp in [('left','左'), ('right','右')]:
    for key, name in [('Shoulder','肩'),('UpperArm','腕'),('LowerArm','ひじ'),
                      ('Hand','手首'),('UpperLeg','足'),('LowerLeg','ひざ'),
                      ('Foot','足首'),('Toes','つま先')]:
        MAP[side+key] = [jp+name]
    for digit, jp_digit in [('Thumb','親指'),('Index','人指'),('Middle','中指'),
                            ('Ring','薬指'),('Little','小指')]:
        for i, part in enumerate(['Proximal','Intermediate','Distal']):
            MAP[side+digit+part] = [jp+jp_digit+str(i if digit=='Thumb' else i+1)]
REQUIRED = ['hips','spine','head','leftUpperArm','leftLowerArm','leftHand',
            'rightUpperArm','rightLowerArm','rightHand','leftUpperLeg',
            'leftLowerLeg','leftFoot','rightUpperLeg','rightLowerLeg','rightFoot']
EXPRESSIONS = {'blink':['まばたき'], 'a':['あ'], 'i':['い'], 'u':['う'],
               'e':['え'], 'o':['お'], 'joy':['笑い','にこり'],
               'angry':['怒り'], 'sorrow':['悲しい','困る'], 'fun':['にこり']}

def read_glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from('<4sII', data)
    if magic != b'glTF' or version != 2 or length != len(data):
        raise ValueError('Invalid GLB header')
    offset, document, chunks = 12, None, []
    while offset < length:
        size, kind = struct.unpack_from('<II', data, offset)
        offset += 8
        if size % 4 or offset+size > length:
            raise ValueError('Invalid GLB chunk')
        blob = data[offset:offset+size]; offset += size
        if kind == 0x4E4F534A:
            document = json.loads(blob)
        else:
            chunks.append((kind, blob))
    if document is None:
        raise ValueError('Missing GLB JSON')
    return document, chunks

def write_glb(path, document, chunks):
    blob = json.dumps(document, ensure_ascii=False, separators=(',',':'), allow_nan=False).encode('utf-8')
    blob += b' ' * (-len(blob) % 4)
    payload = struct.pack('<II', len(blob), 0x4E4F534A)+blob
    for kind, blob in chunks:
        blob += b'\x00' * (-len(blob)%4)
        payload += struct.pack('<II', len(blob), kind)+blob
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 12+len(payload))+payload)

def package_vrm(document, bone_names, title, author, license_url):
    nodes = document.get('nodes', [])
    # Only skin joints are valid humanoid candidates; reject object/name collisions.
    joints = {j for skin in document.get('skins', []) for j in skin['joints']}
    humanoid = []
    mapping = {}
    for role, actual in bone_names.items():
        found = [i for i in joints if nodes[i].get('name') == actual]
        if len(found) == 1:
            mapping[role] = found[0]
            humanoid.append({'bone':role, 'node':found[0], 'useDefaultValues':True})
    missing = [role for role in REQUIRED if role not in mapping]
    if missing:
        raise ValueError('Required humanoid bones missing: '+', '.join(missing))
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Duplicate humanoid assignments')
    parents = {child:i for i,node in enumerate(nodes) for child in node.get('children',[])}
    def ancestor(a,b):
        seen=set()
        while b in parents and b not in seen:
            seen.add(b); b=parents[b]
            if a==b:return True
        return False
    for chain in [('hips','spine','head'),('leftUpperArm','leftLowerArm','leftHand'),
                  ('rightUpperArm','rightLowerArm','rightHand'),
                  ('hips','leftUpperLeg','leftLowerLeg','leftFoot'),
                  ('hips','rightUpperLeg','rightLowerLeg','rightFoot')]:
        for a,b in zip(chain,chain[1:]):
            if not ancestor(mapping[a],mapping[b]):
                raise ValueError('Invalid humanoid hierarchy: '+a+' -> '+b)
    groups=[]
    for preset, candidates in EXPRESSIONS.items():
        binds=[]
        for mesh_index,mesh in enumerate(document.get('meshes',[])):
            targets=mesh.get('extras',{}).get('targetNames',[])
            name=next((name for name in candidates if name in targets),None)
            if name:
                binds.append({'mesh':mesh_index,'index':targets.index(name),'weight':100})
        if binds:
            groups.append({'name':preset,'presetName':preset,'binds':binds,
                           'materialValues':[],'isBinary':False})
    materials=[]
    for m in document.get('materials',[]):
        pbr=m.get('pbrMetallicRoughness',{})
        color=pbr.get('baseColorFactor',[1,1,1,1])
        mode=m.get('alphaMode','OPAQUE')
        blend={'OPAQUE':0,'MASK':1,'BLEND':2}[mode]
        tex=pbr.get('baseColorTexture',{}).get('index')
        textures={} if tex is None else {'_MainTex':tex,'_ShadeTexture':tex}
        materials.append({'name':m.get('name','Material'),'shader':'VRM/MToon',
          'renderQueue':3000 if blend==2 else (2450 if blend==1 else 2000),
          'floatProperties':{'_BlendMode':blend,'_Cutoff':m.get('alphaCutoff',0.5),
             '_CullMode':0 if m.get('doubleSided') else 2,'_ZWrite':0 if blend==2 else 1,
             '_SrcBlend':5 if blend==2 else 1,'_DstBlend':10 if blend==2 else 0,
             '_ShadeShift':0,'_ShadeToony':0.9,'_IndirectLightIntensity':0.1,
             '_LightColorAttenuation':0,'_OutlineWidthMode':0,'_OutlineColorMode':0,
             '_MToonVersion':38,'_DebugMode':0},
          'vectorProperties':{'_Color':color,'_ShadeColor':[0.8,0.8,0.8,1],
                              '_MainTex':[0,0,1,1],'_ShadeTexture':[0,0,1,1]},
          'textureProperties':textures,
          'keywordMap':{'_ALPHATEST_ON':blend==1,'_ALPHABLEND_ON':blend==2,
                        '_ALPHAPREMULTIPLY_ON':False},
          'tagMap':{'RenderType':{'OPAQUE':'Opaque','MASK':'TransparentCutout','BLEND':'Transparent'}[mode]}})
    curve={'curve':[0,0,0,1,1,1,1,0], 'xRange':90, 'yRange':10}
    document.setdefault('extensions',{})['VRM']={
        'exporterVersion':'MMD VRM Tool 0.7.1','specVersion':'0.0',
        'meta':{'title':title,'version':'1.0','author':author,'contactInformation':'',
          'reference':'','allowedUserName':'OnlyAuthor','violentUssageName':'Disallow',
          'sexualUssageName':'Disallow','commercialUssageName':'Disallow',
          'otherPermissionUrl':license_url,'licenseName':'Other','otherLicenseUrl':license_url},
        'humanoid':{'humanBones':humanoid,'armStretch':0.05,'legStretch':0.05,
          'upperArmTwist':0.5,'lowerArmTwist':0.5,'upperLegTwist':0.5,
          'lowerLegTwist':0.5,'feetSpacing':0,'hasTranslationDoF':False},
        'firstPerson':{'firstPersonBone':mapping['head'],
          'firstPersonBoneOffset':{'x':0,'y':0.06,'z':0},
          'meshAnnotations':[{'mesh':i,'firstPersonFlag':'Auto'} for i in range(len(document.get('meshes',[])))],
          'lookAtTypeName':'Bone','lookAtHorizontalInner':curve,'lookAtHorizontalOuter':curve,
          'lookAtVerticalDown':curve,'lookAtVerticalUp':curve},
        'blendShapeMaster':{'blendShapeGroups':groups},
        'secondaryAnimation':{'boneGroups':[],'colliderGroups':[]},
        'materialProperties':materials}
    used=document.setdefault('extensionsUsed',[])
    if 'VRM' not in used:used.append('VRM')
    return {'humanoid':mapping,'expressions':[g['presetName'] for g in groups],
            'materials':len(materials),'springBones':False}
