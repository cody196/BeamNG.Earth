-- End-to-end GPS/vehicle-bridge sequencing with streamed maps, a fake clock and stock AI path semantics.
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local G = require('beamngEarth/gps')
local A = dofile(dir .. '/../beamng_earth/lua/vehicle/extensions/beamngEarthAutodrive.lua')
local N = require('beamngEarth/navgraph')
local now, serial, ready, healthy, paused = 0, 1, true, true, false
os.clock = function() return now end
N.applies = function() return serial end
function vec3(x,y,z) return {x=x,y=y,z=z or 0} end
function log() end
local messages = {}
function ui_message(text) messages[#messages+1] = text end
simTimeAuthority = {getPause=function() return paused end}
local pos, vel, direction = vec3(40,0,0), vec3(33,0,0), vec3(1,0,0)
local nodes, vehicleMaps = {}, {}
local gmMap = {nodes=nodes,buildSerial=serial}
map = {getMap=function() return gmMap end,objects={[77]={damage=0}}}
local commands, starts, additions, stops, requests = {}, 0, 0, 0, 0
local manualPath, currentRoute, aiMap
local function copy(xs) local a={}; for i,x in ipairs(xs) do a[i]=x end; return a end
local lastRequest, reply, returnRoute, routeFail = nil, nil, true, false
beamngEarth_core = {
  serverHealthy=function() return healthy end,
  autodriveReady=function() return ready end,
  requestRoute=function(id)
    requests=requests+1; lastRequest=id
    if returnRoute then
      reply=routeFail and {error='no route'} or {points={{0,pos.x},{0,6000}},dist=6000-pos.x,dur=200}
    end
    return true
  end,
  takeRoute=function(id) if id==lastRequest and reply then local r=reply; reply=nil; return r end end,
}
local veh = {getPosition=function() return pos end,getVelocity=function() return vel end,
  getDirectionVector=function() return direction end,getId=function() return 77 end,
  queueLuaCommand=function(_,code)
    commands[#commands+1]=code
    local f,err=loadstring(code); assert(f,err); f()
  end}
function getPlayerVehicle() return veh end
local function installGraph(first,last,broken)
  nodes={}
  local data={graph={}}
  for x=first,last,100 do
    local id='n'..x
    nodes[id]={pos=vec3(x,0,0),radius=3.7,links={}}
    data.graph[id]={}
  end
  for x=first,last-100,100 do
    if x~=broken then
      local a,b='n'..x,'n'..(x+100)
      local e={oneWay=true,inNode=a}
      nodes[a].links[b]=e
      data.graph[a][b],data.graph[b][a]=e,e
    end
  end
  gmMap.nodes,gmMap.buildSerial=nodes,serial
  vehicleMaps[serial]=data
end
installGraph(0,700)
mapmgr={mapData=vehicleMaps[serial],setMap=function(s) mapmgr.mapData=vehicleMaps[s] end}
input={event=function() end}
obj={queueGameEngineLua=function(_,code) assert(loadstring(code))() end}
ai={mode='disabled',setMode=function(mode)
    ai.mode,currentRoute,manualPath=mode,nil,nil
    if mode=='stop' then stops=stops+1 end
  end,
  driveUsingPath=function(p)
    starts=starts+1; ai.mode,currentRoute,aiMap,manualPath='manual',nil,nil,copy(p.path)
  end,
  setPath=function(ids) additions=additions+1; manualPath=copy(ids) end}
extensions={load=function() return true end,beamngEarthAutodrive=A}
local function frame()
  if aiMap~=mapmgr.mapData then currentRoute=nil end
  aiMap=mapmgr.mapData
  if manualPath then
    if currentRoute then
      if currentRoute[#currentRoute]==manualPath[1] then
        for i=2,#manualPath do currentRoute[#currentRoute+1]=manualPath[i] end
      end
    else currentRoute=copy(manualPath) end
    manualPath=nil
  end
  A.updateGFX()
end
local function settle() frame(); frame() end
local emptyPath=false
core_groundMarkers={routePlanner={path={},calcDistance=function() end},setPath=function(target)
  local path={}
  if target and not emptyPath then
    local tg=target[#target] or target
    local order={}
    for id,n in pairs(nodes) do if n.pos.x>pos.x and n.pos.x<=tg.x+50 then order[#order+1]=id end end
    table.sort(order,function(a,b) return nodes[a].pos.x<nodes[b].pos.x end)
    for _,id in ipairs(order) do path[#path+1]={wp=id,pos=nodes[id].pos} end
  end
  core_groundMarkers.routePlanner.path=path
end}
local anchor={geodeticToEnu=function(_,lat,lon) return lon,lat,0 end}
local function tick(seconds,skipFrames)
  now=now+(seconds or 1.1)
  G.update(anchor,{x=pos.x,y=pos.y,lat=pos.y,lon=pos.x})
  if not skipFrames then settle() end
end
G.setDestination(0,6000,'Highway')
G.setAutodrive(true)
tick(); tick()
T.check(starts==1 and currentRoute and currentRoute[1]=='n0' and currentRoute[2]=='n100',
  'GPS activation starts on the forward edge under the vehicle')
local initialStarts=starts
for i=1,5 do pos.x=pos.x+20; tick() end
T.check(starts==initialStarts and requests==1, 'normal highway travel does not restart AI or reroute')

-- Graph apply, then GPS arrow update, BEFORE the next vehicle frame: this was a repeated reset.
local keep=G.beforeGraph(nodes)
serial=serial+1; installGraph(100,1200)
G.afterGraph(keep,nodes)
tick(nil,true); settle()
T.check(starts==initialStarts and additions>=1 and currentRoute[1]=='n100' and currentRoute[#currentRoute]=='n1200',
  'a streamed graph restores and extends the highway route without resetting speed controls')

-- Delayed terrain alone is not a reason to brake on already loaded road.
healthy=false; tick()
T.check(ai.mode=='manual' and starts==initialStarts, 'continue on loaded road when only a terrain request is late')
ready=false; tick()
T.check(ai.mode=='stop' and G.status().autoWaiting=='server', 'disconnect/resync holds the car')
ready,healthy=true,true; tick()
T.check(ai.mode=='manual', 'the world becoming ready resumes GPS driving')

-- No usable edge ahead: never switch the player's car to free-roaming traffic.
keep=G.beforeGraph(nodes)
serial=serial+1; installGraph(100,1200,100)
G.afterGraph(keep,nodes); settle(); tick()
T.check(ai.mode=='stop' and G.status().autodrive, 'a disappearing forward edge holds while retaining Autodrive intent')
T.check(not table.concat(commands,'\n'):find('setMode("traffic")',1,true), 'no traffic-mode fallback')
serial=serial+1; installGraph(100,1400); tick()
T.check(ai.mode=='manual' and currentRoute[1]=='n100', 'newly loaded drivable road automatically releases the hold')

-- An empty arrows result must leave the existing, valid route running.
emptyPath=true
keep=G.beforeGraph(nodes); serial=serial+1; installGraph(100,1400); G.afterGraph(keep,nodes); tick()
T.check(ai.mode=='manual', 'an empty planner result preserves the already validated route')
emptyPath=false
local beforeStops=stops
vel=vec3(0,0,0)
for i=1,10 do tick() end
T.check(stops==beforeStops and G.status().autoRecoveries==0, 'a short traffic stop does not reset AI')
paused=true; tick(60); paused=false; tick()
T.check(G.status().autoRecoveries==0, 'time spent paused is excluded from stuck recovery')

-- A circle can remain within the old off-route tolerance and never fall below 1 m/s.
vel=vec3(5,0,0); returnRoute=false
for i=1,50 do
  pos.x,pos.y=150+8*math.cos(i*0.7),8*math.sin(i*0.7)
  tick()
  if G.status().autoRecoveries>0 then break end
end
T.check(G.status().autoRecoveries==1 and ai.mode=='stop' and G.status().planning,
  'moving in circles triggers a controlled stop and a new route request')
-- Reply with a fresh route, heading east along the available road again.
pos.x,pos.y=150,0; returnRoute=true
reply={points={{0,150},{0,6000}},dist=5850,dur=180}
tick()
T.check(ai.mode=='manual' and currentRoute[1]=='n100', 'a fresh GPS route resumes after loop recovery')
pos.x=180; tick()
T.check(G.status().autoRecoveries==0, 'real forward progress clears recovery attempts')

-- Repeated unresolvable stalls are bounded; the car must not spin and restart forever.
returnRoute,routeFail,vel=true,true,vec3(0,0,0)
for i=1,220 do tick() end
T.check(not G.autodrive() and ai.mode=='disabled' and messages[#messages]:find('unable to find',1,true),
  'repeated failed recovery hands control back with an explanation')
G.clear()
T.done('test_gps_autodrive')
