"""Triangle-surface distances using an AABB hierarchy. Standard library only.

Distances refer to the supplied tessellation, in feet. They are not distances
between analytical CAD surfaces. A stopped traversal is never a passed check.
"""
from __future__ import annotations
import heapq
import math
import time
from native_control import check_cancel

def sub(a,b): return (a[0]-b[0],a[1]-b[1],a[2]-b[2])
def add(a,b): return (a[0]+b[0],a[1]+b[1],a[2]+b[2])
def mul(a,t): return (a[0]*t,a[1]*t,a[2]*t)
def dot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def norm2(a): return dot(a,a)
def point_segment(p,a,b):
    d=sub(b,a);dd=norm2(d);t=max(0.,min(1.,dot(sub(p,a),d)/dd))if dd else 0.
    q=add(a,mul(d,t));return norm2(sub(p,q)),p,q

def point_triangle(p,t):
    a,b,c=t;ab=sub(b,a);ac=sub(c,a);ap=sub(p,a);d1=dot(ab,ap);d2=dot(ac,ap)
    if d1<=0 and d2<=0:return norm2(ap),p,a
    bp=sub(p,b);d3=dot(ab,bp);d4=dot(ac,bp)
    if d3>=0 and d4<=d3:return norm2(bp),p,b
    vc=d1*d4-d3*d2
    if vc<=0 and d1>=0 and d3<=0:
        q=add(a,mul(ab,d1/(d1-d3)));return norm2(sub(p,q)),p,q
    cp=sub(p,c);d5=dot(ab,cp);d6=dot(ac,cp)
    if d6>=0 and d5<=d6:return norm2(cp),p,c
    vb=d5*d2-d1*d6
    if vb<=0 and d2>=0 and d6<=0:
        q=add(a,mul(ac,d2/(d2-d6)));return norm2(sub(p,q)),p,q
    va=d3*d6-d5*d4
    if va<=0 and d4-d3>=0 and d5-d6>=0:
        q=add(b,mul(sub(c,b),(d4-d3)/((d4-d3)+(d5-d6))));return norm2(sub(p,q)),p,q
    den=va+vb+vc
    if abs(den)<1e-35:return min((point_segment(p,a,b),point_segment(p,b,c),point_segment(p,c,a)),key=lambda z:z[0])
    q=add(a,add(mul(ab,vb/den),mul(ac,vc/den)));return norm2(sub(p,q)),p,q

def segment_segment(p0,p1,q0,q1):
    u=sub(p1,p0);v=sub(q1,q0);w=sub(p0,q0);a=dot(u,u);b=dot(u,v);c=dot(v,v);d=dot(u,w);e=dot(v,w);den=a*c-b*b
    if a<1e-30:
        rr=point_segment(p0,q0,q1);return rr
    if c<1e-30:
        rr=point_segment(q0,p0,p1);return rr[0],rr[2],rr[1]
    s=max(0.,min(1.,(b*e-c*d)/den))if den>1e-30*a*c else 0.
    t=(b*s+e)/c
    if t<0:t=0.;s=max(0.,min(1.,-d/a))
    elif t>1:t=1.;s=max(0.,min(1.,(b-d)/a))
    p=add(p0,mul(u,s));q=add(q0,mul(v,t));return norm2(sub(p,q)),p,q

def segment_triangle(p,q,t,eps=1e-12):
    a,b,c=t;d=sub(q,p);e1=sub(b,a);e2=sub(c,a);h=cross(d,e2);det=dot(e1,h)
    scale=math.sqrt(norm2(d)*norm2(e1)*norm2(e2))
    if abs(det)<=eps*max(scale,1e-30):return None
    inv=1/det;s=sub(p,a);u=dot(s,h)*inv
    if u < -eps or u > 1+eps:return None
    r=cross(s,e1);v=dot(d,r)*inv;z=dot(e2,r)*inv
    if v < -eps or u+v>1+eps or z < -eps or z>1+eps:return None
    return add(p,mul(d,max(0.,min(1.,z)))),eps<z<1-eps and u>eps and v>eps and u+v<1-eps

def triangle_distance(a,b):
    for t,s in [(a,b),(b,a)]:
        for i in range(3):
            hit=segment_triangle(t[i],t[(i+1)%3],s)
            if hit:return 0.,hit[0],hit[0],hit[1]
    best=(math.inf,None,None)
    for p in a:best=min(best,point_triangle(p,b),key=lambda z:z[0])
    for p in b:
        d,x,y=point_triangle(p,a);best=min(best,(d,y,x),key=lambda z:z[0])
    for i in range(3):
        for j in range(3):best=min(best,segment_segment(a[i],a[(i+1)%3],b[j],b[(j+1)%3]),key=lambda z:z[0])
    return *best,False

def box_distance(a,b):
    return sum(max(0.,a[k]-b[k+3],b[k]-a[k+3])**2 for k in range(3))

