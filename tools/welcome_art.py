"""Editable, state-specific drawings. Coordinates follow the cited roadside faces.

All curves and scenes are vector drawing commands, rasterized with Pillow. This
keeps the build offline, deterministic and independent of system-installed fonts.
Reference photographs are never used as texture pixels.
"""
from functools import lru_cache
from pathlib import Path
import json
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / 'tools/fonts'
WHITE = '#fffdf1'
BLUE = '#064a89'
GOLD = '#efbd37'

@lru_cache(maxsize=32)
def font(style, size=220):
    names = {'sans':'town/DejaVuSans.ttf', 'bold':'DejaVuSans-Bold.ttf',
             'road':'RG2014EEM.ttf', 'serif':'Lora.ttf', 'serif_bold':'Lora.ttf',
             'italic':'Lora-Italic.ttf', 'script':'Yellowtail-Regular.ttf'}
    f = ImageFont.truetype(str(FONTS / names[style]), size)
    if style in ('serif','serif_bold','italic'):
        f.set_variation_by_axes([700 if style=='serif_bold' else 400])
    return f


class Board:
    def __init__(self, height, background, border=None, radius=25):
        self.h = height
        self.im = Image.new('RGBA',(1200,height),background)
        self.d = ImageDraw.Draw(self.im)
        if border:
            self.d.rounded_rectangle((15,15,1184,height-16),radius=radius,outline=border,width=9)

    def text(self, words, box, colour=WHITE, style='road', stretch=False, outline=None):
        f=font(style)
        b=f.getbbox(words,stroke_width=3 if outline else 0)
        lay=Image.new('RGBA',(b[2]-b[0]+8,b[3]-b[1]+8))
        ImageDraw.Draw(lay).text((4-b[0],4-b[1]),words,font=f,fill=colour,
                                stroke_width=3 if outline else 0,stroke_fill=outline)
        lay=lay.crop(lay.getbbox())
        x,y,w,h=box
        lay=lay.resize((int(w),int(h)),Image.Resampling.LANCZOS) if stretch else ImageOps.contain(lay,(int(w),int(h)),Image.Resampling.LANCZOS)
        self.im.alpha_composite(lay,(round(x+(w-lay.width)/2),round(y+(h-lay.height)/2)))

    def path(self, points, fill=None, stroke=None, width=4):
        """Start point followed by lines (x,y) or cubic segments (x1,y1,x2,y2,x3,y3)."""
        out=[points[0]]
        for q in points[1:]:
            if len(q)==2: out.append(q);continue
            x,y=out[-1];a,b,c,d,e,f=q
            for i in range(1,33):
                t=i/32;u=1-t
                out.append((u*u*u*x+3*u*u*t*a+3*u*t*t*c+t*t*t*e,
                            u*u*u*y+3*u*u*t*b+3*u*t*t*d+t*t*t*f))
        if fill:self.d.polygon(out,fill=fill)
        if stroke:self.d.line(out,fill=stroke,width=width,joint='curve')
        return out

    def state(self, code, box, fill, stroke=None, width=4):
        rings=state_rings(code,box)
        for r in rings:
            self.d.polygon(r,fill=fill)
            if stroke:self.d.line(r+[r[0]],fill=stroke,width=width,joint='curve')
        return rings

    def star(self,x,y,r,colour,n=5,angle=-math.pi/2):
        self.d.polygon([(x+math.cos(angle+i*math.pi/n)*r*(1 if i%2==0 else .39),
                         y+math.sin(angle+i*math.pi/n)*r*(1 if i%2==0 else .39)) for i in range(2*n)],fill=colour)

    def pine(self,x,y,h,col):
        self.d.rectangle((x-h*.035,y-h*.13,x+h*.035,y),fill=col)
        for z in range(5):
            yy=y-h+z*h*.145;w=h*(.08+z*.048)
            self.d.polygon([(x,yy),(x-w,yy+h*.31),(x+w,yy+h*.31)],fill=col)

    def ellipse(self,box,fill,outline=None,width=1):self.d.ellipse(box,fill=fill,outline=outline,width=width)

    def wood(self, colour, start=0, end=None):
        rng=random.Random(1)
        for y in range(start,end or self.h,4):
            self.path([(0,y),(300,y+rng.randrange(-3,4),800,y+rng.randrange(-3,4),1200,y)],stroke=colour,width=1)

    def emblem(self,key,box):
        im=Image.open(ROOT/'tools/sign_art/welcome/components'/f'{key}.png').convert('RGBA')
        x,y,w,h=box;im=ImageOps.contain(im,(int(w),int(h)),Image.Resampling.LANCZOS)
        self.im.alpha_composite(im,(round(x+(w-im.width)/2),round(y+(h-im.height)/2)))

    def circle_text(self,words,cx,cy,radius,span,below=False):
        f=font('serif_bold',38)
        for i,ch in enumerate(words):
            if ch==' ':continue
            a=(math.pi/2 if below else -math.pi/2)+(i/(len(words)-1)-.5)*span*(-1 if below else 1)
            box=f.getbbox(ch);glyph=Image.new('RGBA',(box[2]-box[0]+8,box[3]-box[1]+8))
            ImageDraw.Draw(glyph).text((4-box[0],4-box[1]),ch,font=f,fill=WHITE)
            glyph=glyph.rotate(-math.degrees(a)+(90 if below else -90),Image.Resampling.BICUBIC,expand=True)
            self.im.alpha_composite(glyph,(round(cx+math.cos(a)*radius-glyph.width/2),round(cy+math.sin(a)*radius-glyph.height/2)))

    def arched_text(self,words,box,colour,rise):
        x,y,w,h=box
        f=font('road');ink=f.getbbox(words)
        run=Image.new('RGBA',(ink[2]-ink[0]+8,ink[3]-ink[1]+8))
        ImageDraw.Draw(run).text((4-ink[0],4-ink[1]),words,font=f,fill=colour)
        run=run.crop(run.getbbox()).resize((int(w),int(h)),Image.Resampling.LANCZOS)
        # Warp the complete typeset run so side bearings and narrow letters
        # keep their proportions (stretching isolated I glyphs makes blocks).
        for col in range(run.width):
            shift=round(rise*(col/(run.width-1)*2-1)**2)
            self.im.alpha_composite(run.crop((col,0,col+1,run.height)),(int(x)+col,int(y)+shift))


