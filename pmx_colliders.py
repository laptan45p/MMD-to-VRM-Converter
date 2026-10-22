"""Approximate PMX fixed rigid bodies with VRM0 spheres, preserving pair filters."""
import copy
import hashlib
import json
import itertools
import math
import numpy as np

MAX_SPHERES = 64

def collide(a, b):
    # Raw PMX bits are enabled pairs; MMD Tools inverts these for its UI's
    # 'cannot collide' bool vector. Both bodies must permit the other group.
    if a.get('sourceKey')!=b.get('sourceKey'):return False
    return bool(a['collisionMask'] & (1 << b['group']) and
                b['collisionMask'] & (1 << a['group']))

def _rotation(angles):
    x,y,z=angles;cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z)
    return np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]]) @ np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]]) @ np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])

def shape_spheres(body):
    """Return PMX-local sphere centers/radii, and whether sampling was capped."""
    size=np.array(body['size'],dtype=float);kind=body['shape']
    if not np.isfinite(size).all() or (size<0).any():raise ValueError('Invalid rigid dimensions')
    if kind==0:
        if size[0]<=0:raise ValueError('Zero sphere radius')
        return [(np.zeros(3),float(size[0]))],False
    if kind==2:
        radius,height=size[:2]
        if radius<=0:raise ValueError('Zero capsule radius')
        ratio=float(height)/float(radius)
        wanted=MAX_SPHERES+1 if ratio>=MAX_SPHERES else max(1,int(math.ceil(ratio))+1)
        count=min(MAX_SPHERES,wanted)
        points=[np.array([0,y,0]) for y in np.linspace(-height/2,height/2,count)]
        return [(p,float(radius)) for p in points],wanted>count
    if kind!=1 or (size<=0).any():raise ValueError('Invalid box dimensions')
    radius=float(size.min());extent=np.maximum(size-radius,0)
    wanted=[MAX_SPHERES+1 if float(v)/radius>=MAX_SPHERES/2 else max(1,int(math.ceil(2*float(v)/radius))+1) for v in extent]
    counts=[min(MAX_SPHERES,n) for n in wanted]
    while math.prod(counts)>MAX_SPHERES:
        axis=max(range(3),key=lambda i:counts[i]);counts[axis]-=1
    axes=[np.linspace(-v,v,n) if n>1 else [0.] for v,n in zip(extent,counts)]
    return [(np.array(p),radius) for p in itertools.product(*axes)],counts!=wanted

def annotate_colliders(document, original_names, physics, import_scale=.08):
    # Local offsets are captured before T-pose baking and rebased by normalize.
    from normalize import world_matrices
    worlds,_=world_matrices(document);nodes=document['nodes'];lookup={}
    for i,n in enumerate(nodes):
        name=(original_names or {}).get(n.get('name'),n.get('name',''))
        lookup.setdefault(name,[]).append(i)
    report={'sourceRigidCount':len(physics['rigidBodies']),'sourceJointCount':physics['jointCount'],
            'mappedRigidCount':0,'fixedRigidCount':0,'skipped':[],'approximations':[],
            'unsupported':['dynamic_rigid_to_rigid_collision','bullet_mass_friction_restitution','joint_constraints'],
            'chainFilterPolicy':'intersection','shapeApproximation':'inscribed_spheres_for_boxes'}
    # Match MMD Tools: PMX xyz -> Blender xzy; rotation (-x,-z,-y),
    # followed by Blender's glTF export Y-up conversion.
    swap=np.array([[1,0,0],[0,0,1],[0,1,0]],dtype=float)
    yup=np.array([[1,0,0],[0,0,1],[0,-1,0]],dtype=float)
    source_key=hashlib.sha256(json.dumps(physics['rigidBodies'],sort_keys=True).encode()).hexdigest()[:24]
    for b in physics['rigidBodies']:
        matches=lookup.get(b['boneName'],[])
        if len(matches)!=1:
            report['skipped'].append({'rigid':b['index'],'reason':'unmapped_or_ambiguous_bone'});continue
        i=matches[0];extra=nodes[i].setdefault('extras',{})
        try:
            if not all(math.isfinite(v) for v in b['position']+b['rotation']):raise ValueError('Nonfinite rigid transform')
            spheres,capped=shape_spheres(b)
            inverse=np.linalg.inv(worlds[i]);basis=worlds[i][:3,:3]
            scale=float(np.linalg.svd(basis,compute_uv=False).max())
            if scale<=1e-10:raise ValueError('Singular bone transform')
            x,y,z=b['rotation'];rotation=yup @ _rotation([-x,-z,-y]) @ swap
            center=yup @ swap @ np.array(b['position'])*import_scale
            local=[]
            for point,radius in spheres:
                p=inverse @ np.append(center+rotation@point*import_scale,1)
                r=radius*import_scale/scale
                if not np.isfinite(p).all() or not math.isfinite(r) or r<=0:raise ValueError('Invalid local collider')
                local.append({'offset':p[:3].tolist(),'radius':r})
            record={k:copy.deepcopy(b[k]) for k in ('index','name','group','collisionMask','shape','mode')}
            record['sourceKey']=source_key
            record['spheres']=local
            record['hitRadius']=min(s['radius'] for s in local)
            extra.setdefault('mmdRigidBodies',[]).append(record);report['mappedRigidCount']+=1
            if b['mode']==0:report['fixedRigidCount']+=1
            if b['shape']!=0:report['approximations'].append({'rigid':b['index'],'shape':'capsule' if b['shape']==2 else 'box','sphereCount':len(local),'samplingCapped':capped})
        except (ValueError,np.linalg.LinAlgError):
            report['skipped'].append({'rigid':b['index'],'reason':'invalid_shape_or_transform'})
    return report

def rebase_colliders(nodes, posed):
    for i,n in enumerate(nodes):
        basis=posed[i][:3,:3];scale=float(np.linalg.svd(basis,compute_uv=False).max())
        for b in n.get('extras',{}).get('mmdRigidBodies',[]):
            for s in b['spheres']:
                s['offset']=(basis @ np.array(s['offset'])).tolist();s['radius']*=scale
            b['hitRadius']*=scale

def scale_metadata(extras, factor):
    result=copy.deepcopy(extras)
    for b in result.get('mmdRigidBodies',[]):
        for s in b['spheres']:
            s['offset']=[v*factor for v in s['offset']];s['radius']*=factor
        b['hitRadius']*=factor
    return result