class BVH:
    def __init__(self,triangles,indices=None):
        self.triangles=triangles
        self.boxes=[tuple(min(p[k]for p in t)for k in range(3))+tuple(max(p[k]for p in t)for k in range(3))for t in triangles]
        self.nodes=[];self.root=self.build(list(range(len(triangles)))if indices is None else indices)
    def build(self,ids):
        if not ids:raise ValueError('Нет невырожденных треугольников для проверки зазора.')
        boxes=self.boxes;bb=tuple(min(boxes[i][k]for i in ids)for k in range(3))+tuple(max(boxes[i][k+3]for i in ids)for k in range(3))
        n=len(self.nodes);self.nodes.append(None)
        if len(ids)<=8:self.nodes[n]=(bb,None,None,ids)
        else:
            axis=max(range(3),key=lambda k:bb[k+3]-bb[k]);ids.sort(key=lambda i:boxes[i][axis]+boxes[i][axis+3]);mid=len(ids)//2
            left=self.build(ids[:mid]);right=self.build(ids[mid:]);self.nodes[n]=(bb,left,right,None)
        return n
    def nearest(self,other,max_tests=2_000_000,seconds=40):
        start=time.monotonic();queue=[(box_distance(self.nodes[0][0],other.nodes[0][0]),0,0)];best=(math.inf,None,None,False);ids=(None,None);tests=0;complete=True
        while queue:
            check_cancel()
            bound,i,j=heapq.heappop(queue)
            if bound>best[0]+1e-24:continue
            if tests>=max_tests or time.monotonic()-start>seconds:complete=False;break
            a=self.nodes[i];b=other.nodes[j]
            if a[3]is not None and b[3]is not None:
                for x in a[3]:
                    for y in b[3]:
                        if box_distance(self.boxes[x],other.boxes[y])>best[0]+1e-24:continue
                        q=triangle_distance(self.triangles[x],other.triangles[y]);tests+=1
                        if q[0]<best[0]or q[3]:best=q;ids=(x,y)
                        if best[0]<1e-24:
                            return {'distanceFt':0.,'pointA':best[1],'pointB':best[2],'crossing':best[3],'complete':True,'distanceComplete':True,'tests':tests,'triangleA':ids[0],'triangleB':ids[1],'elapsedSeconds':time.monotonic()-start}
            else:
                split_a=b[3]is not None or a[3]is None and sum((a[0][k+3]-a[0][k])**2 for k in range(3))>=sum((b[0][k+3]-b[0][k])**2 for k in range(3))
                for x,y in [(a[1],j),(a[2],j)]if split_a else [(i,b[1]),(i,b[2])]:
                    q=box_distance(self.nodes[x][0],other.nodes[y][0])
                    if q<=best[0]+1e-24:heapq.heappush(queue,(q,x,y))
        return {'distanceFt':math.sqrt(best[0])if math.isfinite(best[0])else None,'pointA':best[1],'pointB':best[2],'crossing':best[3],'complete':complete,'distanceComplete':complete,'tests':tests,'triangleA':ids[0],'triangleB':ids[1],'elapsedSeconds':time.monotonic()-start}
    def nearest_point(self,p,cutoff=math.inf,max_tests=5000):
        box=tuple(p)+tuple(p);best=cutoff*cutoff;closest=None;face=None;tests=0;queue=[(box_distance(box,self.nodes[0][0]),0)]
        while queue:
            check_cancel()
            bound,i=heapq.heappop(queue)
            if bound>best:continue
            if tests>=max_tests:return {'complete':False,'tests':tests,'distanceFt':math.sqrt(best),'point':closest,'triangle':face,'atLeast':closest is None}
            node=self.nodes[i]
            if node[3]is not None:
                for j in node[3]:
                    if box_distance(box,self.boxes[j])>best:continue
                    d,_,q=point_triangle(p,self.triangles[j]);tests+=1
                    if d<=best:best=d;closest=q;face=j
            else:
                for j in node[1:3]:
                    d=box_distance(box,self.nodes[j][0])
                    if d<=best:heapq.heappush(queue,(d,j))
        return {'complete':True,'tests':tests,'distanceFt':math.sqrt(best),'point':closest,'triangle':face,'atLeast':closest is None}
    def contains(self,point):
        # Non-axis ray; merge hits on shared edges/vertices before parity counting.
        b=self.nodes[0][0]
        if any(point[k]<b[k]-1e-9 or point[k]>b[k+3]+1e-9 for k in range(3)):return False
        length=10*math.sqrt(sum((b[k+3]-b[k])**2 for k in range(3)))+1
        end=add(point,mul((.8574929257,.431622,.28079),length));raybox=tuple(min(point[k],end[k])for k in range(3))+tuple(max(point[k],end[k])for k in range(3));stack=[0];hits=[]
        while stack:
            n=self.nodes[stack.pop()]
            if box_distance(n[0],raybox)>0:continue
            if n[3]is None:stack.extend(n[1:3]);continue
            for i in n[3]:
                h=segment_triangle(point,end,self.triangles[i])
                if h and math.dist(h[0],point)>1e-8:hits.append(math.dist(h[0],point))
        hits.sort();unique=[]
        for h in hits:
            if not unique or h-unique[-1]>max(1e-8,length*1e-10):unique.append(h)
        return len(unique)%2==1

