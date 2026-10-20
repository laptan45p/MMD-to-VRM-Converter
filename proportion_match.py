"""Conservative cross-section fitting from source skin and skeletal spans."""
import re
import numpy as np

TORSO=('hips','spine','chest','upperChest','neck')
LIMBS=tuple(side+part for side in ('left','right') for part in ('UpperArm','LowerArm','UpperLeg','LowerLeg'))
ENDS={side+part:side+end for side in ('left','right') for part,end in
      (('UpperArm','LowerArm'),('LowerArm','Hand'),('UpperLeg','LowerLeg'),('LowerLeg','Foot'))}


def skin_materials(doc, supplied=''):
    if supplied:
        return {i for i,m in enumerate(doc.get('materials',[])) if m.get('name')==supplied}
    out=set()
    for i,m in enumerate(doc.get('materials',[])):
        name=m.get('name','')
        if re.search(r'cloth|dress|skirt|hair|eye|lash|服|衣装|髪|目',name,re.I):continue
        if re.search(r'skin|肌|素体',name,re.I):out.add(i)
    return out


def joint_region(node, nodes, parents, bones):
    roles={v:k for k,v in bones.items()};seen=set()
    while node not in roles:
        if node not in parents or node in seen:return None
        seen.add(node);node=parents[node]
    role=roles[node]
    return 'torso' if role in TORSO else role if role in LIMBS else None


def regions(joints, weights, nodes, parents, bones):
    lookup={int(j):joint_region(int(j),nodes,parents,bones) for j in np.unique(joints)}
    names=[lookup[int(j)] for j in joints.ravel()]
    names=np.array(names,dtype=object).reshape(joints.shape)
    return {key:np.sum(weights*(names==key),axis=1) for key in ('torso',)+LIMBS}


def measure_axis(points, normals, axis):
    # Require surfaces facing both sides. A front-only skin opening cannot
    # establish torso thickness or the full width underneath clothing.
    if len(points)<24:return None
    if min(np.sum(normals[:,axis]<-.3),np.sum(normals[:,axis]>.3))<4:return None
    lo,hi=np.quantile(points[:,axis],[.025,.975])
    return float(hi-lo) if hi-lo>.004 else None


