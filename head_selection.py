"""Retain long hair independently of neck height and body-control weights."""
import re
import numpy as np


def hair_materials(document):
    return {i for i,m in enumerate(document.get('materials',[]))
        if re.search(r'hair|髪|もみあげ|アホ毛',m.get('name',''),re.I)}


def hair_joints(document,buf,materials):
    result=set()
    for node in document['nodes']:
        if 'mesh' not in node or 'skin' not in node:continue
        skin=document['skins'][node['skin']]
        for p in document['meshes'][node['mesh']]['primitives']:
            if p.get('material') not in materials:continue
            attr=p['attributes'];count=document['accessors'][attr['POSITION']]['count']
            used=np.unique(buf.read(p['indices']).ravel().astype(int)) if 'indices' in p else np.arange(count)
            for suffix in ('0','1'):
                if 'JOINTS_'+suffix not in attr:continue
                js=buf.read(attr['JOINTS_'+suffix])[used].astype(int);ws=buf.read(attr['WEIGHTS_'+suffix])[used]
                result.update(np.array(skin['joints'])[js[ws>1e-6]].tolist())
    return result


def retained_head_nodes(nodes,parents,bones,hair_nodes):
    def descendants(root):
        pending=[root];result=set()
        while pending:
            i=pending.pop()
            if i in result:continue
            result.add(i);pending.extend(nodes[i].get('children',[]))
        return result
    result=descendants(bones['head'])
    # Body-control ancestors may affect hair vertices; they must never pull
    # the whole torso/IK hierarchy into the imported head skeleton.
    blocked=set(bones.values())
    for node in list(blocked):
        seen=set()
        while node in parents and node not in seen:
            seen.add(node);node=parents[node];blocked.add(node)
    for seed in hair_nodes-blocked:
        result.update(descendants(seed)-blocked)
        current=seed;seen=set()
        while current not in blocked and current not in seen:
            seen.add(current);result.add(current)
            if current not in parents:break
            current=parents[current]
    return result


def head_faces(triangles,positions,head_weights,neck_weights,cut,is_hair=False):
    if is_hair:return np.ones(len(triangles),dtype=bool)
    keep=(head_weights>=.5)|((head_weights+neck_weights>=.5)&(positions[:,1]>=cut))
    return np.all(keep[triangles],axis=1)
