"""Fit a body to anatomical landmarks rather than coincident MMD controls."""
import numpy as np

def torso_landmarks(source, donor, source_bones, donor_bones):
    source=np.asarray(source,dtype=float);donor=np.asarray(donor,dtype=float)
    fitted=source.copy()
    sm=(source[source_bones['leftUpperLeg']]+source[source_bones['rightUpperLeg']])/2
    dm=(donor[donor_bones['leftUpperLeg']]+donor[donor_bones['rightUpperLeg']])/2
    sn=source[source_bones['neck']];dn=donor[donor_bones['neck']]
    height=float(sn[1]-sm[1]);donor_height=float(dn[1]-dm[1])
    if min(height,donor_height)<.03:raise ValueError('脚の付け根から首の高さが不正です。')
    scale=height/donor_height
    if not .1<scale<10:raise ValueError('元モデルと補完素体の大きさが大幅に異なります。')
    sh=source[source_bones['hips']];ss=source[source_bones['spine']]
    dh=donor[donor_bones['hips']];ds=donor[donor_bones['spine']]
    expected_gap=max(float(ds[1]-dh[1])*scale,0)
    actual_gap=float(ss[1]-sh[1]);expected_hip_offset=max(float(dh[1]-dm[1])*scale,0)
    # MMD lower/upper-body control bones often share a waist-level origin.
    # They remain animation controls; only fitting landmarks are substituted.
    collapsed=expected_gap>.005 and actual_gap<expected_gap*.35
    elevated=expected_hip_offset>.005 and sh[1]-sm[1]>expected_hip_offset*2
    adjusted=bool(collapsed or elevated)
    roles=[role for role in ('hips','spine','chest','upperChest') if role in source_bones and role in donor_bones]
    report={'adjusted':adjusted,'strategy':'template_torso_proportions' if adjusted else 'source_landmarks',
        'sourceHipSpineGap':actual_gap,'referenceHipSpineGap':expected_gap,
        'sourcePositions':{role:source[source_bones[role]].tolist() for role in roles}}
    if adjusted:
        for role in roles:
            p=donor[donor_bones[role]];t=float((p[1]-dm[1])/donor_height)
            reference=dm+t*(dn-dm)
            fitted[source_bones[role]]=sm+t*(sn-sm)+(p-reference)*scale
    report['fittedPositions']={role:fitted[source_bones[role]].tolist() for role in roles}
    return fitted,scale,report

def neutral_body_material(properties):
    """Remove template-specific rim, emission and outline effects."""
    properties['shader']='VRM/MToon'
    floats=properties.setdefault('floatProperties',{})
    floats.update({'_OutlineWidthMode':0,'_OutlineWidth':0,'_RimLightingMix':0,'_RimLift':0,
        '_ShadeShift':0,'_ShadeToony':.9,'_ShadingGradeRate':1,'_IndirectLightIntensity':.1,
        '_LightColorAttenuation':0,'_UvAnimScrollX':0,'_UvAnimScrollY':0,'_UvAnimRotation':0})
    vectors=properties.setdefault('vectorProperties',{})
    vectors['_RimColor']=[0,0,0,1];vectors['_EmissionColor']=[0,0,0,1];vectors['_ShadeColor']=[.8,.8,.8,1]
    textures=properties.setdefault('textureProperties',{})
    main=textures.get('_MainTex')
    bump=textures.get('_BumpMap')
    properties['textureProperties']={} if main is None else {'_MainTex':main,'_ShadeTexture':main}
    if bump is not None:properties['textureProperties']['_BumpMap']=bump
    vectors['_ShadeTexture']=vectors.get('_MainTex',[0,0,1,1]).copy()
    return properties
