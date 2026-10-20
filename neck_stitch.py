"""Conservative, transactional bridge between two simple open neck loops.

Works on normalized, world-baked GLB meshes. Unsupported topology leaves the
original composition intact. Meshes keep their indices so head morph bindings
remain valid. Duplicate UV vertices are grouped geometrically for loop finding.
"""
import copy
import numpy as np
from body_template import Buffer, triangles, influences, BIN
from normalize import world_matrices
from body_appearance import sample_color, choose_material, normals as surface_normals

class CannotJoin(ValueError):pass

def unit(v):
    length=np.linalg.norm(v)
    return v/length if length>1e-12 else np.array([0.,0.,-1.])

def topology(doc,buf,mesh_indexes,tolerance):
    positions=[];owners=[];lookup={};edges={};normal_faces={};primitives={}
    for ni,node in enumerate(doc['nodes']):
        if node.get('mesh') not in mesh_indexes or 'skin' not in node:continue
        mi=node['mesh'];skin=doc['skins'][node['skin']]
        for pi,p in enumerate(doc['meshes'][mi]['primitives']):
            key=(mi,pi);primitives[key]=p
            if p.get('mode',4)!=4:continue
            pos=buf.read(p['attributes']['POSITION']);tri=triangles(buf,p);js,ws=influences(buf,p,skin)
            local={}
            for v in np.unique(tri):
                point=pos[v];q=tuple(np.round(point/tolerance).astype(np.int64))
                if q not in lookup:
                    lookup[q]=len(positions);positions.append(point);owners.append([])
                canonical=lookup[q];local[int(v)]=canonical
                weights={}
                for j,w in zip(js[v],ws[v]):
                    if w>1e-6:weights[skin['joints'][j]]=weights.get(skin['joints'][j],0)+float(w)
                owners[canonical].append({'key':key,'vertex':int(v),'weights':weights})
            for face in tri:
                mapped=[local[int(v)] for v in face]
                if len(set(mapped))!=3:continue
                cross=np.cross(pos[face[1]]-pos[face[0]],pos[face[2]]-pos[face[0]])
                for v in mapped:normal_faces[v]=normal_faces.get(v,np.zeros(3))+cross
                for a,b in zip(mapped,mapped[1:]+mapped[:1]):
                    edges.setdefault(tuple(sorted((a,b))),[]).append((a,b))
    boundary=[uses[0] for uses in edges.values() if len(uses)==1]
    neighbors={};outgoing={}
    for a,b in boundary:
        neighbors.setdefault(a,set()).add(b);neighbors.setdefault(b,set()).add(a)
        outgoing.setdefault(a,[]).append(b)
    loops=[];visited=set()
    for start in neighbors:
        if start in visited:continue
        component=set();stack=[start]
        while stack:
            i=stack.pop()
            if i in component:continue
            component.add(i);stack.extend(neighbors[i]-component)
        visited.update(component)
        if len(component)<6 or len(component)>256 or any(len(neighbors[i])!=2 or len(outgoing.get(i,[]))!=1 for i in component):continue
        loop=[];current=start
        while current not in loop:
            loop.append(current);current=outgoing[current][0]
        if current==start and len(loop)==len(component):loops.append(loop)
    return {'positions':np.array(positions),'owners':owners,'loops':loops,'normals':normal_faces,'primitives':primitives,'edges':edges}

def simple_projection(points):
    p=points[:,[0,2]]
    def cross(a,b):return a[0]*b[1]-a[1]*b[0]
    for i in range(len(p)):
        a,b=p[i],p[(i+1)%len(p)]
        if np.linalg.norm(b-a)<1e-8:return False
        for j in range(i+2,len(p)):
            if i==0 and j==len(p)-1:continue
            c,d=p[j],p[(j+1)%len(p)]
            if cross(b-a,c-a)*cross(b-a,d-a)<-1e-16 and cross(d-c,a-c)*cross(d-c,b-c)<-1e-16:return False
    return True