@lru_cache(maxsize=1)
def states():return json.loads((ROOT/'server/sign_states.geojson').read_text())['features']

def state_rings(code,box):
    f=next(f for f in states() if f['properties']['STUSAB']==code)
    rings=[p[0] for p in f['geometry']['coordinates']]
    rings=[r for r in rings if len(r)>3 and (code!='AK' or (min(p[0] for p in r)>-170 and max(p[0] for p in r)<0))]
    allp=[p for r in rings for p in r]
    xmin,ymin=min(p[0] for p in allp),min(p[1] for p in allp)
    xmax,ymax=max(p[0] for p in allp),max(p[1] for p in allp)
    x,y,w,h=box;s=min(w/((xmax-xmin)*.76),h/(ymax-ymin))
    return [[(x+w/2+(p[0]-(xmin+xmax)/2)*.76*s,y+h/2-(p[1]-(ymin+ymax)/2)*s) for p in r] for r in rings]


def flower(b,x,y,r,petal,centre,petals=8):
    for i in range(petals):
        t=i*math.tau/petals
        xx=x+math.cos(t)*r*.62;yy=y+math.sin(t)*r*.62
        b.ellipse((xx-r*.43,yy-r*.43,xx+r*.43,yy+r*.43),petal)
    b.ellipse((x-r*.26,y-r*.26,x+r*.26,y+r*.26),centre)


def bird(b,x,y,s,cardinal=False):
    """Branch-perched bird with wing feathers, cheek, bill and tapered tail."""
    def tr(q):return tuple(v*s+(x if i%2==0 else y) for i,v in enumerate(q))
    def p(q,fill,stroke=None):b.path([tr(z) for z in q],fill,stroke,2)
    col='#bc2732' if cardinal else '#aaa59b'
    p([(-.3,.3),(-1.1,1),(-.88,1.09),(.2,.47)],'#8f2832' if cardinal else '#555758')
    p([(-.65,.18),(-.9,-.65,.13,-.64,.5,-.21),(.88,.0,.42,.7,-.2,.5),(-.65,.18)],col)
    p([(-.52,.01),(-.27,-.2,.24,-.03,.22,.32),(-.18,.48,-.5,.24,-.52,.01)],'#922b31' if cardinal else '#595b5c')
    for i in range(4):p([(-.47+i*.12,.08),(-.2+i*.11,.31)],None,'#d26454' if cardinal else '#dedacb')
    p([(.2,-.33),(.24,-.79),(.62,-.42),(.65,-.04),(.2,-.33)],col if cardinal else '#242a2c')
    p([(.48,-.33),(.67,-.28),(.72,-.02),(.43,.02)],'#272626' if cardinal else '#f3f0dc')
    p([(.62,-.29),(.93,-.22),(.65,-.09)],'#ed9944' if cardinal else '#202527')
    b.ellipse((x+s*.5,y-s*.36,x+s*.56,y-s*.30),'#13191c')
    for dx in (-.1,.15):b.path([tr((dx,.45)),tr((dx-.05,.73)),tr((dx+.12,.73))],stroke='#614334',width=4)


def al():
    b=Board(800,'#006b52',WHITE)
    b.text('Welcome to',(160,100,880,100),style='sans')
    b.text('Sweet Home',(70,290,1060,165),style='serif_bold')
    b.text('Alabama',(110,560,980,170),style='serif_bold')
    return b

def ak():
    b=Board(650,'#a46a26');b.wood('#bc8133')
    b.path([(35,535),(35,160),(65,45,1135,45,1165,160),(1165,535)],'#242b2a')
    for y in range(130,530,25):b.d.line((40,y,1160,y),fill='#3d423a',width=3)
    b.text('Welcome to',(110,120,650,85),'#efdc99','serif')
    b.text('Alaska',(75,220,690,230),'#e5d08b','script')
    b.state('AK',(750,90,380,390),'#d3a043')
    b.text('and the Gateway to the Klondike',(80,562,1040,55),'#282727','serif')
    return b

def az():
    b=Board(1450,'#075c95',WHITE)
    b.text('ARIZONA',(65,85,1070,160),style='bold',stretch=True)
    # Classic flag/sunburst board: the lower blue field forms the star's base.
    cx,cy=600,850
    for i in range(13):
        a=math.pi+i*math.pi/13;z=math.pi+(i+1)*math.pi/13
        b.d.polygon([(cx,cy),(cx+1700*math.cos(a),cy+650*math.sin(a)),(cx+1700*math.cos(z),cy+650*math.sin(z))],fill='#b6372f' if i%2==0 else '#efbe38')
    b.d.rectangle((0,0,1200,315),fill='#075c95')
    b.text('ARIZONA',(65,85,1070,160),style='bold',stretch=True)
    b.star(600,850,260,WHITE)
    b.text('THE GRAND CANYON STATE',(80,1185,1040,67),style='road')
    b.text('WELCOMES YOU',(180,1300,840,67),style='road')
    b.d.rounded_rectangle((15,15,1184,1434),radius=25,outline=WHITE,width=9)
    return b

def ar():
    b=Board(740,'#184879')
    b.text('WELCOME TO',(120,43,960,80),style='serif')
    b.d.rectangle((0,165,1200,585),fill=WHITE)
    b.text('Arkansas',(60,220,1080,190),'#121a1b','serif_bold',True)
    b.path([(570,244),(590,191,653,179,671,170),(654,218,605,245,570,244)],'#3b774a')
    b.text('THE NATURAL STATE',(180,472,840,65),'#386844','sans')
    b.text('BUCKLE UP FOR SAFETY',(75,640,1050,57),style='serif_bold')
    return b

def ca():
    b=Board(700,'#07478b',WHITE)
    b.text('Welcome to',(80,90,760,120),'#efbd3c','script')
    b.text('California',(45,285,840,235),'#efbd3c','script',True)
    for x,y,s in ((950,180,95),(1070,300,95),(920,420,100)):
        b.path([(x,y+40),(x-50,y+140,1000,540,1010,640)],stroke='#568747',width=9)
        b.path([(x,y+100),(x-45,y+70,x-80,y+110,x-45,y+155),(x,y+100)],'#66883e')
        b.path([(x-s,y),(x-s*.9,y-100,x-s*.25,y-60,x,y-45),(x+s*.3,y-90,x+s,y-85,x+s,y),(x+s*.7,y+85,x-s*.6,y+85,x-s,y)],'#f2b72d')
        b.path([(x-s*.6,y-25),(x-s*.5,y+65,x+s*.4,y+90,x+s*.65,y-35)],stroke='#d88e21',width=6)
    return b

