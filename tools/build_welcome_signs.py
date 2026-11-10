"""Rebuild researched welcome faces, profiles, catalog and review sheets.

python tools/build_welcome_signs.py
Offline/deterministic: Pillow, bundled fonts and checked-in emblem assets.
See tools/sign_art/welcome/sources.json for the selected design and references.
"""
from pathlib import Path
import json
import shutil
import sys
import uuid
from html import escape
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.welcome_art import DRAWINGS, FONTS

OUT=ROOT/'mod/beamng_earth/levels/beamng_earth/art/shapes/beamngEarth/welcome_signs'
VFS='/levels/beamng_earth/art/shapes/beamngEarth/welcome_signs'
SOURCES=ROOT/'tools/sign_art/welcome/sources.json'
PREVIEW=ROOT/'build/welcome-signs'


def triangulate(points):
    """Build-time ear clipping of a simple CCW polygon (no runtime dependency)."""
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    order=list(range(len(points)));tri=[]
    if sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in order)<0:order.reverse()
    while len(order)>3:
        for i,mid in enumerate(order):
            a,b,c=order[i-1],mid,order[(i+1)%len(order)]
            if cross(points[a],points[b],points[c])<=1e-10:continue
            if any(all(cross(points[u],points[v],points[p])>=-1e-10 for u,v in ((a,b),(b,c),(c,a))) for p in order if p not in (a,b,c)):continue
            tri.append([a,b,c]);order.pop(i);break
        else:raise ValueError('Invalid welcome plate contour')
    tri.append(order)
    return tri


def profile(points,height):
    # x right, y upwards; these are also the mesh's Collada UVs (V up).
    # cdae.write performs the single conversion to BeamNG's V-down convention.
    clean=[]
    for x,y in points:
        p=[round(x/1200,7),round(1-y/height,7)]
        if not clean or p!=clean[-1]:clean.append(p)
    if clean[0]==clean[-1]:clean.pop()
    if sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(clean,clean[1:]+clean[:1]))<0:clean.reverse()
    return {'points':clean,'triangles':triangulate(clean)}


