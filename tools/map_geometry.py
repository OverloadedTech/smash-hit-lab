#!/usr/bin/env python3
"""Map actual baked quads to source XML boxes using verified face containment.

Ambiguous ownership is reported and disables per-box editing for affected boxes.
No nearest-box heuristic is used. Whole-segment editing remains possible.
"""
from pathlib import Path
import json
import struct
import zlib
import xml.etree.ElementTree as ET
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'analysis/apk/assets'
OUT=ROOT/'dev/assets/shdev/geometry'

def vec(text,default):
    values=[float(x) for x in (text or default).split()]
    if len(values)!=3:raise ValueError(text)
    return values

def build():
    templates={t.attrib['name']:dict(t.find('properties').attrib) for t in ET.parse(SRC/'templates.xml.mp3').getroot() if t.tag=='template'}
    totals=dict(segments=0,boxes=0,quads=0,mapped=0,ambiguous=0,unmapped=0,editable_boxes=0,nonquad_segments=[])
    reports=[]
    for xml in sorted((SRC/'segments').rglob('*.xml.mp3')):
        logical=xml.relative_to(SRC/'segments').as_posix()[:-8]
        mesh=xml.with_name(xml.name[:-8]+'.mesh.mp3')
        data=zlib.decompress(mesh.read_bytes())
        nv,=struct.unpack_from('<I',data)
        raw=np.frombuffer(data,dtype=np.dtype([('p','<f4',(3,)),('uv','<f4',(2,)),('c','u1',(4,))]),count=nv,offset=4)
        nt,=struct.unpack_from('<I',data,4+24*nv)
        triangles=np.frombuffer(data,dtype='<u4',count=nt*3,offset=8+24*nv).reshape(-1,3)
        node=ET.parse(xml).getroot();boxes=[]
        for index,e in enumerate(node):
            if e.tag!='box':continue
            a=dict(templates.get(e.get('template'),{}));a.update(e.attrib)
            boxes.append(dict(source_index=index,ordinal=len(boxes),position=vec(a.get('pos'),'0 0 0'),half_extents=vec(a.get('size'),'1 1 1'),hidden=a.get('hidden','0')!='0',attributes=a,quads=[],ambiguous=False))
        totals['segments']+=1;totals['boxes']+=len(boxes)
        if nv%4 or nt*2!=nv or (len(triangles) and np.any(triangles.min(axis=1)//4!=triangles.max(axis=1)//4)):
            totals['nonquad_segments'].append(logical);continue
        # Every record group consists of four unique render vertices. Determine
        # its oriented plane from an actual indexed triangle, not vertex order.
        quads=raw['p'].reshape(-1,4,3)
        nq=len(quads);totals['quads']+=nq
        normals=np.zeros((nq,3),np.float32)
        if len(triangles):
            tri=raw['p'][triangles]
            normals[triangles[:,0]//4]=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        qmin=quads.min(axis=1);qmax=quads.max(axis=1)
        owners=np.full(nq,-1,dtype=np.int32);matches=np.zeros(nq,dtype=np.int32)
        eps=2e-4
        for i,box in enumerate(boxes):
            if box['hidden']:continue
            pos=np.array(box['position']);size=np.array(box['half_extents']);lo=pos-size;hi=pos+size
            inside=np.all(qmin>=lo-eps,axis=1)&np.all(qmax<=hi+eps,axis=1)
            face=np.zeros(nq,dtype=bool)
            for axis in range(3):
                face|=((np.abs(qmin[:,axis]-hi[axis])<eps)&(np.abs(qmax[:,axis]-hi[axis])<eps)&(normals[:,axis]>1e-7))
                face|=((np.abs(qmin[:,axis]-lo[axis])<eps)&(np.abs(qmax[:,axis]-lo[axis])<eps)&(normals[:,axis]<-1e-7))
            selected=inside&face
            ids=np.flatnonzero(selected)
            box['quads']=ids.tolist();matches[ids]+=1;owners[ids]=i
        for box in boxes:
            box['ambiguous']=any(matches[q]>1 for q in box['quads'])
            box['editable']=bool(box['quads']) and not box['ambiguous']
            totals['editable_boxes']+=int(box['editable'])
        owners[matches!=1]=-1
        stats=dict(segment=logical,vertices=nv,quads=nq,mapped=int(np.sum(matches==1)),ambiguous=int(np.sum(matches>1)),unmapped=int(np.sum(matches==0)))
        for k in ['mapped','ambiguous','unmapped']:totals[k]+=stats[k]
        reports.append(stats)
        target=OUT/(logical+'.json');target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(dict(version=1,source='segments/'+logical+'.xml',mesh='segments/'+logical+'.mesh',vertex_count=nv,boxes=boxes,owners=owners.tolist(),stats=stats),separators=(',',':'))+'\n')
    (ROOT/'analysis/reports/geometry_mapping.json').write_text(json.dumps(dict(totals=totals,segments=reports),indent=2))
    print(json.dumps(totals,indent=2))

if __name__=='__main__':build()
