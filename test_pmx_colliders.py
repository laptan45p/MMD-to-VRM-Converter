import copy
import math
import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
from pmx_colliders import annotate_colliders, shape_spheres, collide, rebase_colliders, scale_metadata
from pmx_physics import read_physics_data
from spring_bones import setup_springs
from normalize import normalize
import test_pmx_physics
import test_springs

def body(index=0,bone='head',mode=0,shape=0,group=0,mask=65535):
    return {'index':index,'name':'rigid','boneName':bone,'mode':mode,'shape':shape,
            'group':group,'collisionMask':mask,'size':[1,2,1],
            'position':[0,10,0],'rotation':[0,0,0]}

class CollisionTest(unittest.TestCase):
    def test_raw_pmx_bits_are_enabled_pairs_and_require_both_sides(self):
        a=body(group=3,mask=1<<9);b=body(group=9,mask=1<<3)
        self.assertTrue(collide(a,b));b['collisionMask']=0;self.assertFalse(collide(a,b))
        b['collisionMask']=65535;a['collisionMask']=0;self.assertFalse(collide(a,b))

    def test_unrelated_models_do_not_share_collision_group_meanings(self):
        a=body();b=body();a['sourceKey']='source-a';b['sourceKey']='source-b'
        self.assertFalse(collide(a,b));b['sourceKey']='source-a';self.assertTrue(collide(a,b))

    def test_shapes_capsules_keep_radius_and_sample_the_cylinder_plus_endcaps(self):
        spheres,capped=shape_spheres(body(shape=2))
        self.assertEqual(spheres[0][0].tolist(),[0,-1,0]);self.assertEqual(spheres[-1][0].tolist(),[0,1,0])
        self.assertTrue(all(r==1 for _,r in spheres));self.assertFalse(capped)
        b=body(shape=2);b['size']=[.001,100,0];points,capped=shape_spheres(b)
        self.assertTrue(capped);self.assertLessEqual(len(points),64)

    def test_box_half_extents_rotation_and_sampling_limit(self):
        b=body(shape=1);b['size']=[.1,1,2];spheres,capped=shape_spheres(b)
        self.assertLessEqual(len(spheres),64)
        for p,r in spheres:self.assertTrue(np.all(np.abs(p)+r<=np.array(b['size'])+1e-8))
        self.assertTrue(capped)
        b['size']=[1,1,1];spheres,capped=shape_spheres(b);self.assertEqual(len(spheres),1)

    def test_annotation_matches_blender_axis_and_rotation_convention(self):
        doc={'nodes':[{'name':'anchor','translation':[0,.8,0]}]}
        b=body(bone='anchor',shape=2);b['rotation']=[0,0,math.pi/2]
        report=annotate_colliders(doc,{}, {'rigidBodies':[b],'jointCount':2})
        spheres=doc['nodes'][0]['extras']['mmdRigidBodies'][0]['spheres']
        np.testing.assert_allclose(spheres[0]['offset'],[.08,0,0],atol=1e-8)
        self.assertAlmostEqual(spheres[0]['radius'],.08);self.assertEqual(report['sourceJointCount'],2)

    def test_bake_rotates_offsets_without_translation_leaking_into_local_offsets(self):
        nodes=[{'extras':{'mmdRigidBodies':[{'spheres':[{'offset':[1,0,0],'radius':.1}],'hitRadius':.1}]}}]
        pose=np.eye(4);pose[:3,:3]=[[0,-2,0],[2,0,0],[0,0,2]];pose[:3,3]=[10,20,30]
        rebase_colliders(nodes,[pose]);b=nodes[0]['extras']['mmdRigidBodies'][0]
        np.testing.assert_allclose(b['spheres'][0]['offset'],[0,2,0]);self.assertAlmostEqual(b['hitRadius'],.2)
        scaled=scale_metadata(nodes[0]['extras'],.5);self.assertAlmostEqual(scaled['mmdRigidBodies'][0]['hitRadius'],.1)
        self.assertAlmostEqual(b['hitRadius'],.2)

    def test_unknown_and_invalid_rigids_are_reported_not_attached_to_random_bones(self):
        d={'nodes':[{'name':'head'}]};a=body();a['size'][0]=float('nan')
        report=annotate_colliders(d,{}, {'rigidBodies':[a,body(1,bone='missing')],'jointCount':0})
        self.assertEqual(report['mappedRigidCount'],0);self.assertEqual(len(report['skipped']),2)

    def test_source_filters_apply_to_every_category_and_preserve_explicit_disabled_pairs(self):
        d=test_springs.SpringTest().fixture();head=next(i for i,n in enumerate(d['nodes']) if n['name']=='head')
        record={'index':0,'group':3,'collisionMask':65535,'mode':0,'spheres':[{'offset':[0,0,0],'radius':.1}],'hitRadius':.1}
        d['nodes'][head]['extras']={'mmdRigidBodies':[record]}
        for i,n in enumerate(d['nodes']):
            if n.get('name') in ('髪','リボン','袖','スカート','左胸'):
                dynamic=copy.deepcopy(record);dynamic.update(index=i+1,group=9,collisionMask=1<<3,mode=1,hitRadius=.007)
                n['extras']={'mmdRigidBodies':[dynamic]}
        report=setup_springs(d);groups=d['extensions']['VRM']['secondaryAnimation']['boneGroups']
        self.assertTrue(all(g['colliderGroups'] for g in groups));self.assertEqual(report['pmxColliderCount'],1)
        self.assertTrue(all(g['collisionSource']=='pmx' for g in report['groups']))
        self.assertTrue(all(g['hitRadius']==.007 for g in groups))
        record['collisionMask']=0;report=setup_springs(d)
        self.assertTrue(all(not g['colliderGroups'] for g in d['extensions']['VRM']['secondaryAnimation']['boneGroups']))
        report=setup_springs(d,options={'colliders':False});self.assertEqual(report['colliderCount'],0)

    def test_mixed_chain_filters_use_intersection_not_union(self):
        d=test_springs.SpringTest().fixture();head=next(i for i,n in enumerate(d['nodes']) if n['name']=='head');root=next(i for i,n in enumerate(d['nodes']) if n['name']=='髪')
        fixed={'index':0,'group':3,'collisionMask':65535,'mode':0,'spheres':[{'offset':[0,0,0],'radius':.1}],'hitRadius':.1}
        d['nodes'][head]['extras']={'mmdRigidBodies':[fixed]}
        for i,mask in [(root,65535),(root+1,0)]:
            r=copy.deepcopy(fixed);r.update(index=i+1,mode=1,group=9,collisionMask=mask)
            d['nodes'][i]['extras']={'mmdRigidBodies':[r]}
        report=setup_springs(d);hair=next(g for g in report['groups'] if g['category']=='hair')
        self.assertEqual(hair['colliderGroups'],[])

    def test_dynamic_unnamed_accessories_are_included_without_simulating_fixed_roots(self):
        d=test_springs.SpringTest().fixture();i=len(d['nodes'])
        d['nodes'] += [{'name':'accessory_007','children':[i+1],'extras':{'mmdPhysics':{'mode':'dynamic'}}},{'name':'end'}]
        d['skins'][0]['joints'] += [i,i+1];report=setup_springs(d)
        self.assertTrue(any(g['category']=='other' and g['node']==i for g in report['groups']))
        disabled=setup_springs(d,options={'other':{'enabled':False}})
        self.assertFalse(any(g['category']=='other' for g in disabled['groups']))

    def test_vrm0_serialization_converts_collider_offsets_from_gltf_to_unity(self):
        from spring_bones import vrm0_offset
        self.assertEqual(vrm0_offset([.1,.2,.3]),{'x':.1,'y':.2,'z':-.3})

    def test_head_transplant_keeps_and_scales_source_collider_metadata(self):
        from test_head_transplant import HeadTransplantTest
        from head_transplant import transplant_head
        case=HeadTransplantTest();case.setUp()
        try:
            d,c,b=case.source();head=b['head']
            record={'index':0,'group':0,'collisionMask':65535,'mode':0,'shape':0,'spheres':[{'offset':[.01,.02,.03],'radius':.04}],'hitRadius':.04}
            d['nodes'][head].setdefault('extras',{})['mmdRigidBodies']=[record]
            c,report,_=transplant_head(d,c,b,case.path,log=lambda _:None)
            out=d['nodes'][b['head']]['extras']['mmdRigidBodies'][0]
            self.assertAlmostEqual(out['spheres'][0]['radius'],.04*report['headScale'])
            np.testing.assert_allclose(out['spheres'][0]['offset'],np.array([.01,.02,.03])*report['headScale'])
        finally:case.tearDown()

    def test_reader_keeps_rigid_fields_and_bone_positions(self):
        data=test_pmx_physics.pmx_bytes()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'fixture.pmx';path.write_bytes(data);result=read_physics_data(path)
        self.assertEqual(len(result['rigidBodies']),3);self.assertEqual(result['rigidBodies'][-1]['mode'],1)
        self.assertEqual(result['bones'][0]['position'],[0,1,0])

    def test_normalizer_rebases_metadata_in_the_real_pose_baking_path(self):
        import test_body_template
        d,chunks,bones=test_body_template.fixture();i=bones['leftLowerArm']
        d['nodes'][bones['leftHand']]['translation'][1]=-.15
        d['nodes'][i].setdefault('extras',{})['mmdRigidBodies']=[{'spheres':[{'offset':[0,.1,0],'radius':.01}],'hitRadius':.01}]
        before=copy.deepcopy(d['nodes'][i]['extras']);chunks=normalize(d,chunks,bones,lambda _:None)
        after=d['nodes'][i]['extras'];self.assertNotEqual(before,after)
        np.testing.assert_allclose(np.linalg.norm(after['mmdRigidBodies'][0]['spheres'][0]['offset']),.1)
        expected=copy.deepcopy(after);normalize(d,chunks,bones,lambda _:None)
        np.testing.assert_allclose(d['nodes'][i]['extras']['mmdRigidBodies'][0]['spheres'][0]['offset'],expected['mmdRigidBodies'][0]['spheres'][0]['offset'])
