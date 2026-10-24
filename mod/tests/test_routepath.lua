local T=dofile((arg[0]:match('^(.*)[/\\]') or '.')..'/testlib.lua')
local R=require('beamngEarth/routepath')
local function node(x,y,z) return {pos={x=x,y=y or 0,z=z or 0},radius=5,links={}} end
local function edge(ns,a,b,oneWay)
  -- Store on the far node to exercise the stock single-sided representation.
  ns[b].links[a]={inNode=a,oneWay=oneWay~=false}
end
local function route(points)
  local e={x={},y={},cum={0}}
  for i,p in ipairs(points) do
    e.x[i],e.y[i]=p[1],p[2]
    if i>1 then e.cum[i]=e.cum[i-1]+math.sqrt((p[1]-points[i-1][1])^2+(p[2]-points[i-1][2])^2) end
  end
  return e
end
local nodes={}
for x=0,800,100 do nodes['h'..x]=node(x,0) end
for x=0,700,100 do edge(nodes,'h'..x,'h'..(x+100)) end
nodes.r1=node(250,20)
nodes.r2= node(300,65)
nodes.r3= node(400,80,5)
nodes.bridge1=node(400,0,8)
nodes.bridge2=node(400,-100,8)
edge(nodes,'h200','r1'); edge(nodes,'r1','r2'); edge(nodes,'r2','r3')
edge(nodes,'r3','bridge1'); edge(nodes,'bridge1','bridge2')
local main=route({{0,0},{2000,0}})
local result=R.plan(nodes,R.graph(nodes),main,40,1500,'h0','h100',{x=40,y=0})
T.check(table.concat(result.ids,',')=='h0,h100,h200,h300,h400,h500,h600,h700,h800',
  'stay on the highway when a connected exit reaches a bridge crossing the GPS route')
T.check(not result.final and result.s==800,'loaded highway endpoint is not the GPS destination')
local shifted=route({{0,12},{2000,12}})
result=R.plan(nodes,R.graph(nodes),shifted,40,1500,'h0','h100',{x=40,y=0})
T.check(result.ids[#result.ids]=='h800','a persistent OSM/rendered-road offset does not prematurely end the path')

local exitRoute=route({{0,0},{200,0},{250,20},{300,65},{400,80},{400,0},{400,-100}})
result=R.plan(nodes,R.graph(nodes),exitRoute,40,1500,'h0','h100',{x=40,y=0})
T.check(table.concat(result.ids,',')=='h0,h100,h200,r1,r2,r3,bridge1,bridge2',
  'take the exit and bridge when the planned route actually uses them')
T.check(result.final,'only the end of the planned exit route is final')

-- Two decks occupy identical XY: connectivity must decide, not iteration order or altitude averaging.
for x=0,800,100 do nodes['upper'..x]=node(x,0,9) end
for x=0,700,100 do edge(nodes,'upper'..x,'upper'..(x+100)) end
result=R.plan(nodes,R.graph(nodes),main,340,1500,'h300','h400',{x=340,y=0})
T.check(result.ids[1]=='h300' and result.ids[#result.ids]=='h800' and not table.concat(result.ids):find('upper'),
  'a parallel overhead road cannot replace the connected highway')

-- A missing mainline edge may not be bypassed via a ramp and a crossing road.
nodes.h400.links.h300=nil
result=R.plan(nodes,R.graph(nodes),main,40,1500,'h0','h100',{x=40,y=0})
T.check(table.concat(result.ids,',')=='h0,h100,h200,h300',
  'a loading gap ends the usable highway path without an unrelated exit detour')
T.check(not result.final,'a gap cannot report arrival')
T.check(R.plan(nodes,R.graph(nodes),main,40,1500,'h100','h0',{x=40,y=0})==nil,
  'one-way carriageways cannot be followed backwards')

local curve={a=node(0,0),b=node(100,0),c=node(100,100),d=node(200,100)}
edge(curve,'a','b');edge(curve,'b','c');edge(curve,'c','d');edge(curve,'b','d')
result=R.plan(curve,R.graph(curve),route({{0,0},{100,0},{100,100},{200,100}}),40,1500,'a','b',{x=40,y=0})
T.check(table.concat(result.ids,',')=='a,b,c,d','a diagonal shortcut across the planned corner is excluded')
local loop={a=node(0,0),b=node(100,0),c=node(100,200),d=node(200,200),e=node(200,0)}
edge(loop,'a','b');edge(loop,'b','c');edge(loop,'c','d');edge(loop,'d','e');edge(loop,'b','e')
result=R.plan(loop,R.graph(loop),route({{0,0},{100,0},{100,200},{200,200},{200,0}}),40,1500,'a','b',{x=40,y=0})
T.check(table.concat(result.ids,',')=='a,b,c,d,e','crossing close to a later route leg cannot skip the connecting ramp')
-- A slowly changing offset used to cost more than forward progress, turning a
-- connected, in-corridor highway into an artificial endpoint after several miles.
local drift={}
for i=0,12 do
  drift['d'..i]=node(i*50,math.min(22,i*2))
  if i>0 then edge(drift,'d'..(i-1),'d'..i) end
end
result=R.plan(drift,R.graph(drift),main,20,1500,'d0','d1',{x=20,y=0.8})
T.check(result.ids[#result.ids]=='d12' and result.length>570,
  'gradual road/GPS offset inside the corridor cannot manufacture a dead end')
local joins={a=node(0,0),b=node(100,0),c=node(98,6),d=node(200,6),e=node(500,6)}
edge(joins,'a','b');edge(joins,'b','c');edge(joins,'c','d');edge(joins,'d','e')
result=R.plan(joins,R.graph(joins),main,40,1500,'a','b',{x=40,y=0})
T.check(table.concat(result.ids,',')=='a,b,c,d,e',
  'a short junction connector with small projection backtracking does not stop the highway path')
local _,diag=R.plan(joins,R.graph(joins),main,40,1500,'b','a',{x=40,y=0})
T.check(diag and diag.reason=='no_forward_edge','unusable starts report a diagnostic reason')
joins.c.pos.y=50
result,diag=R.plan(joins,R.graph(joins),main,40,1500,'a','b',{x=40,y=0})
T.check(result.ids[#result.ids]=='b' and diag and diag.corridor>0,
  'relaxed connector matching still rejects roads outside the planned route corridor')
T.done('test_routepath')
