"""OpenVSP 3.51 Engine Model parameter bridge. OpenVSP owns all updates."""
import hashlib
import json
import math
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from native_audit import run_script

PARMS=['GeomIOType','GeomInType','GeomOutType','InletFaceMode','InletLipMode','OutletFaceMode','OutletLipMode',
       'InletFaceIndex','InletLipIndex','InletFaceU','InletLipU','OutletFaceIndex','OutletLipIndex','OutletFaceU','OutletLipU',
       'EngineShowStationsFlag','InletModeType','OutletModeType','RotExtensionFlag','ExtensionDistance','AutoExtensionSet','AutoExtensionFlag']


def active_parameters(v):
    """Pinned GeomEngine::ValidateParms, mirrored for the controls only."""
    active={'GeomIOType','EngineShowStationsFlag'}
    mode=int(v['GeomIOType'])
    def location(side,place):
        prefix=side+place
        active.add(prefix+'Mode')
        active.add(prefix+('U' if int(v[prefix+'Mode']) else 'Index'))
    def extension():
        active.update(['RotExtensionFlag','AutoExtensionFlag'])
        active.add('AutoExtensionSet' if v['AutoExtensionFlag'] else 'ExtensionDistance')
    if mode:
        if mode<=2:
            active.update(['GeomInType','InletModeType']);location('Inlet','Lip')
            if int(v['GeomInType'])!=1:location('Inlet','Face')
            if int(v['InletModeType'])==7:extension()
        if mode>=2:
            if not(mode==2 and int(v['GeomInType']) in (0,2)):active.add('GeomOutType')
            active.add('OutletModeType');location('Outlet','Lip')
            if int(v['GeomOutType'])!=1 or (mode==2 and int(v['GeomInType'])==0):location('Outlet','Face')
            if int(v['OutletModeType'])==7:extension()
    if int(v['InletModeType']) in (0,1,2):active.discard('OutletModeType')
    return sorted(active)


def engine_update(executable,xml,gid,changes=None):
    root=ET.fromstring(xml)
    g=next((g for g in root.findall('./Vehicle/Geom') if g.findtext('ParmContainer/ID')==gid),None)
    if g is None or g.findtext('GeomBase/TypeName')!='Fuselage':
        raise ValueError('Выбери Fuselage-компонент с Engine Model.')
    changes=[] if changes is None else changes
    if not isinstance(changes,list) or len(changes)>100:raise ValueError('Неверный список правок Engine Model.')
    statements=[]
    for edit in changes:
        if not isinstance(edit,dict) or edit.get('name') not in PARMS:raise ValueError('Неизвестный параметр Engine Model.')
        val=edit.get('value')
        if isinstance(val,bool):val=int(val)
        if not isinstance(val,(float,int)) or not math.isfinite(val) or abs(val)>1e12:
            raise ValueError('Нужно конечное числовое значение Engine Model.')
        statements.append('SetParmVal(g,'+json.dumps(edit['name'])+',"EngineModel",'+repr(float(val))+');Update();')
    script='''int main(){ReadVSPFile("Source.vsp3");Update();
if(GetVSPVersionMajor()!=3||GetVSPVersionMinor()!=51){Print("SECTION_STUDIO_ERROR: Requires OpenVSP 3.51.x");return 1;}
string g=GID;
CHANGES
file f;f.open("EngineInfo.json","w");f.writeString("{\\\"version\\\":\\\""+GetVSPVersion()+"\\\",\\\"sectionCount\\\":"+GetNumXSec(GetXSecSurf(g,0))+",\\\"parameters\\\":{");
PARMS
f.writeString("},\\\"sets\\\":[");for(int i=0;i<GetNumSets();i++){if(i>0)f.writeString(",");f.writeString(formatInt(i));}f.writeString("]}");f.close();file names;names.open("SetNames.bin","w");for(int i=0;i<GetNumSets();i++){string sn=GetSetName(i);names.writeString(formatInt(sn.length())+"\\n"+sn);}names.close();
while(GetNumTotalErrors()>0){ErrorObj e=PopLastError();Print(e.GetErrorString());Print("SECTION_STUDIO_ERROR");return 1;}
Print("SECTION_STUDIO_SAVED: EngineInfo.json");return 0;}
'''.replace('GID',json.dumps(gid)).replace('CHANGES','\n'.join(statements))
    lines=[]
    for i,name in enumerate(PARMS):
        key=json.dumps(name)
        lines.append(('f.writeString(",");' if i else '')+'{string p=FindParm(g,'+key+',"EngineModel");f.writeString("\\"'+name+'\\":{\\"value\\":"+formatFloat(GetParmVal(p),"",0,15)+",\\"min\\":"+formatFloat(GetParmLowerLimit(p),"",0,15)+",\\"max\\":"+formatFloat(GetParmUpperLimit(p),"",0,15)+"}");}')
    script=script.replace('PARMS','\n'.join(lines))
    with tempfile.TemporaryDirectory(prefix='StudioEngine_') as tmp:
        folder=Path(tmp);(folder/'Source.vsp3').write_text(xml,encoding='utf-8')
        info=run_script(executable,folder,script,'EngineInfo.json')
        # Set names are arbitrary user strings; recover them from XML instead
        # if they would require escaping beyond the native writer above.
        text=info.read_text(encoding='utf-8')
        set_names=[]
        with (folder/'SetNames.bin').open('rb') as f:
            while line:=f.readline():
                size=int(line);set_names.append(f.read(size).decode('utf-8'))
        try:out=json.loads(text)
        except json.JSONDecodeError as e:raise ValueError('OpenVSP вернул некорректное описание Engine Model.') from e
    out['sets']=set_names
    values={k:v['value'] for k,v in out['parameters'].items()}
    out.update(ok=True,geomId=gid,sourceHash=hashlib.sha256(xml.encode()).hexdigest(),active=active_parameters(values),values=values)
    return out