def co():
    b=Board(680,'#795134');b.wood('#68452d')
    for y in range(115,680,112):b.d.line((0,y,1200,y),fill='#503b2c',width=5)
    b.text('WELCOME TO',(160,75,880,100),'#f1e4ba','road',True)
    b.text('COLORFUL',(200,280,800,110),'#f1e4ba','road',True)
    b.text('COLORADO',(65,465,1070,125),'#f1e4ba','road',True)
    return b

def ct():
    # The long-established general welcome face avoids assigning a 2024
    # pizza/basketball/submarine slogan to the wrong entry corridor.
    b=Board(890,'#174a92',WHITE)
    b.text('Connecticut',(50,110,1100,150),style='road',stretch=True)
    b.text('Welcomes',(90,350,1020,150),style='road',stretch=True)
    b.text('You',(320,610,560,150),style='road',stretch=True)
    return b

def de():
    b=Board(640,WHITE,'#163956')
    b.text('Welcome to',(690,65,430,58),'#26648f','sans')
    b.text('Delaware',(75,160,1050,185),'#163956','serif',True)
    b.path([(45,385),(310,310,470,395,705,365),(870,345,1050,345,1160,355),(900,360,790,425,540,405),(300,365,150,365,45,385)],'#287ca3')
    b.path([(45,407),(330,365,510,455,760,405),(930,375,1040,392,1160,375),(925,420,780,468,535,438),(300,397,180,392,45,407)],'#5d9ca1')
    b.text('Endless Discoveries',(130,488,940,92),'#1b3b55','script')
    return b

def fl():
    b=Board(720,'#167cb6',WHITE)
    # Palms are part of the large lower-background silhouette.
    for x,y,h in ((170,695,270),(310,720,230),(1020,700,280),(900,720,200)):
        b.path([(x,y),(x-20,y-h*.6,x+15,y-h*.9,x,y-h)],stroke='#228f5c',width=22)
        for dx,dy in ((-150,55),(-130,-30),(-65,-75),(50,-85),(140,-25),(150,55)):
            b.path([(x,y-h),(x+dx*.35,y-h-50,x+dx,y-h+dy-35,x+dx,y-h+dy)],stroke='#228f5c',width=19)
    b.text('Welcome to',(160,60,880,105),style='script')
    b.text('FL',(100,215,280,200),style='bold',stretch=True)
    b.ellipse((402,236,590,423),'#f59c26')
    b.path([(490,244),(490,195,545,186,566,193),(544,222,519,239,490,244)],'#216b38')
    b.text('RIDA',(600,215,500,200),style='bold',stretch=True)
    b.text('The Sunshine State',(110,545,980,105),style='script')
    return b

def ga():
    b=Board(720,'#104d87',WHITE)
    for s,y,w in [('Welcome',70,690),("We're glad",235,730),("Georgia's",400,790),('on your mind.',565,1030)]:
        b.text(s,(60,y,w,100),style='serif',stretch=True)
    b.path([(920,80),(1060,30,1180,200,1080,335),(1015,400,882,360,832,260),(785,165,830,95,920,80)],'#eea74e')
    b.path([(925,87),(930,160,974,204,942,331)],stroke='#bd693c',width=8)
    b.path([(934,87),(975,20,1073,28,1105,40),(1080,111,991,119,934,87)],'#2c713c')
    return b

def id():
    b=Board(625,'#084e87',WHITE)
    b.text('Welcome to',(150,75,900,115),style='sans')
    b.text('IDAHO',(55,265,1090,270),style='serif_bold',stretch=True)
    return b

def il():
    b=Board(740,'#0b704c',WHITE)
    b.d.rectangle((0,180,1200,510),fill=WHITE)
    b.text('WELCOME TO',(200,70,800,65),style='road')
    b.text('ILLINOIS',(60,245,1080,200),'#176b4d','serif',True)
    # Lincoln's profile, the recognizable mark in the middle of the word.
    b.path([(630,238),(626,203,644,181,665,188),(689,187,699,207,693,225),(703,236),(695,242),(697,255),(684,262),(674,282),(655,279),(645,298),(623,295),(637,267)],'#176b4d')
    b.text('THE LAND OF LINCOLN',(100,558,1000,65),style='road')
    b.text('From the People of Illinois',(100,659,1000,43),style='sans')
    return b

def indiana():
    b=Board(1245,'#172927')
    b.d.rectangle((0,910,1200,1245),fill='#172d57')
    b.d.rounded_rectangle((38,38,1162,870),radius=30,outline='#e8e7d8',width=10)
    b.text('More to Discover',(250,255,700,100),'#d6ad52','script')
    b.d.rectangle((115,405,280,580),fill='#a94d35')
    b.text('IN',(133,430,128,130),style='bold',stretch=True)
    b.text('INDIANA',(315,413,800,164),style='bold',stretch=True)
    b.text('EST. 1816',(420,690,360,45),style='sans')
    b.text('Benjamin Harrison',(200,950,800,85),'#d6ad52','script')
    b.text("AMERICA'S HOOSIER PRESIDENT",(95,1060,1010,55),style='road',stretch=True)
    b.text("Lincoln's",(105,1148,330,72),'#d6ad52','script')
    b.text('BOYHOOD HOME',(455,1150,650,65),style='road',stretch=True)
    return b

def ia():
    b=Board(770,WHITE,'#24713c')
    b.text('THE PEOPLE OF',(330,65,760,57),'#252b27','serif')
    b.text('IOWA',(365,155,720,190),'#252b27','serif',True)
    b.text('WELCOME YOU',(340,395,750,53),'#252b27','serif')
    for i in range(13):
        a=math.pi+i*math.pi/12;x=480+math.cos(a)*270;y=630+math.sin(a)*135
        b.d.line((480+math.cos(a)*160,630+math.sin(a)*80,x,y),fill='#d4a732',width=8)
    b.path([(45,570),(300,480,465,670,710,565),(935,480,1050,520,1155,560),(1145,600,840,590,680,635),(400,700,220,550,45,610)],'#348449')
    b.text('Iowa',(730,470,350,135),'#dda92d','script')
    b.text('Fields of Opportunities',(120,676,960,56),'#1a2821','serif')
    return b

