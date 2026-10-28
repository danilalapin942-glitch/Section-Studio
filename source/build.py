from pathlib import Path
p=Path(__file__).resolve().parent
s=(p/'template.html').read_text(encoding='utf-8')
for name in ('core','vsp','pressure','machline','audit','repair','templates','wingfit','native','wingui','riskui','app'):
    s=s.replace('/*'+name.upper()+'*/',(p/(name+'.js')).read_text(encoding='utf-8'))
s=s.replace('/*TEMPLATE_DATA*/',(p/'sections.json').read_text(encoding='utf-8').replace('</','<\\/'))
(p.parent/'Section_Studio.html').write_text(s,encoding='utf-8')
print('Built Section_Studio.html')
