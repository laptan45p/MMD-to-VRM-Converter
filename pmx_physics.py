"""Read fixed/dynamic bone hints, not rigid-body simulation parameters."""
import io
import struct


class Reader:
    def __init__(self,data):self.file=io.BytesIO(data)
    def read(self,n):
        if n<0:raise ValueError('Invalid PMX length')
        value=self.file.read(n)
        if len(value)!=n:raise ValueError('PMX physics data is truncated')
        return value
    def number(self,fmt):return struct.unpack('<'+fmt,self.read(struct.calcsize('<'+fmt)))[0]
    def count(self):
        value=self.number('i')
        if not 0<=value<=10000000:raise ValueError('Invalid PMX count')
        return value
    def index(self,size):return self.number({1:'b',2:'h',4:'i'}[size])
    def string(self):return self.read(self.count()).decode(self.encoding)


def read_physics_hints(path):
    r=Reader(path.read_bytes())
    if r.read(4)!=b'PMX ':raise ValueError('Not a PMX file')
    r.number('f');header=r.read(r.number('B'))
    if len(header)<8 or header[0] not in (0,1) or any(x not in (1,2,4) for x in header[2:8]):raise ValueError('Invalid PMX header')
    r.encoding='utf-16-le' if header[0]==0 else 'utf-8';h=header
    for _ in range(4):r.string()
    for _ in range(r.count()):
        r.read(32+16*h[1]);kind=r.number('B')
        sizes={0:h[5],1:2*h[5]+4,2:4*h[5]+16,3:2*h[5]+40,4:4*h[5]+16}
        if kind not in sizes:raise ValueError('Unknown PMX weight type')
        r.read(sizes[kind]+4)
    r.read(h[2]*r.count())
    for _ in range(r.count()):r.string()
    for _ in range(r.count()):
        r.string();r.string();r.read(65+2*h[3]+1);shared=r.number('B');r.read(1 if shared else h[3]);r.string();r.read(4)
    bones=[];parents=[]
    for _ in range(r.count()):
        bones.append(r.string());r.string();r.read(12);parents.append(r.index(h[5]));r.read(4);flags=r.number('H')
        r.read(h[5] if flags&1 else 12)
        if flags&0x0300:r.read(h[5]+4)
        if flags&0x0400:r.read(12)
        if flags&0x0800:r.read(24)
        if flags&0x2000:r.read(4)
        if flags&0x0020:
            r.read(h[5]+8)
            for _ in range(r.count()):
                r.read(h[5]);limited=r.number('B')
                if limited:r.read(24)
    for _ in range(r.count()):
        r.string();r.string();r.read(1);kind=r.number('B');count=r.count()
        sizes={0:h[6]+4,1:h[2]+12,2:h[5]+28,3:h[2]+16,4:h[2]+16,5:h[2]+16,6:h[2]+16,7:h[2]+16,8:h[4]+113,9:h[6]+4,10:h[7]+25}
        if kind not in sizes:raise ValueError('Unknown PMX morph type')
        r.read(count*sizes[kind])
    for _ in range(r.count()):
        r.string();r.string();r.read(1)
        for _ in range(r.count()):r.read(h[5] if r.number('B')==0 else h[6])
    modes={}
    for _ in range(r.count()):
        r.string();r.string();bone=r.index(h[5]);r.read(60);mode=r.number('B')
        if mode not in (0,1,2):raise ValueError('Invalid PMX rigid-body mode')
        if 0<=bone<len(bones):modes.setdefault(bone,set()).add(mode)
    controls=set()
    for bone in modes:
        current=parents[bone];seen=set()
        while 0<=current<len(bones) and current not in seen:
            seen.add(current)
            if current not in modes:controls.add(current)
            current=parents[current]
    result={}
    for i in controls:result[bones[i]]={'mode':'control','rigidModes':[]}
    for i,values in modes.items():
        # Conflicting fixed/dynamic bodies are kept fixed conservatively.
        result[bones[i]]={'mode':'fixed' if 0 in values else 'dynamic','rigidModes':sorted(values)}
    return result


def annotate_nodes(document,original_names,hints):
    counts={'fixed':0,'dynamic':0,'control':0}
    for node in document['nodes']:
        name=node.get('name','');hint=hints.get(original_names.get(name,name))
        if hint is not None:
            node.setdefault('extras',{})['mmdPhysics']=hint.copy();counts[hint['mode']]+=1
    return counts