def ks():
    b=Board(720,'#1d6099',WHITE)
    b.text('Welcome To',(220,80,760,110),style='sans')
    b.path([(70,370),(430,450,775,400,1070,245),(850,440,510,510,100,450),(70,370)],'#e7b433')
    b.star(1090,250,90,'#e7b433')
    b.text('KANSAS',(100,535,1000,115),style='sans',stretch=True)
    return b

def ky():
    b=Board(670,'#08509a',WHITE)
    # The sign's emblem is a stylized, expanded silhouette, not a geographic map.
    b.path([(65,535),(140,480),(150,450),(215,455),(235,415),(290,420),(320,380),(390,370),(420,330),(485,350),(510,310),(545,325),(575,280),(615,275),(620,225),(655,250),(700,230),(750,260),(800,250),(850,285),(900,270),(950,290),(995,280),(1030,310),(1060,335),(1125,350),(1140,405),(1090,475),(1025,535)],WHITE)
    b.text('Welcome',(80,45,435,75),style='sans')
    b.text('To',(310,130,160,60),style='sans')
    b.text('Kentucky',(320,365,690,112),'#134e8a','italic',True)
    b.text('UNBRIDLED SPIRIT',(360,485,610,30),'#134e8a','sans')
    # Horse-head flourish above Kentucky's tourism lettering.
    b.path([(805,355),(857,310,880,308,912,321),(920,295),(931,323),(958,346),(944,358),(921,341),(908,347),(892,366)],stroke='#134e8a',width=9)
    return b

def la():
    b=Board(735,'#124b92',WHITE)
    b.text('Welcome to Louisiana',(75,55,1050,115),style='serif')
    # Three petalled fleur-de-lis with curled side petals.
    b.path([(600,190),(520,280,548,351,590,430),(540,367,489,275,420,331),(357,395,434,473,489,421),(447,425,426,370,463,366),(515,360,554,439,566,463),(526,466),(526,496),(580,496),(555,560),(600,534),(645,560),(620,496),(674,496),(674,463),(634,463),(646,439,685,360,737,366),(774,370,753,425,711,421),(766,473,843,395,780,331),(711,275,660,367,610,430),(652,351,680,280,600,190)],'#e6bd59')
    b.text('Bienvenue en Louisiane',(70,620,1060,65),style='serif')
    return b

def me():
    b=Board(720,'#14528e',WHITE)
    b.text('WELCOME TO',(130,75,940,85),style='road')
    b.text('MAINE',(80,250,1040,205),style='road',stretch=True)
    b.text('The Way Life Should Be',(70,570,1060,72),style='sans')
    return b

def md():
    b=Board(1400,'#edebe0')
    pts=[(10,1390),(10,470),(175,470),(175,425)]
    pts += [(600+425*math.cos(a),425+410*math.sin(a)) for a in [math.pi+i*math.pi/48 for i in range(49)]]
    pts += [(1025,470),(1190,470),(1190,1390)]
    b.d.line(pts+[pts[0]],fill='#dea63b',width=22,joint='curve')
    inner=[(x*.95+30,y*.95+35) for x,y in pts]
    b.d.line(inner+[inner[0]],fill='#242b2c',width=20,joint='curve')
    b.emblem('md',(385,130,430,285))
    b.text('FOUNDED 1634',(400,425,400,38),'#292a27','serif')
    b.d.rectangle((100,550,1100,760),fill='#e3ae45',outline='#242b2c',width=7)
    b.text('MARYLAND',(135,585,930,123),'#252828','serif',True)
    b.text('WELCOMES YOU',(90,795,1020,75),'#252828','serif',True)
    b.d.line((95,900,1105,900),fill='#252828',width=6)
    b.path([(180,1120),(440,1040,725,1150,1010,1010)],stroke='#31513a',width=12)
    for x,y,r in ((370,1050,48),(480,1020,55),(600,1040,50),(730,1000,60)):
        b.path([(x,y),(x+10,y+60,x+50,1090,x+30,1130)],stroke='#38603f',width=6)
        flower(b,x,y,r,'#dfbc47','#3b3626',10)
    for x,y in ((270,1100),(550,1110),(850,1080),(945,1055)):
        b.path([(x,y),(x+20,y-80,x+110,y-100,x+95,y-85),(x+75,y-40,x+50,y-10,x,y)],'#34583a')
    b.d.line((95,1190,1105,1190),fill='#252828',width=6)
    b.text("WE'RE OPEN FOR BUSINESS",(95,1245,1010,60),'#252828','serif',True)
    b.contour=pts
    return b

def ma():
    b=Board(665,'#12599c',WHITE)
    b.text('Massachusetts',(70,75,1060,105),style='sans',stretch=True)
    b.text('Welcomes You',(70,235,1060,165),style='script',stretch=True)
    b.path([(510,620),(780,550,930,630,1150,500)],stroke='#636844',width=10)
    for x,y in ((700,560),(800,570),(1010,580),(1090,535)):
        b.path([(x,y),(x-25,y-30,x-30,y-65,x-5,y-70),(x+20,y-55,x+20,y-30,x,y)],'#539763')
        flower(b,x,y,36,'#efb6ce','#ddbd65',5)
    bird(b,940,510,105)
    b.text('massDOT',(65,570,230,40),style='sans')
    return b

def mi():
    b=Board(410,'#07519a')
    b.text('Welcome to',(74,48,560,63),style='road')
    b.text('PURE',(65,215,310,90),style='road',stretch=True)
    # MDOT I2-5, 2020: the M is light blue, not white. The mark has
    # a long descending entry stroke and sits between PURE and ICHIGAN.
    b.path([(350,375),(421,238,505,100,551,123),(568,132,529,258,526,280),(590,179,605,154,630,149),(615,265,610,297,660,315),(636,326),(579,311,590,223,602,180),(556,251,538,316,510,319),(490,320,541,172,535,145),(482,181,416,301,365,374),(350,375)],'#84bce2')
    b.text('ICHIGAN',(662,215,490,90),style='road',stretch=True)
    return b

