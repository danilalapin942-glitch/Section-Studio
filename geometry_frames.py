"""OpenVSP Rx Ry Rz component and section frames, in feet."""
import math

def matrix(angles):
 x,y,z=[math.radians(v)for v in angles];cx,sx,cy,sy,cz,sz=math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
 return ((cy*cz,-cy*sz,sy),(cx*sz+sx*sy*cz,cx*cz-sx*sy*sz,-sx*cy),(sx*sz-cx*sy*cz,sx*cz+cx*sy*sz,cx*cy))
def vector(frame,p,inverse=False):
 r=matrix(frame.get('rotation',[0,0,0]));return tuple(sum(p[j]*(r[j][i]if inverse else r[i][j])for j in range(3))for i in range(3))
def world(frame,p):
 p=tuple(p[i]-(frame.get('center',0)if i==0 else 0)for i in range(3));r=vector(frame,p);return tuple(frame['origin'][i]+r[i]for i in range(3))
def local(frame,p):
 r=vector(frame,tuple(p[i]-frame['origin'][i]for i in range(3)),True);return (r[0]+frame.get('center',0),r[1],r[2])
def val(n,path,default=0.):
 e=n.find(path);return float(e.get('Value'))if e is not None else default
def frame_of(g,factor):
 L=val(g,'ParmContainer/Design/Length')*factor;center=L*val(g,'ParmContainer/XForm/Origin');relative=val(g,'ParmContainer/XForm/Abs_Or_Relitive_flag',1)==1
 if relative:
  translation=[val(g,'ParmContainer/XForm/'+k+'_Rel_Location',val(g,'ParmContainer/XForm/'+k+'_Location')-(center/factor if i==0 else 0))*factor for i,k in enumerate('XYZ')]
  origin=[translation[0]+center,translation[1],translation[2]];rotation=[val(g,'ParmContainer/XForm/'+k+'_Rel_Rotation',val(g,'ParmContainer/XForm/'+k+'_Rotation'))for k in 'XYZ']
 else:origin=[val(g,'ParmContainer/XForm/'+k+'_Location')*factor for k in 'XYZ'];rotation=[val(g,'ParmContainer/XForm/'+k+'_Rotation')for k in 'XYZ']
 return {'origin':origin,'rotation':rotation,'center':center,'length':L}

def section_plane(xs,frame):
 p=tuple(val(xs,'ParmContainer/XSec/'+k+'LocPercent')*frame['length']for k in 'XYZ');r=matrix([val(xs,'ParmContainer/XSec/'+k+'Rotate')for k in 'XYZ']);n=vector(frame,tuple(r[k][0]for k in range(3)))
 return {'center':world(frame,p),'normal':n,'localX':p[0]}