def build_plan(source, donor, positions, source_positions, donor_positions, scale, enabled=True, manual_width=1.):
    """Samples are (points, normals, per-region skin weights), already fitted."""
    report={'enabled':bool(enabled),'status':'disabled','torso':[],'limbs':{},'warnings':[]}
    if not enabled:return None,report
    p,n,r=source;dp,dn,dr=donor
    hip=positions['hips'];neck=positions['neck'];height=float(neck[1]-hip[1])
    if height<.03:return None,dict(report,status='insufficient_landmarks')
    def span(pos,part):return abs(float(pos['left'+part][0]-pos['right'+part][0]))
    shoulder=span(source_positions,'UpperArm')/max(span(donor_positions,'UpperArm')*scale,1e-6)
    pelvis=span(source_positions,'UpperLeg')/max(span(donor_positions,'UpperLeg')*scale,1e-6)
    shoulder=float(np.clip(shoulder,.65,1.35));pelvis=float(np.clip(pelvis,.65,1.35))
    ys=np.linspace(hip[1]-height*.12,neck[1],9);factors=[]
    for y in ys:
        sm=(r['torso']>.65)&(np.abs(p[:,1]-y)<height*.065)
        dm=(dr['torso']>.65)&(np.abs(dp[:,1]-y)<height*.065)
        t=float(np.clip((y-hip[1])/height,0,1))
        # Shoulder/hip bone spacing gives a conservative fallback for width;
        # there is no skeletal evidence for soft-tissue depth.
        fallback=pelvis*(1-t)+shoulder*t
        values=[];methods=[]
        for axis in (0,2):
            a=measure_axis(p[sm],n[sm],axis);b=measure_axis(dp[dm],dn[dm],axis)
            if a is not None and b is not None:
                values.append(float(np.clip(a*manual_width/b,.65,1.35)));methods.append('skin')
            else:
                values.append(fallback if axis==0 else 1.);methods.append('skeleton' if axis==0 else 'unchanged')
        factors.append(values);report['torso'].append({'y':float(y),'width':values[0],'depth':values[1],'methods':methods})
    # Smooth measurement noise without shifting the anatomical height anchors.
    factors=np.asarray(factors)
    if len(factors)>2:factors[1:-1]=(factors[:-2]+2*factors[1:-1]+factors[2:])/4
    for item,factor in zip(report['torso'],factors):item.update(width=float(factor[0]),depth=float(factor[1]))
    limb_factors={}
    for role in LIMBS:
        end=ENDS[role]
        if role not in positions or end not in positions:continue
        a=positions[role];axis=positions[end]-a;length=np.linalg.norm(axis)
        if length<.01:continue
        axis=axis/length
        def radius(points,normals,weights):
            t=(points-a)@axis/length
            mask=(weights>.65)&(t>.2)&(t<.8)
            q=points[mask];norm=normals[mask]
            if len(q)<24:return None
            coverage=np.quantile(t[mask],[.1,.9])
            if coverage[0]>.35 or coverage[1]<.65:return None
            rel=q-a;radial=rel-(rel@axis)[:,None]*axis
            # Reject one-sided patches, e.g. exposed fronts beside stockings.
            transverse=np.eye(3)[int(np.argmin(np.abs(axis)))];transverse-=axis*np.dot(transverse,axis);transverse/=np.linalg.norm(transverse)
            side=norm@transverse
            if min(np.sum(side<-.3),np.sum(side>.3))<4:return None
            return float(np.quantile(np.linalg.norm(radial,axis=1),.8))
        sr=radius(p,n,r[role]);dd=radius(dp,dn,dr[role])
        if sr is not None and dd is not None and dd>.002:
            factor=float(np.clip(sr*manual_width/dd,.65,1.35));method='skin'
        else:
            factor=shoulder if role.endswith(('UpperArm','LowerArm')) else pelvis;method='skeleton'
        limb_factors[role]=factor;report['limbs'][role]={'factor':factor,'method':method}
    # If one leg/arm is covered but its paired side has a usable skin section,
    # prefer that evidence over giving the two sides different fallback widths.
    for part in ('UpperArm','LowerArm','UpperLeg','LowerLeg'):
        left='left'+part;right='right'+part
        if left not in report['limbs'] or right not in report['limbs']:continue
        a=report['limbs'][left];b=report['limbs'][right]
        if (a['method']=='skin') != (b['method']=='skin'):
            good,other=(left,right) if a['method']=='skin' else (right,left)
            limb_factors[other]=limb_factors[good]
            report['limbs'][other]={'factor':limb_factors[good],'method':'paired_skin'}
    report.update(status='applied',shoulderSpanFactor=shoulder,hipSpanFactor=pelvis)
    if any(x['methods']!=['skin','skin'] for x in report['torso']):
        report['warnings'].append('肌形状を十分に測れない部位は骨格幅を基準に補正し、厚みは維持しました。衣装の内側の体型は復元しません。')
    report['limit']=[.65,1.35]
    return {'ys':ys,'factors':factors,'limbs':limb_factors},report


def shoulder_height(points, weights, height_plan):
    p=np.asarray(points,dtype=float).copy()
    if height_plan is not None:
        y=p[:,1];mapped=np.interp(y,height_plan['from'],height_plan['to'])
        inside=(y>=height_plan['from'][0])&(y<=height_plan['from'][-1])
        p[:,1]+=(mapped-y)*weights*inside
    return p


def apply_plan(points, region_weights, positions, plan):
    p=np.asarray(points,dtype=float)
    if plan is None:return p.copy()
    p=shoulder_height(p,region_weights['torso'],plan.get('height'))
    out=p.copy();hip=positions['hips'];neck=positions['neck']
    t=np.clip((p[:,1]-hip[1])/max(neck[1]-hip[1],.03),0,1)
    center=hip+t[:,None]*(neck-hip)
    for column,axis in enumerate((0,2)):
        factor=np.interp(p[:,1],plan['ys'],plan['factors'][:,column])
        out[:,axis]+=(p[:,axis]-center[:,axis])*(factor-1)*region_weights['torso']
    for role,factor in plan['limbs'].items():
        a=positions[role];axis=positions[ENDS[role]]-a;size=np.linalg.norm(axis)
        if size<1e-6:continue
        axis/=size;relative=p-a;radial=relative-(relative@axis)[:,None]*axis
        out+=radial*((factor-1)*region_weights[role])[:,None]
    return out