def mn():
    b=Board(790,'#ffdf30')
    b.state('MN',(65,35,730,710),'#bd9974','#192d40',7)
    mask=Image.new('L',b.im.size);d=ImageDraw.Draw(mask)
    for r in state_rings('MN',(65,35,730,710)):d.polygon(r,fill=255)
    layer=Board(790,(0,0,0,0))
    layer.path([(315,0),(310,130,350,200,390,295),(420,380,455,390,480,480),(485,580,560,625,610,790),(1200,790),(1200,0)],'#d8c0a0')
    layer.path([(355,0),(345,150,400,220,435,310),(455,380,500,410,515,475),(540,590,610,665,650,790),(1200,790),(1200,0)],'#759bc8')
    layer.im.putalpha(ImageChops.multiply(layer.im.getchannel('A'),mask));b.im.alpha_composite(layer.im)
    b.text('WELCOME',(700,55,430,80),'#0b4383','sans')
    b.text('TO',(830,165,180,70),'#0b4383','sans')
    b.path([(0,500),(170,530,270,570,410,540),(620,480,850,400,1200,420),(1200,790),(0,790)],'#073a7a')
    for x,y,h in ((65,535,170),(135,555,100),(630,510,190),(750,470,185),(850,450,145),(960,435,190),(1100,450,250)):
        b.pine(x,y,h,'#073a7a')
    b.text('Minnesota',(25,430,1140,290),'#ffdf30','script',True,outline='#173b72')
    return b

def ms():
    b=Board(760,'#134e8c',WHITE)
    b.state('MS',(350,175,510,400),'#b83639')
    b.text('WELCOME TO',(175,65,850,95),style='sans')
    b.text('MISSISSIPPI',(75,300,1050,175),style='serif',stretch=True)
    b.text("Birthplace of America's Music",(70,580,1060,90),style='script')
    for x,y in ((155,240),(1045,505)):
        b.ellipse((x-37,y+35,x+15,y+70),'#c3444a')
        b.d.line((x+11,y+56,x+11,y-65),fill='#c3444a',width=10)
        b.path([(x+11,y-65),(x+74,y-45,x+75,y-15,x+35,y-10)],stroke='#c3444a',width=13)
    return b

def mo():
    b=Board(650,'#1976b2',WHITE)
    # River S and spiral sun are the distinguishing tourism wordmark.
    b.text('MI',(80,155,235,220),style='serif',stretch=True)
    b.text('SOURI',(460,155,650,220),style='serif',stretch=True)
    b.path([(465,190),(355,150,314,225,391,270),(467,316,454,368,345,380),(435,320,359,307,337,268),(280,179,382,137,465,190)],WHITE)
    pts=[]
    for i in range(200):
        t=i/199*math.pi*4;r=8+i*.30;pts.append((420+math.cos(t)*r,88+math.sin(t)*r))
    b.d.line(pts,fill='#f7c345',width=13)
    for i in range(12):
        a=i*math.tau/12;b.d.line((420+math.cos(a)*83,88+math.sin(a)*83,420+math.cos(a)*100,88+math.sin(a)*100),fill='#f7c345',width=7)
    b.text('Welcomes You',(390,470,700,87),'#f7c345','sans')
    return b

def mt():
    b=Board(650,'#639ac5',WHITE)
    outline=[(55,30),(1135,40),(1160,550),(500,560),(498,602),(465,584),(452,602),(355,625),(270,470),(222,490),(235,348),(197,355),(65,265)]
    b.path(outline,'#061f46',WHITE,4)
    b.ellipse((400,65,840,565),'#5b8db7',WHITE,8)
    b.path([(420,260),(470,210),(530,235),(605,130),(680,235),(720,195),(815,285),(820,330),(420,330)],'#063564')
    b.path([(480,225),(530,235),(605,130),(584,210),(555,203),(535,250)],WHITE)
    b.path([(605,130),(680,235),(643,214),(628,180)],'#022244')
    b.path([(720,195),(752,230),(732,220),(727,212),(708,224)],WHITE)
    b.path([(420,330),(825,330),(807,426),(765,506),(697,550),(600,560),(498,525),(445,451)],'#ffb529')
    b.path([(439,422),(550,460),(601,426),(650,449),(690,385),(745,412),(781,478),(707,540),(586,549),(490,505)],'#ef8c1b')
    b.path([(580,545),(625,485),(620,440),(600,431),(620,420),(655,421),(675,413),(700,425),(684,438),(690,480),(738,517),(684,549)],'#ed6a21')
    b.text('Welcome',(90,90,360,78),style='italic')
    b.text('to',(245,179,140,62),style='italic')
    b.text('MONTANA',(280,284,780,111),'#be1f36','bold',True,outline=WHITE)
    return b

def wagon(b,x,y,s,col,canvas):
    b.path([(x,y),(x,y-s*.65,x+s*.85,y-s*.65,x+s*.9,y),(x,y)],canvas,col,5)
    for j in (.2,.45,.7):b.path([(x+s*j,y),(x+s*(j-.03),y-s*.4,x+s*(j+.08),y-s*.6,x+s*(j+.16),y-s*.4)],stroke=col,width=4)
    b.d.rectangle((x-10,y,x+s,y+s*.12),fill=col)
    for xx in (x+s*.16,x+s*.79):
        b.ellipse((xx-s*.14,y+s*.03,xx+s*.14,y+s*.31),canvas,col,6)
        for a in range(0,180,30):
            t=math.radians(a);b.d.line((xx-math.cos(t)*s*.14,y+s*.17-math.sin(t)*s*.14,xx+math.cos(t)*s*.14,y+s*.17+math.sin(t)*s*.14),fill=col,width=3)

def ne():
    b=Board(760,'#096949',WHITE)
    b.text('NEBRASKA',(65,65,1070,115),style='road',stretch=True)
    b.text('...the',(80,260,380,75),style='sans')
    b.text('good life',(55,395,590,105),style='sans')
    b.ellipse((760,230,1040,510),'#e5ba3c')
    wagon(b,730,455,350,WHITE,'#096949')
    b.text('Home of',(75,630,450,67),style='sans')
    b.text('Arbor Day',(655,630,475,67),style='sans')
    b.ellipse((545,605,650,710),None,WHITE,5)
    b.pine(598,692,75,WHITE)
    return b

