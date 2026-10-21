import struct
import tempfile
import unittest
from pathlib import Path
from pmx_physics import read_physics_hints,annotate_nodes
from spring_bones import setup_springs
import test_springs


def pmx_bytes():
    def string(text):
        data=text.encode('utf-8');return struct.pack('<i',len(data))+data
    out=b'PMX '+struct.pack('<fB',2.,8)+bytes([1,0,1,1,1,1,1,1])
    out+=string('fixture')+string('')*3+struct.pack('<4i',0,0,0,0)
    names=['head','Hair','BackHair','HairStrand1','HairStrand2'];parents=[-1,0,1,2,3]
    out+=struct.pack('<i',len(names))
    for name,parent in zip(names,parents):out+=string(name)+string('')+struct.pack('<3fb i H 3f',0,1,0,parent,0,0,0,.1,0)
    out+=struct.pack('<3i',0,0,3)
    for name,bone,mode in [('head',0,0),('base',2,0),('strand',3,1)]:
        out+=string(name)+string('')+struct.pack('<b',bone)+b'\0'*60+bytes([mode])
    return out


class PhysicsHintTest(unittest.TestCase):
    def test_fixed_dynamic_and_control_bones_are_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.pmx';path.write_bytes(pmx_bytes());hints=read_physics_hints(path)
        self.assertEqual(hints['head']['mode'],'fixed');self.assertEqual(hints['Hair']['mode'],'control')
        self.assertEqual(hints['BackHair']['mode'],'fixed');self.assertEqual(hints['HairStrand1']['mode'],'dynamic')
        self.assertNotIn('HairStrand2',hints)
    def test_truncated_data_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.pmx';path.write_bytes(pmx_bytes()[:-1])
            with self.assertRaises(ValueError):read_physics_hints(path)
    def test_blender_alias_is_annotated(self):
        d={'nodes':[{'name':'Hair.001'}]};counts=annotate_nodes(d,{'Hair.001':'髪'},{'髪':{'mode':'control','rigidModes':[]}})
        self.assertEqual(counts['control'],1);self.assertEqual(d['nodes'][0]['extras']['mmdPhysics']['mode'],'control')
    def test_fixed_cap_and_control_root_are_not_simulated(self):
        d=test_springs.SpringTest().fixture();root=next(i for i,n in enumerate(d['nodes']) if n['name']=='髪')
        cap=root+1;strand=len(d['nodes']);d['nodes'].extend([{'name':'後ろ髪1','children':[strand+1]},{'name':'後ろ髪先'}])
        d['nodes'][cap]['children']=[strand];d['skins'][0]['joints'] += [strand,strand+1]
        d['nodes'][root]['extras']={'mmdPhysics':{'mode':'control'}};d['nodes'][cap]['extras']={'mmdPhysics':{'mode':'fixed'}}
        d['nodes'][strand]['extras']={'mmdPhysics':{'mode':'dynamic'}}
        report=setup_springs(d);hair=[g for g in report['groups'] if g['category']=='hair']
        self.assertEqual([g['node'] for g in hair],[strand]);self.assertNotIn(root,hair[0]['chainNodes']);self.assertNotIn(cap,hair[0]['chainNodes'])
    def test_fixed_anchor_inside_chain_is_a_simulation_boundary(self):
        d=test_springs.SpringTest().fixture();root=next(i for i,n in enumerate(d['nodes']) if n['name']=='髪')
        fixed=root+1;lower=len(d['nodes']);d['nodes'][fixed]['extras']={'mmdPhysics':{'mode':'fixed'}}
        d['nodes'][fixed]['children']=[lower];d['nodes'] += [{'name':'HairLower','children':[lower+1]},{'name':'HairEnd'}];d['skins'][0]['joints'] += [lower,lower+1]
        report=setup_springs(d);hair=[g for g in report['groups'] if g['category']=='hair']
        self.assertEqual([g['node'] for g in hair],[lower])
