"""Bake glTF skin into a normalized VRM0 T-pose (requires numpy)."""
import numpy as np
from bone_mapping import validate_required_bones

def world_matrices(doc):
    nodes=doc['nodes'];parents={c:i for i,n in enumerate(nodes) for c in n.get('children',[])}
    cache={}
    def world(i):
        if i in cache:return cache[i]
        n=nodes[i]
        if 'matrix' in n:m=np.array(n['matrix']).reshape(4,4).T
        else:
            x,y,z,w=n.get('rotation',[0,0,0,1]);m=np.eye(4)
            m[:3,:3]=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])@np.diag(n.get('scale',[1,1,1]))
            m[:3,3]=n.get('translation',[0,0,0])
        cache[i]=world(parents[i])@m if i in parents else m
        return cache[i]
    return [world(i).copy() for i in range(len(nodes))],parents

def normalize(doc,chunks,bones,log=print):
    validate_required_bones(bones, ['head'] + [side+part for side in ('left','right')
                            for part in ('UpperArm','LowerArm','Hand')])
    if doc.get('animations'):raise ValueError('Animated GLB normalization is unsupported')
    binary=bytearray(next(b for k,b in chunks if k==0x004E4942))
    types={5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}
    widths={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}
    def values(view,offset,count,width,dtype):
        v=doc['bufferViews'][view];start=v.get('byteOffset',0)+offset
        if v.get('buffer',0)!=0:raise ValueError('Multiple buffers are unsupported')
        size=np.dtype(dtype).itemsize;stride=v.get('byteStride',width*size)
        return np.ndarray((count,width),dtype=dtype,buffer=binary,offset=start,strides=(stride,size)).copy()
    def read(index):
        a=doc['accessors'][index];width=widths[a['type']];dtype=types[a['componentType']]
        result=values(a['bufferView'],a.get('byteOffset',0),a['count'],width,dtype) if 'bufferView'in a else np.zeros((a['count'],width),dtype=dtype)
        if 'sparse'in a:
            sp=a['sparse'];ind=sp['indices'];val=sp['values']
            indexes=values(ind['bufferView'],ind.get('byteOffset',0),sp['count'],1,types[ind['componentType']]).ravel()
            result[indexes]=values(val['bufferView'],val.get('byteOffset',0),sp['count'],width,dtype)
        if a.get('normalized') and a['componentType']!=5126:
            info=np.iinfo(np.dtype(dtype));result=np.maximum(result.astype(float)/info.max,-1)
        return result
    def view(blob):
        binary.extend(b'\0'*(-len(binary)%4));offset=len(binary);binary.extend(blob)
        index=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(blob)})
        return index
    def write(index,array,sparse=False):
        a=doc['accessors'][index];array=np.asarray(array,dtype='<f4');a['componentType']=5126
        for k in ['bufferView','byteOffset','sparse','normalized']:a.pop(k,None)
        if sparse:
            idx=np.flatnonzero(np.any(array!=0,axis=1)).astype('<u4')
            if len(idx):a['sparse']={'count':len(idx),'indices':{'bufferView':view(idx.tobytes()),'componentType':5125},'values':{'bufferView':view(array[idx].tobytes())}}
        else:a['bufferView']=view(array.tobytes())
        if a['type']=='VEC3':a['min']=array.min(axis=0).tolist();a['max']=array.max(axis=0).tolist()
    old,parents=world_matrices(doc);posed=[m.copy() for m in old]
    def subtree(i):
        yield i
        for c in doc['nodes'][i].get('children',[]):yield from subtree(c)
    def align(start,end,direction):
        pivot=posed[start][:3,3];v=posed[end][:3,3]-pivot;v/=np.linalg.norm(v)
        target=np.array(direction,dtype=float);target/=np.linalg.norm(target)
        cross=np.cross(v,target);cos=float(np.dot(v,target))
        if cos<-0.99999:raise ValueError('Arm direction is ambiguous')
        skew=np.array([[0,-cross[2],cross[1]],[cross[2],0,-cross[0]],[-cross[1],cross[0],0]])
        rot=np.eye(3)+skew+skew@skew/(1+cos)
        change=np.eye(4);change[:3,:3]=rot;change[:3,3]=pivot-rot@pivot
        for i in subtree(start):posed[i]=change@posed[i]
    # Orient the avatar first, then extend each arm away from its torso.
    # VRM/MMD exporters use different X-side conventions. Forcing left to +X
    # can fold a normalized template's arms across its body.
    eyes=[bones.get('leftEye'),bones.get('rightEye')]
    head=bones['head']
    forward=np.mean([old[i][2,3] for i in eyes if i is not None])-old[head][2,3] if all(i is not None for i in eyes) else -1
    turn=np.diag([-1,1,-1,1]) if forward>0 else np.eye(4)
    posed=[turn@m for m in posed]
    for side in ('left','right'):
        a,b,c=[bones[side+part] for part in ['UpperArm','LowerArm','Hand']]
        lateral=posed[a][0,3]-posed[head][0,3]
        if abs(lateral)<1e-6:lateral=posed[c][0,3]-posed[head][0,3]
        if abs(lateral)<1e-6:raise ValueError('Arm side cannot be determined')
        sign=1 if lateral>0 else -1
        align(a,b,[sign,0,0]);align(b,c,[sign,0,0])
    log('VRM0 Tポーズ・ボーン回転を正規化しています')
    updated=set()
    for ni,node in enumerate(doc['nodes']):
        if 'mesh'not in node:continue
        skin=doc['skins'][node['skin']] if 'skin'in node else None
        if skin:
            inverse=read(skin['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
            matrices=np.array([posed[j]@inverse[k] for k,j in enumerate(skin['joints'])])
        for primitive in doc['meshes'][node['mesh']]['primitives']:
            attr=primitive['attributes'];count=doc['accessors'][attr['POSITION']]['count']
            if skin:
                deform=np.zeros((count,4,4));weights_total=np.zeros(count)
                for suffix in ['0','1']:
                    if 'JOINTS_'+suffix not in attr:continue
                    js=read(attr['JOINTS_'+suffix]).astype(int);ws=read(attr['WEIGHTS_'+suffix])
                    deform+=np.einsum('vjab,vj->vab',matrices[js],ws);weights_total+=ws.sum(axis=1)
                if np.min(weights_total)<1e-8:raise ValueError('Unweighted vertices found')
                deform/=weights_total[:,None,None]
            else:deform=np.broadcast_to(turn@old[ni],(count,4,4))
            for semantic in ['POSITION','NORMAL','TANGENT']:
                if semantic not in attr:continue
                index=attr[semantic]
                if index in updated:continue
                data=read(index);xyz=np.einsum('vab,vb->va',deform[:,:3,:3],data[:,:3])
                if semantic=='POSITION':xyz+=deform[:,:3,3]
                else:xyz/=np.maximum(np.linalg.norm(xyz,axis=1)[:,None],1e-12)
                data[:,:3]=xyz;write(index,data);updated.add(index)
            for target in primitive.get('targets',[]):
                for semantic in ['POSITION','NORMAL','TANGENT']:
                    if semantic not in target:continue
                    index=target[semantic]
                    if index in updated:continue
                    delta=read(index);delta=np.einsum('vab,vb->va',deform[:,:3,:3],delta)
                    write(index,delta,sparse=True);updated.add(index)
    # New joint axes are all world axes; mesh vertices above are baked into world space.
    from pmx_colliders import rebase_colliders
    rebase_colliders(doc['nodes'],posed)
    positions=[m[:3,3] for m in posed]
    for i,node in enumerate(doc['nodes']):
        for k in ['matrix','rotation','scale']:node.pop(k,None)
        pos=np.zeros(3) if 'mesh'in node else positions[i]
        parent=parents.get(i)
        node['translation']=(pos-(np.zeros(3) if parent is None or 'mesh'in doc['nodes'][parent] else positions[parent])).tolist()
    for skin in doc.get('skins',[]):
        inverse=[]
        for j in skin['joints']:
            m=np.eye(4);m[:3,3]=-positions[j];inverse.append(m.T.reshape(-1))
        write(skin['inverseBindMatrices'],np.array(inverse))
    doc['buffers'][0]['byteLength']=len(binary)
    return [(k,bytes(binary) if k==0x004E4942 else b) for k,b in chunks]