def nv():
    b=Board(760,'#292e50')
    # Documented 1990s prospector board, still recognizable as a historic edition.
    for y in range(760):
        t=y/760;b.d.line((0,y,1200,y),fill=(int(53+192*t),int(47+145*t),int(87-25*t)))
    b.path([(0,700),(210,500),(335,575),(530,480),(640,580),(840,480),(1200,575),(1200,760),(0,760)],'#5d432e')
    b.text('WELCOME TO',(470,100,660,85),style='sans')
    b.text('NEVADA',(390,245,760,150),style='bold',stretch=True)
    c='#282925'
    # Prospector with broad hat, pick and a loaded mule.
    b.ellipse((200,170,270,242),c);b.ellipse((155,185,310,215),c)
    b.path([(205,230),(175,338),(215,420),(190,600),(220,625),(260,430),(270,605),(306,605),(292,400),(270,270)],c)
    b.path([(190,285),(135,370),(165,392),(235,310)],c)
    b.d.line((130,175,330,430),fill=c,width=14)
    b.path([(90,165),(180,125,260,180,268,205),(185,161,120,170,90,165)],c)
    b.ellipse((60,390,215,510),c)
    b.path([(60,425),(20,355),(10,350),(5,400),(30,450),(45,470)],c)
    for x in (80,175):b.d.line((x,480,x-10,605),fill=c,width=19)
    b.d.rectangle((86,360,190,415),fill=c)
    return b

def nh():
    b=Board(900,'#103a70','#e8c255')
    b.text('Welcome to',(155,55,890,145),'#e8c255','script')
    b.path([(210,245),(550,200,880,225,1020,175)],stroke='#e8c255',width=9)
    b.text('NEW',(280,325,640,145),'#e8c255','serif',True)
    b.text('HAMPSHIRE',(60,545,1080,125),'#e8c255','serif',True)
    b.d.line((80,735,1120,735),fill='#e8c255',width=5)
    b.text('THE GRANITE STATE',(100,790,1000,53),'#e8c255','serif')
    return b

def nj():
    b=Board(760,'#1d6951',WHITE)
    b.state('NJ',(300,200,600,510),'#e3e1ca',WHITE,6)
    b.text('WELCOME TO',(125,75,950,83),style='road')
    b.d.rectangle((45,320,1155,510),fill='#e3e1ca')
    b.text('NEW JERSEY',(70,345,1060,130),'#33715d','serif',True)
    return b

def nm():
    b=Board(900,'#e9c532','#bc2d24')
    b.text('Welcome to',(490,90,625,95),'#292c27','sans')
    b.text('NEW MEXICO',(75,480,1050,165),'#292c27','sans',True)
    b.text('The Land of Enchantment',(80,740,1040,75),'#b32f26','sans')
    for x,y,col,flip in ((190,140,'#b92a24',1),(340,180,'#358043',-1)):
        b.path([(x,y),(x+110,y-30,x+155,y+110,x+70,y+180),(x+25,y+230,x-60,y+250,x-95,y+230),(x+20,y+210,x+50,y+110,x,y)],col)
        b.path([(x+10,y+10),(x+35,y-40,x+80,y-45,x+70,y-85)],stroke='#456c35',width=19)
        b.path([(x+70,y+35),(x+100,y+85,x+65,y+140,x+35,y+160)],stroke='#e78046' if flip==1 else '#69aa4a',width=9)
    return b

def ny():
    b=Board(760,'#13704f',WHITE)
    b.text('Welcome',(160,70,620,90),style='road')
    b.text('To',(360,210,200,75),style='road')
    b.emblem('ny',(915,75,215,215))
    b.text('New York',(130,380,940,140),style='road',stretch=True)
    b.text('The Empire State',(90,600,1020,80),style='road')
    return b

def nc():
    b=Board(715,'#09704f',WHITE)
    b.d.rectangle((80,100,510,390),fill=WHITE)
    b.d.rectangle((225,100,510,245),fill='#c63438')
    b.d.rectangle((80,100,225,390),fill='#173c73')
    b.star(152,245,34,WHITE)
    b.text('N',(93,230,32,35),GOLD,'serif_bold')
    b.text('C',(184,230,32,35),GOLD,'serif_bold')
    for y,txt in ((150,'MAY 20th 1775'),(325,'APRIL 12th 1776')):
        b.d.rectangle((89,y,216,y+26),fill=GOLD)
        b.text(txt,(94,y+4,117,17),'#173c73','sans',True)
    b.text('Welcome',(560,95,555,115),style='sans')
    b.text('To',(745,280,190,100),style='sans')
    b.text('NORTH CAROLINA',(65,515,1070,120),style='road',stretch=True)
    return b

def nd():
    b=Board(620,'#153e91',WHITE)
    b.text('Welcome to',(160,65,880,85),style='road')
    b.text('North Dakota',(50,210,1100,225),style='script',stretch=True)
    b.text('L E G E N D A R Y',(175,505,850,50),style='serif')
    return b

def oh():
    b=Board(440,WHITE)
    b.state('OH',(80,25,405,390),WHITE,'#a92e43',12)
    b.text('Ohio',(20,110,515,220),'#174d86','script',True,outline=WHITE)
    b.text('W E L C O M E  T O',(540,95,610,55),'#9f3044','sans')
    b.text('THE HEART OF IT ALL',(540,205,610,80),'#174d86','bold')
    return b

def ok():
    b=Board(600,WHITE,'#464a47')
    b.text('Welcome to',(55,220,535,65),'#0876b7','sans')
    b.text('OKLAHOMA',(55,315,700,110),'#1e2325','bold',True)
    # Eight folded, coloured kite rays surrounding the white star (2020 mark).
    colours=[('#1c6cc4','#28b8e0'),('#27bce0','#006eb1'),('#63b900','#2d7200'),('#cf3000','#a42310'),('#ef8600','#993b09'),('#af5b00','#df9100'),('#2795eb','#126cd2'),('#033ce4','#1239bb')]
    cx,cy=1005,295
    for i,(light,dark) in enumerate(colours):
        a=(i-2)*math.pi/4
        def p(r,t):return (cx+math.cos(a+t)*r,cy+math.sin(a+t)*r)
        b.path([p(110,0),p(225,-.26),p(295,0),p(225,.26)],light)
        b.path([p(110,0),p(295,0),p(225,.26)],dark)
        b.path([p(260,.36),p(315,.38),p(287,.22)],light)
    return b

def ore():
    b=Board(740,WHITE)
    b.state('OR',(55,70,790,610),'#997729')
    b.text('WELCOME',(190,210,570,85),style='road')
    b.text('TO',(370,370,180,75),style='road')
    b.text('OREGON',(205,520,530,95),style='road')
    b.path([(890,480),(875,300),(940,235),(1020,265),(1080,335),(1080,480),(890,480)],'#e2eee3','#268158',8)
    b.text('OREGON TRAIL',(885,285,195,34),'#268158','road')
    wagon(b,915,400,125,'#268158',WHITE)
    return b