def main():
    OUT.mkdir(parents=True,exist_ok=True);PREVIEW.mkdir(parents=True,exist_ok=True)
    sources=json.loads(SOURCES.read_text())['states']
    assert set(sources)==set(DRAWINGS) and len(sources)==49
    materials={};states={};previews=[]
    for code,source in sources.items():
        board=DRAWINGS[code]();art=board.im
        profiles=None
        if hasattr(board,'contour'):
            profiles=[profile(board.contour,board.h)]
            mask=Image.new('L',art.size);ImageDraw.Draw(mask).polygon(board.contour,fill=255);art.putalpha(mask)
        elif hasattr(board,'panels'):
            profiles=[profile(p,board.h) for p in board.panels]
        art.resize((1024,1024),Image.Resampling.LANCZOS).save(OUT/(code.lower()+'.png'),optimize=True)
        art.save(PREVIEW/(code.lower()+'.png'),optimize=True)
        mat='bne_welcome_'+code.lower()
        materials[mat]={'name':mat,'mapTo':mat,'class':'Material','version':1.5,
            'Stages':[{'baseColorMap':VFS+'/'+code.lower()+'.png','baseColorFactor':[1,1,1,1],
                       'roughnessFactor':.48,'metallicFactor':0.,'retroreflectivity':.8}],
            'persistentId':str(uuid.uuid5(uuid.NAMESPACE_URL,'beamng.earth/welcome/'+code)),
            'doubleSided':False,'translucent':False}
        if profiles:materials[mat].update(alphaTest=True,alphaRef=128)
        width=min(5.5,4.2*1200/board.h) if board.h>1000 else 5.0
        width,height=source.get('size_m',(width,width*board.h/1200))
        states[code]={**source,'width':width,'height':height,'design':source['edition'],
                      'reference':source['references'][0],'artwork':source['fidelity']}
        if profiles:states[code]['panels']=profiles
        tile=Image.new('RGB',(420,340),'#e9edef')
        thumb=ImageOps.contain(art,(400,285),Image.Resampling.LANCZOS)
        tile.paste(thumb,((420-thumb.width)//2,8+(285-thumb.height)//2),thumb)
        d=ImageDraw.Draw(tile);f=ImageFont.truetype(str(FONTS/'DejaVuSans-Bold.ttf'),20)
        d.text((12,302),code+'  '+source['name'],font=f,fill='#203441')
        previews.append(tile)
    (OUT/'main.materials.json').write_text(json.dumps(materials,indent=2)+'\n')
    (ROOT/'server/data/welcome_signs.json').write_text(json.dumps({'version':2,'states':states},indent=2)+'\n')
    shutil.copyfile(SOURCES,OUT/'sources.json')
    for name in ('Roadgeek-LICENSE.txt','DejaVu-LICENSE.txt','Yellowtail-LICENSE.txt','Lora-LICENSE.txt'):
        shutil.copyfile(FONTS/name,OUT/name)
    sheet=Image.new('RGB',(420*7,340*7),'white')
    for i,tile in enumerate(previews):sheet.paste(tile,((i%7)*420,(i//7)*340))
    sheet.save(ROOT/'build/welcome-signs-preview.jpg',quality=95)
    for group in range(6):
        part=Image.new('RGB',(1260,1020),'#e9edef')
        for i,tile in enumerate(previews[group*9:(group+1)*9]):part.paste(tile,((i%3)*420,(i//3)*340))
        part.save(PREVIEW/f'review-{group+1}.jpg',quality=96)
    cards=[]
    for code,s in sources.items():
        links=' · '.join(f'<a href="{escape(u,quote=True)}">Reference {i+1}</a>' for i,u in enumerate(s['references']))
        cards.append(f'<article><figure><img src="{code.lower()}.png" alt="{escape(s["name"])} welcome sign"></figure><h2>{code} · {escape(s["name"])}</h2><p>{escape(s["edition"])}</p><p>{escape(s["description"])}</p><small>{links}</small></article>')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>State welcome signs — researched designs</title><style>body{margin:0;background:#edf0f1;color:#183241;font:16px system-ui}header{padding:32px;max-width:1100px;margin:auto}h1{margin:0 0 12px}header p{max-width:850px;line-height:1.5}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px;padding:0 32px 32px;max-width:1600px;margin:auto}article{background:white;border-radius:12px;padding:20px}figure{height:270px;margin:0;display:flex;align-items:center;justify-content:center;background:#dfe6e8;border-radius:6px}img{max-width:96%;max-height:96%;object-fit:contain}h2{font-size:20px}p{line-height:1.5}small a{color:#17648b}</style><header><h1>49 state welcome signs</h1><p>Reference-based game artwork, reviewed 9 November 2026. Each face follows a documented design. Some represent established or historic editions; custom lettering and illustrated scenery remain approximations. Governor plaques are omitted. Locations are inferred from road/state crossings, not surveyed sign positions.</p></header><main>'''+''.join(cards)+'</main></html>'
    (PREVIEW/'index.html').write_text(html,encoding='utf8')
    lines=['# State welcome sign reference catalog', '',
           'Reviewed 9 November 2026. One documented edition per state; designs vary by crossing and date.',
           'These are game recreations. Custom lettering and illustrated scenery remain approximations.',
           'Governor-name plaques are omitted. See [feature notes](STATE_WELCOME_SIGNS.md) for placement and dimensions.', '',
           '| State | Selected design | Visual details and references |', '| --- | --- | --- |']
    for code,s in sources.items():
        links='; '.join(f'[Reference {i+1}]({u})' for i,u in enumerate(s['references']))
        lines.append(f'| {code} — {s["name"]} | {s["edition"]} | {s["description"]} {links} |')
    lines += ['', 'Official drawings checked: MDOT I2-5, page 13 of the MDOT-supplied-sign PDF; TxDOT I-2T, Figure 7-16; PennDOT Summer 2024 DOTcom, cover page.',
              '', 'The Maryland flag, New York coat of arms and West Virginia seal use the public-domain components credited in the packaged welcome-sign NOTICE.md. Reference photographs are not redistributed.', '']
    (ROOT/'docs/STATE_WELCOME_SIGN_REFERENCES.md').write_text('\n'.join(lines),encoding='utf8')
    print(f'Built {len(states)} researched faces, {sum("panels" in s for s in states.values())} shaped boards; gallery: {PREVIEW / "index.html"}')


if __name__=='__main__':main()