def select_loop(data,neck,cut,height,allowed):
    candidates=[]
    for loop in data['loops']:
        p=data['positions'][loop]
        if not simple_projection(p):continue
        center=p.mean(axis=0);radii=np.linalg.norm(p[:,[0,2]]-center[[0,2]],axis=1)
        if np.ptp(p[:,1])>height*.16:continue
        if abs(center[1]-cut)>height*.16:continue
        if np.linalg.norm(center[[0,2]]-neck[[0,2]])>height*.15:continue
        if not height*.015<np.mean(radii)<height*.20:continue
        if min(radii)/max(max(radii),1e-8)<.35:continue
        coverage=np.mean([sum(w for j,w in data['owners'][i][0]['weights'].items() if j in allowed) for i in loop])
        if coverage<.5:continue
        score=abs(center[1]-cut)+np.linalg.norm(center[[0,2]]-neck[[0,2]])
        candidates.append((score,loop))
    candidates.sort(key=lambda item:item[0])
    if not candidates:raise CannotJoin('首に近い、単純な輪状の境界を検出できませんでした。')
    if len(candidates)>1 and candidates[1][0]-candidates[0][0]<height*.005:
        raise CannotJoin('首の境界候補が複数あり、安全に選べませんでした。')
    loop=candidates[0][1];p=data['positions'][loop]
    if any(len(uses)>2 and (edge[0] in loop or edge[1] in loop) for edge,uses in data['edges'].items()):
        raise CannotJoin('首の周囲に非多様体の辺があります。')
    return loop

def perimeter(points):
    lengths=np.linalg.norm(np.roll(points,-1,axis=0)-points,axis=1)
    if min(lengths)<1e-8:raise CannotJoin('首の境界に短すぎる辺があります。')
    return np.r_[0,np.cumsum(lengths)]/sum(lengths)

def area(points):
    x=points[:,0];z=points[:,2]
    return .5*np.sum(x*np.roll(z,-1)-np.roll(x,-1)*z)

def sample_ring(points,params,values):
    out=[]
    for value in values:
        i=min(np.searchsorted(params,value,side='right')-1,len(points)-1);i=max(0,i)
        t=(value-params[i])/(params[i+1]-params[i]);out.append(points[i]*(1-t)+points[(i+1)%len(points)]*t)
    return np.array(out)