def pa():
    b=Board(640,'#f5f2df','#1f4b94')
    b.text('WELCOME TO',(370,40,460,65),'#bd3445','road')
    # The 2024 heading arches gently over the Liberty Bell.
    b.arched_text('PENNSYLVANIA',(80,145,1040,115),'#214b94',35)
    b.text('EST.',(225,356,200,57),'#214b94','serif_bold')
    b.text('1681',(790,356,200,57),'#214b94','serif_bold')
    b.d.rectangle((510,290,690,350),fill='#bd3445')
    b.path([(568,333),(563,393,552,430,520,461),(552,478,647,478,680,461),(648,430,637,393,632,333),(617,320),(582,320),(568,333)],'#214b94')
    b.ellipse((578,475,623,492),'#214b94')
    b.path([(591,382),(584,419),(592,430),(579,468)],stroke=WHITE,width=5)
    b.text('LET FREEDOM RING',(120,545,960,65),'#bd3445','serif_bold',True)
    return b

def ri():
    b=Board(850,'#eeeee4','#264b69')
    # Small sailboat vignette above the three lines of lettering.
    b.d.line((600,55,600,240),fill='#264b69',width=6)
    b.path([(585,68),(500,199),(585,195)],'#315e7d')
    b.path([(615,88),(683,200),(615,195)],'#315e7d')
    b.path([(480,215),(710,215),(665,245),(520,245)],'#315e7d')
    for y in (260,280):b.path([(445,y),(505,y-18,550,y+18,600,y),(650,y-18,700,y+18,755,y)],stroke='#6594ad',width=6)
    b.text('Welcome To',(190,350,820,77),'#264b69','sans')
    b.text('Rhode Island',(80,485,1040,113),'#264b69','serif_bold',True)
    b.text('The Ocean State',(105,665,990,85),'#264b69','sans')
    return b

def sc():
    b=Board(650,'#104b82','#c34246')
    b.ellipse((60,70,480,490),'#174e80',WHITE,6)
    b.ellipse((100,110,440,450),WHITE,'#c34246',5)
    b.state('SC',(135,180,270,240),'#1e5e9b')
    b.circle_text('SMILING FACES',270,280,188,2.0)
    b.circle_text('BEAUTIFUL PLACES',270,280,188,2.45,True)
    b.text('Welcome to',(520,125,610,100),style='script')
    b.text('South',(585,290,485,90),style='serif')
    b.text('Carolina',(490,425,640,115),style='serif')
    return b

def sd():
    b=Board(760,'#faf4df','#346c68')
    b.text('South Dakota',(170,30,860,120),'#a82f41','script',True)
    # Original line illustration of the four presidents, in the gold/cream
    # palette and composition of the documented Great Faces board.
    g='#bf964e';cream='#faf4df'
    b.path([(170,620),(215,480),(205,290),(270,185),(355,180),(420,290),(495,235),(560,250),(610,350),(675,290),(750,310),(805,270),(895,285),(970,385),(1000,620)],g)
    faces=[(275,280,1.1),(476,322,.87),(658,358,.81),(837,338,.96)]
    for j,(x,y,s) in enumerate(faces):
        def p(q,col):b.path([tuple(v*s+(x if i%2==0 else y) for i,v in enumerate(z)) for z in q],col)
        p([(-45,-65),(7,-97,75,-50,66,3),(54,30),(67,53),(40,58),(31,93),(4,105),(-32,71),(-45,15),(-45,-65)],cream)
        p([(-40,-39),(-22,-55,18,-53,45,-30),(21,-26),(-5,-38),(-40,-39)],g)
        p([(-24,-5),(-4,-11),(16,-3),(2,5),(-24,-5)],g)
        p([(18,-12),(20,27),(35,34),(14,42),(10,28),(18,-12)],g)
        p([(-5,59),(30,56),(13,66),(-5,59)],g)
        p([(-37,60),(-5,112),(34,96),(49,118),(11,151),(-57,100),(-37,60)],cream)
        if j==2:
            for dx in (-15,31):b.ellipse((x+(dx-16)*s,y-12*s,x+(dx+16)*s,y+15*s),None,g,4)
        if j==3:p([(-36,56),(-5,93),(31,77),(35,112),(-4,135),(-30,110),(-36,56)],g)
    b.text('GREAT FACES. GREAT PLACES.',(170,665,860,52),'#28555c','road')
    return b

def tn():
    b=Board(670,'#1c508c',WHITE)
    b.state('TN',(45,80,1110,360),WHITE)
    b.text('Tennessee',(170,185,780,112),'#19242f','script',True)
    b.text('The Volunteer State',(180,310,640,45),'#19242f','serif')
    b.text('Welcomes You',(100,505,870,90),style='sans')
    b.d.rectangle((990,475,1140,580),fill='#ba333e')
    b.d.rectangle((1127,475,1140,580),fill='#0a3a79')
    b.ellipse((1020,490,1098,568),'#153976',WHITE,4)
    for x,y in ((1059,510),(1041,544),(1076,544)):b.star(x,y,12,WHITE)
    return b

def tx():
    b=Board(733,'#006b51',WHITE,70)
    b.text('Welcome to Texas',(120,45,960,107),style='script')
    b.path([(360,185),(515,140,590,273,800,225),(815,355,785,480,865,555),(680,620,600,465,448,508),(360,185)],WHITE)
    b.path([(404,342),(580,280,660,453,821,402),(820,455,830,520,865,555),(680,620,600,465,448,508),(404,342)],'#e72f36')
    b.path([(360,185),(425,160,485,180,522,212),(550,310,567,408,583,510),(530,494,490,490,448,508),(360,185)],'#3454a0')
    b.star(455,320,75,WHITE,angle=-math.pi/2+.10)
    b.d.line((340,175,455,605),fill='#f2dc29',width=12);b.ellipse((329,156,351,178),'#f2dc29')
    b.text('DRIVE FRIENDLY - THE TEXAS WAY',(80,635,1040,49),style='road',stretch=True)
    return b