def triangle_area(t):return .5*math.sqrt(norm2(cross(sub(t[1],t[0]),sub(t[2],t[0]))))

def check_pairs(mesh,pairs,components):
    nodes,faces,fp=mesh['nodes'],mesh['faces'],mesh['faceParts'];parts=mesh['parts']
    if isinstance(parts,list):parts={p['part']:p for p in parts}
    caches={};records={}
    for gid in {p[k]for p in pairs for k in ('a','b')}:
        ids=[i for i,f in enumerate(faces)if parts[fp[i]]['geomId']==gid and len(f)==3 and triangle_area([nodes[n]for n in f])>1e-18]
        if not ids:raise ValueError('В сетке нет поверхности компонента '+components.get(gid,gid))
        tris=[tuple(nodes[n]for n in faces[i])for i in ids];caches[gid]=BVH(tris);records[gid]=ids
    result=[]
    for p in pairs:
        a,b=caches[p['a']],caches[p['b']];r=a.nearest(b);contained=False
        if r['complete'] and r['distanceFt'] is not None and r['distanceFt']>1e-8:
            # Probe each original mesh part; a fully enclosed disconnected part
            # must not pass just because its skin has positive clearance.
            for source,target,gid in [(a,b,p['a']),(b,a,p['b'])]:
                seen=set()
                for ti,fi in enumerate(records[gid]):
                    if fp[fi]in seen:continue
                    seen.add(fp[fi]);t=source.triangles[ti];probe=tuple(sum(q[k]for q in t)/3 for k in range(3))
                    if target.contains(probe):contained=True;break
                if contained:break
        r.update(a=p['a'],b=p['b'],nameA=components.get(p['a'],p['a']),nameB=components.get(p['b'],p['b']),minimumGapFt=p['minimumGapFt'],toleranceFt=p['toleranceFt'],contained=contained)
        for side,gid in [('A',p['a']),('B',p['b'])]:
            ti=r['triangle'+side];r['face'+side]=records[gid][ti]if ti is not None else None
            if ti is not None:
                t=caches[gid].triangles[ti];n=cross(sub(t[1],t[0]),sub(t[2],t[0]));length=math.sqrt(norm2(n));r['normal'+side]=mul(n,1/length)if length else None
        r['state']='incomplete'if not r['complete']else'overlap'if contained or r['crossing']else'contact'if r['distanceFt']<=1e-8 else'below-limit'if r['distanceFt']+p['toleranceFt']<p['minimumGapFt']else'clear'
        r['passed']=r['state']=='clear'
        result.append(r)
    return result

def distance_field(mesh,pairs,seconds=20,max_tests=2_000_000):
    """Centroid samples, with exact distances only inside the displayed band."""
    start=time.monotonic();parts=mesh['parts'];caches={};records={};values={};tests=0;complete=True;visited=0
    for gid in {p[k]for p in pairs for k in ('a','b')}:
        ids=[i for i,f in enumerate(mesh['faces'])if parts[mesh['faceParts'][i]]['geomId']==gid and triangle_area([mesh['nodes'][j]for j in f])>1e-18]
        records[gid]=ids;caches[gid]=BVH([tuple(mesh['nodes'][j]for j in mesh['faces'][i])for i in ids])
    possible=sum(len(records[p['a']])+len(records[p['b']])for p in pairs)
    for pi,pair in enumerate(pairs):
        band=max(.05,10*pair['minimumGapFt'])
        for source,target in [(pair['a'],pair['b']),(pair['b'],pair['a'])]:
            for fi in records[source]:
                check_cancel()
                if tests>=max_tests or time.monotonic()-start>seconds:complete=False;break
                t=[mesh['nodes'][j]for j in mesh['faces'][fi]];p=tuple(sum(v[k]for v in t)/3 for k in range(3));r=caches[target].nearest_point(p,band,min(5000,max_tests-tests));tests+=r['tests'];visited+=1
                if not r['complete']:complete=False;continue
                value={'distanceFt':r['distanceFt'],'atLeast':r['atLeast'],'minimumGapFt':pair['minimumGapFt'],'pairIndex':pi}
                prev=values.get(str(fi))
                if prev is None or value['distanceFt']/max(value['minimumGapFt'],1e-8)<prev['distanceFt']/max(prev['minimumGapFt'],1e-8):values[str(fi)]=value
            if not complete:break
        if not complete:break
    return {'method':'native-TRI-centroid-distance-band','faces':values,'complete':complete,'visitedFaces':visited,'possibleFaceVisits':possible,'tests':tests,'elapsedSeconds':time.monotonic()-start,'note':'Цвет — расстояние в центре треугольника. За пределами полосы показана доказанная нижняя граница. Глобальные минимумы пар проверяются отдельно по целым треугольникам.'}
