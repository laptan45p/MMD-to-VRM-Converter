"""Conservative name-based VRM0 Spring Bone setup, not a PMX physics solver."""
import math
import re
import unicodedata

CATEGORIES = ('hair', 'ribbon', 'sleeve', 'skirt', 'chest')
LABELS = dict(zip(CATEGORIES, ('髪', 'リボン・紐', '袖', 'スカート', '胸')))
# stiffness, drag, gravity, radius in meters at approximately adult scale
BASE = {'hair': (0.8, 0.4, 0.04, 0.012), 'ribbon': (1.1, 0.45, 0.03, 0.008),
        'sleeve': (1.8, 0.55, 0.04, 0.012), 'skirt': (2.3, 0.6, 0.03, 0.014),
        'chest': (2.5, 0.6, 0.0, 0.006)}

def text_key(value):
    return unicodedata.normalize('NFKC', value).casefold()

def classify(name):
    key = text_key(name)
    if re.search(r'ik|捩|twist|操作|control|先$|tip$|end$', key): return None
    # Accessory names take precedence over the body part in their prefix.
    for category, pattern in [
        ('ribbon', r'リボン|紐|ribbon|bow|strap'),
        ('hair', r'髪|おさげ|アホ毛|テール|hair|ponytail|pigtail|bangs'),
        ('sleeve', r'袖|sleeve'), ('skirt', r'スカート|skirt'),
        ('chest', r'胸|breast|bust|boob')]:
        if re.search(pattern, key): return category
    return None

def default_options():
    result = {'colliders': True}
    for category in CATEGORIES:
        stiffness, drag, gravity, radius = BASE[category]
        result[category] = {'enabled': True, 'stiffness': stiffness, 'drag': drag,
                            'gravity': gravity, 'radius': radius}
    return result

def descendants_set(nodes, root):
    result=set();pending=[root]
    while pending:
        i=pending.pop()
        if i in result:continue
        result.add(i);pending.extend(nodes[i].get('children',[]))
    return result

def setup_springs(document, original_names=None, options=None, active_joints=None):
    defaults = default_options(); supplied = options or {}
    settings = {'colliders': bool(supplied.get('colliders', True))}
    for category in CATEGORIES:
        settings[category] = {**defaults[category], **supplied.get(category, {})}
        for key, low, high in [('stiffness', 0, 10), ('drag', 0, 1),
                                ('gravity', 0, 1), ('radius', 0, 0.1)]:
            value = float(settings[category][key])
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError('Invalid Spring Bone '+category+'.'+key)
            settings[category][key] = value
    nodes = document['nodes']; vrm = document['extensions']['VRM']
    humanoid = {b['bone']: b['node'] for b in vrm['humanoid']['humanBones']}
    protected = set(humanoid.values())
    parents = {c:i for i,n in enumerate(nodes) for c in n.get('children', [])}
    names = original_names or {}
    joints = {j for skin in document.get('skins', []) for j in skin['joints']}
    report = {'settings': settings, 'groups': [], 'skipped': [], 'warnings': []}
    def descendants(i):
        yield i
        for child in nodes[i].get('children', []): yield from descendants(child)
    candidates = {}
    for i in sorted(joints):
        name = names.get(nodes[i].get('name'), nodes[i].get('name', ''))
        category = classify(name)
        if i not in protected and category and (active_joints is None or descendants_set(nodes,i).intersection(active_joints)):
            candidates[i] = category
    # If a candidate is off, its descendants must not leak into another category.
    roots = []
    for i, category in candidates.items():
        ancestor = parents.get(i)
        while ancestor is not None and ancestor not in candidates: ancestor = parents.get(ancestor)
        if ancestor is not None: continue
        chain = list(descendants(i))
        reason = None
        if not settings[category]['enabled']: reason = 'disabled'
        elif not nodes[i].get('children'): reason = 'no_child_bone'
        elif protected.intersection(chain): reason = 'contains_humanoid_bone'
        if reason:
            report['skipped'].append({'node':i, 'name':nodes[i]['name'], 'category':category, 'reason':reason})
        else: roots.append((i, category, chain))
    positions = {}
    def position(i):
        if i in positions: return positions[i]
        n = nodes[i]
        if 'matrix' in n or any(abs(v) > 1e-5 for v in n.get('rotation',[0,0,0,1])[:3]) or any(abs(v-1)>1e-5 for v in n.get('scale',[1,1,1])):
            raise ValueError('Spring Bone setup requires normalized nodes')
        local = n.get('translation', [0,0,0]); parent = parents.get(i)
        base = position(parent) if parent is not None else [0,0,0]
        positions[i] = [a+b for a,b in zip(local,base)]; return positions[i]
    head_y = position(humanoid['head'])[1]
    foot_y = min(position(humanoid[side+'Foot'])[1] for side in ('left','right'))
    scale = max(0.2, min(3.0, (head_y-foot_y)/1.3))
    colliders = []; indexes = {}
    def sphere_group(role, radius, offset=None, end=None):
        if role not in humanoid: return
        node = humanoid[role]; centers = [offset or [0,0,0]]
        if end in humanoid:
            a, b = position(node), position(humanoid[end])
            centers = [[(b[k]-a[k])*fraction for k in range(3)] for fraction in (0.25,0.55,0.85)]
        indexes[role] = len(colliders)
        colliders.append({'node':node, 'colliders':[
            {'offset':dict(zip(('x','y','z'), c)), 'radius':radius*scale} for c in centers]})
    if settings['colliders'] and roots:
        sphere_group('head', 0.085, [0,0.055*scale,0])
        sphere_group('chest', 0.10)
        sphere_group('spine', 0.085)
        sphere_group('hips', 0.085)
        for side in ('left','right'):
            sphere_group(side+'UpperArm',0.032,end=side+'LowerArm')
            sphere_group(side+'LowerArm',0.028,end=side+'Hand')
            sphere_group(side+'UpperLeg',0.045,end=side+'LowerLeg')
            sphere_group(side+'LowerLeg',0.035,end=side+'Foot')
    groups = []
    for i, category, chain in roots:
        p = settings[category]
        if category in {'hair','ribbon'}: roles = ['head','chest','spine']
        elif category == 'sleeve': roles = ['chest','spine','hips']
        elif category == 'skirt': roles = ['hips','leftUpperLeg','rightUpperLeg','leftLowerLeg','rightLowerLeg']
        else: roles = []  # Breast/torso self-collisions can cause severe popping.
        used_colliders = [indexes[r] for r in roles if r in indexes and humanoid[r] not in chain]
        groups.append({'comment':LABELS[category]+': '+nodes[i]['name'],
            'stiffiness':p['stiffness'], 'gravityPower':p['gravity'],
            'gravityDir':{'x':0,'y':-1,'z':0}, 'dragForce':p['drag'],
            'center':-1, 'hitRadius':p['radius']*scale, 'bones':[i], 'colliderGroups':used_colliders})
        report['groups'].append({'category':category,'root':nodes[i]['name'],
            'node':i,'chainNodes':chain,'colliderGroups':used_colliders})
    detected = {category for _, category, _ in roots}
    for category in CATEGORIES:
        if settings[category]['enabled'] and category not in detected:
            report['warnings'].append(LABELS[category]+'の有効なボーン連鎖を検出できませんでした。')
    report['warnings'].append('揺れと衝突は名前・骨格からの仮設定です。配信アプリで動作を確認してください。')
    vrm['secondaryAnimation'] = {'boneGroups':groups, 'colliderGroups':colliders}
    report['colliderCount'] = len(colliders)
    return report