def ut():
    b=Board(740,'#144976')
    b.text('Welcome to',(60,48,530,95),'#efdfae','script')
    b.text('UTAH',(340,175,690,150),style='serif_bold',stretch=True)
    b.path([(0,600),(180,390),(310,475),(490,340),(700,525),(870,420),(1200,560),(1200,740),(0,740)],'#87afc3')
    b.path([(0,600),(180,390),(165,475),(250,475),(310,525),(490,340),(420,510),(545,480),(700,590),(870,420),(810,550),(1200,650),(1200,740),(0,740)],'#d5e4e9')
    b.path([(0,680),(270,540,500,600,670,645),(920,560,1050,610,1200,680),(1200,740),(0,740)],'#e6eded')
    # Life Elevated skier edition: original vector scenery, not a photo strip.
    b.ellipse((765,338,800,373),'#293746')
    b.path([(764,371),(702,405),(684,439),(708,452),(749,416),(792,394)],'#aec33b')
    b.path([(706,447),(655,471),(630,504),(653,514),(690,483),(729,475),(748,447)],'#253b48')
    b.d.line((618,515,786,530),fill='#223746',width=9)
    b.d.line((659,540,829,549),fill='#223746',width=8)
    b.d.line((766,402,821,426),fill='#243b48',width=8)
    b.d.line((821,425,850,540),fill='#243b48',width=4)
    b.text('L I F E   E L E V A T E D',(165,660,870,42),'#8c7f3b','sans')
    return b

def vt():
    b=Board(720,WHITE)
    b.path([(0,155),(90,125),(135,70),(245,160),(350,115),(450,175),(535,125),(680,180),(795,130),(875,190),(1030,120),(1200,160),(1200,720),(0,720)],'#146348')
    b.text('Welcome To',(150,215,900,110),style='script')
    b.text('VERMONT',(65,380,1070,155),style='serif_bold',stretch=True)
    b.text('The Green Mountain State',(95,620,1010,58),style='italic')
    return b

def va():
    b=Board(780,'#f1eee2','#172f58')
    b.text('Virginia',(90,50,1020,205),'#213866','serif',True)
    b.path([(175,560),(430,450,730,560,1030,440)],stroke='#75533a',width=13)
    for x,y in ((255,535),(400,510),(820,495),(955,465)):
        b.path([(x,y),(x-45,y-15,x-60,y-60,x-20,y-75),(x+10,y-65,x+15,y-20,x,y)],'#548346')
        flower(b,x,y,49,'#fffdf0','#d4b96a',4)
    bird(b,610,440,175,True)
    b.text('Welcomes You',(155,645,890,86),'#9b3243','serif')
    return b

def wa():
    b=Board(760,'#176b50',WHITE)
    b.state('WA',(75,65,1050,645),WHITE)
    b.text('Welcome To',(330,270,680,73),'#176b50','sans')
    b.text('Washington',(205,385,870,150),'#176b50','script',True)
    b.text('The Evergreen State',(360,535,650,43),'#176b50','sans')
    return b

def wv():
    b=Board(720,'#83b8ca',WHITE)
    # Layered Appalachian ridges retain the scenic design without reusing photo pixels.
    rng=random.Random(41)
    for level,col in ((230,'#5b93a0'),(310,'#497b7a'),(405,'#335c54'),(500,'#224f40')):
        points=[(0,level+100)]+[(x,level+rng.randrange(-55,55)) for x in range(0,1240,40)]+[(1200,720),(0,720)]
        b.d.polygon(points,fill=col)
    for x in range(0,1200,35):b.pine(x,715,rng.randrange(100,190),'#21452f')
    b.text('Welcome To',(80,60,720,85),style='italic')
    b.text('WEST VIRGINIA',(55,245,860,175),'#f4e6bb','road',True,outline='#264d43')
    b.emblem('wv',(930,210,230,230))
    b.text('Wild and Wonderful',(140,560,920,92),'#eed455','italic')
    return b

def wi():
    b=Board(650,(0,0,0,0))
    b.d.rounded_rectangle((145,210,1190,640),radius=55,fill='#184b92',outline=WHITE,width=10)
    # A separate Wisconsin-shaped plate projects above the blue board.
    rings=b.state('WI',(10,10,395,360),'#21795b',WHITE,7)
    b.text('WELCOME TO',(420,285,710,90),style='road',stretch=True)
    b.text('WISCONSIN',(225,450,900,105),style='road',stretch=True)
    # Rectangular body and state cutout are represented as separate polygons.
    b.panels=[[(145,210),(1190,210),(1190,640),(145,640)]]+[r[:-1] if r[0]==r[-1] else r for r in rings if len(r)>12]
    return b

def wy():
    b=Board(650,'#644631');b.wood('#715036')
    b.d.rectangle((45,45,1155,605),fill='#91c0d0')
    # Devils Tower edition; steep fluted monolith rather than generic peaks.
    b.path([(50,400),(170,310),(350,340),(480,295),(650,370),(840,295),(1150,340),(1150,605),(50,605)],'#536b49')
    b.path([(390,480),(450,325),(480,145),(500,122),(680,125),(710,160),(735,325),(810,480)],'#b6aa7f')
    for x in range(485,710,16):b.path([(x,145),(x-7,230,x-6,325,x-50,465)],stroke='#7e775a',width=5)
    rng=random.Random(8)
    for x in range(45,1155,16):b.pine(x,565,rng.randrange(65,170),'#355236')
    b.d.rectangle((0,605,1200,650),fill='#644631')
    b.d.rectangle((0,0,45,650),fill='#644631');b.d.rectangle((1155,0,1200,650),fill='#644631')
    b.text('WYOMING',(230,450,850,100),style='serif_bold',stretch=True)
    b.text('WELCOMES YOU',(390,560,570,31),style='sans')
    # Small bucking horse and rider silhouette at lower left.
    b.path([(95,480),(132,435),(162,450),(180,430),(210,449),(238,435),(248,451),(213,476),(200,505),(236,530),(220,541),(180,520),(155,492),(125,505),(102,540),(85,530),(110,487)],'#252e27')
    b.path([(162,450),(163,409),(180,390),(188,417),(183,443)],'#252e27')
    b.ellipse((166,373,187,397),'#252e27');b.d.line((158,385,194,385),fill='#252e27',width=6)
    b.d.line((180,413,206,379),fill='#252e27',width=8)
    return b


DRAWINGS={k.upper():v for k,v in list(globals().items()) if len(k)==2 and callable(v)}
DRAWINGS.update(IN=indiana,OR=ore)
