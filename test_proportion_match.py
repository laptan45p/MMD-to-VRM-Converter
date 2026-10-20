import unittest
import numpy as np
from proportion_match import build_plan,apply_plan,skin_materials,LIMBS
from test_body_template import fixture
from normalize import world_matrices


class ProportionMatchTest(unittest.TestCase):
    def setUp(self):
        d,c,b=fixture();world,_=world_matrices(d)
        self.positions={r:world[i][:3,3] for r,i in b.items()}
    def samples(self,width=1,depth=1,front_only=False):
        theta=np.linspace(0,2*np.pi,80,endpoint=False)
        if front_only:theta=theta[np.sin(theta)<-.5]
        p=[];n=[]
        for y in np.linspace(.72,1.43,80):
            for t in theta:
                p.append([np.cos(t)*.11*width,y,np.sin(t)*.075*depth]);n.append([np.cos(t),0,np.sin(t)])
        p=np.array(p);n=np.array(n);r={key:np.zeros(len(p)) for key in ('torso',)+LIMBS};r['torso'][:]=1
        return p,n,r
    def plan(self,source,donor,enabled=True):
        return build_plan(source,donor,self.positions,self.positions,self.positions,1,enabled)
    def test_skin_cross_sections_match_source_and_keep_height(self):
        source=self.samples(.8,.9);donor=self.samples();plan,report=self.plan(source,donor)
        out=apply_plan(donor[0],donor[2],self.positions,plan)
        np.testing.assert_allclose(out[:,0],source[0][:,0],atol=1e-6)
        np.testing.assert_allclose(out[:,2],source[0][:,2],atol=1e-6)
        np.testing.assert_array_equal(out[:,1],donor[0][:,1])
        self.assertEqual(report['status'],'applied')
    def test_clothes_are_never_selected_as_skin(self):
        d={'materials':[{'name':'Body_Cloth'},{'name':'skin'},{'name':'skirt_skin'},{'name':'hair'},{'name':'素体'}]}
        self.assertEqual(skin_materials(d),{1,4})
    def test_missing_skin_uses_skeleton_width_and_preserves_depth(self):
        donor=self.samples();empty=(np.empty((0,3)),np.empty((0,3)),{key:np.empty(0) for key in donor[2]})
        source_positions={r:p.copy() for r,p in self.positions.items()}
        for role in ('leftUpperArm','rightUpperArm','leftUpperLeg','rightUpperLeg'):source_positions[role][0]*=.8
        plan,report=build_plan(empty,donor,self.positions,source_positions,self.positions,1)
        out=apply_plan(donor[0],donor[2],self.positions,plan)
        np.testing.assert_allclose(out[:,0],donor[0][:,0]*.8)
        np.testing.assert_array_equal(out[:,2],donor[0][:,2]);self.assertTrue(report['warnings'])
    def test_front_only_skin_patch_does_not_flatten_torso(self):
        source=self.samples(.8,.4,True);donor=self.samples();plan,report=self.plan(source,donor)
        self.assertTrue(all(x['methods'][1]=='unchanged' for x in report['torso']))
        out=apply_plan(donor[0],donor[2],self.positions,plan)
        np.testing.assert_array_equal(out[:,2],donor[0][:,2])
    def test_disabled_matching_is_identity(self):
        donor=self.samples();plan,report=self.plan(self.samples(.7,.8),donor,False)
        self.assertIsNone(plan);self.assertEqual(report['status'],'disabled')
        np.testing.assert_array_equal(apply_plan(donor[0],donor[2],self.positions,plan),donor[0])
    def test_extreme_measurement_is_limited(self):
        plan,report=self.plan(self.samples(.4,2),self.samples())
        self.assertTrue(np.all(plan['factors']>=.65));self.assertTrue(np.all(plan['factors']<=1.35))
    def test_limb_thickness_matches_skin_without_moving_bone_axis(self):
        role='leftUpperArm';a=self.positions[role];b=self.positions['leftLowerArm']
        def limb(radius):
            points=[];normals=[]
            for t in np.linspace(.21,.79,35):
                for angle in np.linspace(0,2*np.pi,64,endpoint=False):
                    normal=np.array([0,np.cos(angle),np.sin(angle)])
                    points.append(a+(b-a)*t+radius*normal);normals.append(normal)
            p=np.array(points);r={key:np.zeros(len(p)) for key in ('torso',)+LIMBS};r[role][:]=1
            return p,np.array(normals),r
        source=limb(.024);donor=limb(.03);plan,report=self.plan(source,donor)
        self.assertAlmostEqual(plan['limbs'][role],.8,places=5)
        result=apply_plan(donor[0],donor[2],self.positions,plan)
        np.testing.assert_allclose(result,source[0],atol=1e-6)
    def test_manual_width_is_kept_after_automatic_matching(self):
        source=self.samples(.8,.9);donor=self.samples(.9,.9)
        plan,report=build_plan(source,donor,self.positions,self.positions,self.positions,1,True,.9)
        out=apply_plan(donor[0],donor[2],self.positions,plan)
        np.testing.assert_allclose(out[:,0],source[0][:,0]*.9,atol=1e-6)
        np.testing.assert_allclose(out[:,2],source[0][:,2]*.9,atol=1e-6)
    def test_shoulder_height_preserves_neck_and_hip_planes(self):
        from proportion_match import shoulder_height
        points=np.array([[0,.8,0],[.1,1.3,.02],[0,1.4,0],[.3,1.3,0]])
        out=shoulder_height(points,np.array([1,1,1,0]),{'from':[.8,1.3,1.4],'to':[.8,1.25,1.4]})
        np.testing.assert_allclose(out[:,1],[.8,1.25,1.4,1.3])
        np.testing.assert_array_equal(out[:,[0,2]],points[:,[0,2]])