def stitch_neck(doc,chunks,bones,cut,enabled=True,image_decode=None):
    report={'enabled':bool(enabled),'status':'disabled','warnings':[]}
    if not enabled:return doc,chunks,report
    # All mutations happen on copies. A rejected join never damages the output.
    staged=copy.deepcopy(doc);buf=Buffer(staged,chunks)
    try:
        world,parents=world_matrices(staged);neck=world[bones['neck']][:3,3]
        height=float(neck[1]-world[bones['hips']][1,3])
        if height<.05:raise CannotJoin('腰から首の高さが不正です。')
        body=[i for i,m in enumerate(staged['meshes']) if m.get('name')=='TemplateBody']
        if len(body)!=1:raise CannotJoin('補完した体のメッシュを特定できません。')
        body_index=body[0];head_indexes=set(range(len(staged['meshes'])))-{body_index}
        tolerance=max(height*1e-5,1e-7)
        top=topology(staged,buf,head_indexes,tolerance);bottom=topology(staged,buf,{body_index},tolerance)
        tl=select_loop(top,neck,cut,height,{bones['neck'],bones['head']})
        bl=select_loop(bottom,neck,cut,height,{bones[r] for r in ('neck','head','chest','spine') if r in bones})
        tp=top['positions'][tl].copy();bp=bottom['positions'][bl].copy()
        if area(tp)*area(bp)>=0:raise CannotJoin('頭側と体側の面の向きが整合していません。')
        # The head must be above the body's neck opening; large gaps are rejected.
        if tp[:,1].mean()<bp[:,1].mean()-height*.05:raise CannotJoin('頭側の首境界が体側より大きく下にあります。')
        ratio=np.linalg.norm(tp[:,[0,2]]-tp[:,[0,2]].mean(axis=0),axis=1).mean()/np.linalg.norm(bp[:,[0,2]]-bp[:,[0,2]].mean(axis=0),axis=1).mean()
        if not .5<=ratio<=2:raise CannotJoin('首の太さの差が大きいため接合を省略しました。')
        for data,loop in ((top,tl),(bottom,bl)):
            for canonical in loop:
                reference=data['owners'][canonical][0]['weights']
                for owner in data['owners'][canonical][1:]:
                    keys=set(reference)|set(owner['weights'])
                    if sum(abs(reference.get(k,0)-owner['weights'].get(k,0)) for k in keys)>.001:
                        raise CannotJoin('首の同じ位置に異なるウェイトの頂点があり、接合を省略しました。')
        # Reject animated neck edges. Head expression deltas must not open cracks.
        for canonical in tl:
            for owner in top['owners'][canonical]:
                primitive=top['primitives'][owner['key']]
                for target in primitive.get('targets',[]):
                    if 'POSITION' in target and np.linalg.norm(buf.read(target['POSITION'])[owner['vertex']])>height*1e-5:
                        raise CannotJoin('首の境界に表情モーフがあり、接合後の隙間を避けられません。')
        # Follow the head winding; body boundary winding must be reversed.
        bl=bl[::-1];bp=bottom['positions'][bl].copy()
        tc=tp[:,[0,2]].mean(axis=0);bc=bp[:,[0,2]].mean(axis=0)
        angles=np.arctan2(bp[:,2]-bc[1],bp[:,0]-bc[0]);ta=np.arctan2(tp[0,2]-tc[1],tp[0,0]-tc[0])
        start=int(np.argmin(np.abs(np.angle(np.exp(1j*(angles-ta))))));bl=bl[start:]+bl[:start];bp=bottom['positions'][bl].copy()
        tparam=perimeter(tp);bparam=perimeter(bp);matched=sample_ring(tp,tparam,bparam[:-1])
        displacement=matched[:,[0,2]]-bp[:,[0,2]]
        if np.max(np.linalg.norm(displacement,axis=1))>height*.15:raise CannotJoin('首の位置・形の差が大きいため接合を省略しました。')
        # A narrow bridge band avoids zero-area faces on coplanar boundaries.
        band=height*.012
        lower_gaps=[]
        for canonical in bl:
            for edge,uses in bottom['edges'].items():
                if canonical not in edge:continue
                other=edge[1] if edge[0]==canonical else edge[0]
                if other in bl:continue
                gap=bottom['positions'][canonical,1]-bottom['positions'][other,1]
                if gap>height*.0001:lower_gaps.append(gap)
        if lower_gaps:band=min(band,min(lower_gaps)*.35)
        if band<height*.0002:raise CannotJoin('首の接続帯を作る余地がありません。')
        new_bp=bp.copy();new_bp[:,[0,2]]=matched[:,[0,2]]
        # Never raise the body boundary above its original position.
        new_bp[:,1]=np.minimum(bp[:,1],matched[:,1]-band)
        if np.max(tp[:,1])-np.min(new_bp[:,1])>height*.20:raise CannotJoin('首の接続距離が長すぎます。')
        # Match the body boundary to the head without moving the original head.
        edits={};modified_normals={}
        # Fade the ring displacement into a narrow neck neighborhood so a
        # mismatch does not fold the immediately adjacent row of triangles.
        delta=new_bp-bp
        for primitive in bottom['primitives'].values():
            index=primitive['attributes']['POSITION']
            if index in edits:continue
            points=buf.read(index);closest=np.zeros_like(points);movement=np.zeros_like(points);best=np.full(len(points),np.inf)
            for k in range(len(bp)):
                a=bp[k];b=bp[(k+1)%len(bp)];segment=b-a
                t=np.clip((points-a)@segment/max(np.dot(segment,segment),1e-12),0,1)
                projection=a+t[:,None]*segment;distance=np.linalg.norm(points-projection,axis=1);use=distance<best
                closest[use]=projection[use];movement[use]=((1-t[use,None])*delta[k]+t[use,None]*delta[(k+1)%len(bp)])
                best[use]=distance[use]
            weight=np.clip(1-best/(height*.15),0,1);weight=weight*weight*(3-2*weight)
            weight[points[:,1]>np.max(bp[:,1])+tolerance]=0
            edits[index]=points+movement*weight[:,None]
        for canonical,target,old in zip(bl,new_bp,bp):
            for owner in bottom['owners'][canonical]:
                key=owner['key'];primitive=bottom['primitives'][key];index=primitive['attributes']['POSITION']
                edits.setdefault(index,buf.read(index));edits[index][owner['vertex']]=target
        # Reject local face inversion before accepting the new neck edge.
        for key,primitive in bottom['primitives'].items():
            old=buf.read(primitive['attributes']['POSITION']);new=edits.get(primitive['attributes']['POSITION'],old);tri=triangles(buf,primitive)
            old_cross=np.cross(old[tri[:,1]]-old[tri[:,0]],old[tri[:,2]]-old[tri[:,0]])
            new_cross=np.cross(new[tri[:,1]]-new[tri[:,0]],new[tri[:,2]]-new[tri[:,0]])
            valid=np.linalg.norm(old_cross,axis=1)>1e-12
            if np.any(np.sum(old_cross[valid]*new_cross[valid],axis=1)<=0):raise CannotJoin('首の調整で体の面が反転するため接合を省略しました。')
            normal_index=primitive['attributes'].get('NORMAL')
            if normal_index is not None:modified_normals[normal_index]=surface_normals(new,tri,buf.read(normal_index))
        # Triangulate rings with unequal vertex counts by normalized arc length.
        n=len(tp);m=len(bp);faces=[];i=j=0
        while i<n or j<m:
            if j==m or (i<n and tparam[i+1]<=bparam[j+1]):
                faces.append([i%n,n+j%m,(i+1)%n]);i+=1
            else:
                faces.append([i%n,n+j%m,n+(j+1)%m]);j+=1
        positions=np.vstack([tp,new_bp]);faces=np.array(faces,dtype=int)
        cross=np.cross(positions[faces[:,1]]-positions[faces[:,0]],positions[faces[:,2]]-positions[faces[:,0]])
        if np.any(np.linalg.norm(cross,axis=1)<height*height*1e-9):raise CannotJoin('首の接続帯に退化した面ができるため接合を省略しました。')
        bridge_normals=np.zeros_like(positions)
        for column in range(3):np.add.at(bridge_normals,faces[:,column],cross)
        owners=[top['owners'][k][0] for k in tl]+[bottom['owners'][k][0] for k in bl]
        for row,(data,canonical) in enumerate([(top,k) for k in tl]+[(bottom,k) for k in bl]):
            owner=data['owners'][canonical][0];normal_index=data['primitives'][owner['key']]['attributes'].get('NORMAL')
            base=modified_normals[normal_index][owner['vertex']] if normal_index in modified_normals else data['normals'][canonical]
            normal=unit(unit(base)+unit(bridge_normals[row]));bridge_normals[row]=normal
            for owner in data['owners'][canonical]:
                primitive=data['primitives'][owner['key']];index=primitive['attributes'].get('NORMAL')
                if index is not None:
                    modified_normals.setdefault(index,buf.read(index));modified_normals[index][owner['vertex']]=normal
        for index,array in edits.items():
            old=staged['accessors'][index];new=buf.add(array,old['type']);staged['accessors'][index]=staged['accessors'][new].copy()
        for index,array in modified_normals.items():
            old=staged['accessors'][index];new=buf.add(array,old['type']);staged['accessors'][index]=staged['accessors'][new].copy()
        for mesh_value in staged['meshes']:
            for primitive in mesh_value['primitives']:
                if primitive['attributes'].get('NORMAL') in modified_normals:
                    primitive['attributes'].pop('TANGENT',None)
        # Keep the exact boundary weights; interpolation over the band blends them.
        joints=sorted({joint for owner in owners for joint in owner['weights']})
        js=np.zeros((len(owners),8),dtype=np.uint16);ws=np.zeros((len(owners),8))
        for row,owner in enumerate(owners):
            for col,(joint,weight) in enumerate(sorted(owner['weights'].items(),key=lambda item:-item[1])[:8]):
                js[row,col]=joints.index(joint);ws[row,col]=weight
            ws[row]/=ws[row].sum()
        inverse=[]
        for joint in joints:
            matrix=np.eye(4);matrix[:3,3]=-world[joint][:3,3];inverse.append(matrix.T.reshape(-1))
        skin=len(staged['skins']);staged['skins'].append({'joints':joints,'inverseBindMatrices':buf.add(inverse,'MAT4')})
        # Use the template skin's representative color, avoiding stretched atlas UVs.
        body_materials=[p.get('material') for p in staged['meshes'][body_index]['primitives'] if 'material' in p]
        body_material=choose_material(staged,allowed=body_materials)
        if body_material is None:raise CannotJoin('首の接続帯に使う肌材質を特定できませんでした。')
        color=np.array([.8,.65,.55])
        if body_material is not None:
            material=staged['materials'][body_material];color=np.array(material.get('pbrMetallicRoughness',{}).get('baseColorFactor',[1,1,1,1]))[:3]
            if image_decode is None and material.get('pbrMetallicRoughness',{}).get('baseColorTexture'):
                raise CannotJoin('肌テクスチャの代表色を取得できませんでした。')
            if image_decode is not None:
                try:color=sample_color(staged,buf,body_material,image_decode)
                except (ValueError,RuntimeError,OSError):
                    raise CannotJoin('首の接続帯に使う肌色を取得できませんでした。')
        mi=len(staged.setdefault('materials',[]));staged['materials'].append({'name':'NeckJoinSkin','pbrMetallicRoughness':{'baseColorFactor':np.clip(np.r_[color,1],0,1).tolist(),'metallicFactor':0,'roughnessFactor':1},'doubleSided':False})
        attr={'POSITION':buf.add(positions,'VEC3'),'NORMAL':buf.add(bridge_normals,'VEC3')}
        for suffix,start in [('0',0),('1',4)]:
            attr['JOINTS_'+suffix]=buf.add(js[:,start:start+4],'VEC4',5123);attr['WEIGHTS_'+suffix]=buf.add(ws[:,start:start+4],'VEC4')
        mesh=len(staged['meshes']);staged['meshes'].append({'name':'NeckJoin','primitives':[{'attributes':attr,'indices':buf.add(faces.ravel(),'SCALAR',5125),'material':mi}]})
        node=len(staged['nodes']);staged['nodes'].append({'name':'NeckJoin','mesh':mesh,'skin':skin,'translation':[0,0,0]})
        staged['scenes'][staged.get('scene',0)]['nodes'].append(node)
        report.update(status='joined',headVertices=n,bodyVertices=m,bridgeTriangles=len(faces),bandHeight=float(band),
            maxBodyAdjustment=float(np.max(np.linalg.norm(new_bp-bp,axis=1))),warnings=['首の接続帯は肌の代表色を使います。肌模様や陰影の境目が残る場合があります。'])
        return staged,buf.finish(),report
    except CannotJoin as error:
        report.update(status='skipped',reason=str(error),warnings=['首の自動接合を省略: '+str(error)])
        return doc,chunks,report
